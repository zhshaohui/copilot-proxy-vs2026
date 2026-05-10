"""
Enhanced stream server for VS2026 GitHub Copilot tool calling support.
"""
import json
import http.server
import threading
import requests
import sys
import os
import re
import random
import string
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from copilot_proxy.config import MODEL_URL, MODEL_API_KEY, MODEL_NAME

DASHSCOPE_URL = MODEL_URL
DASHSCOPE_KEY = MODEL_API_KEY
STREAM_PORT = 15433
# Use current working directory for logs to ensure compatibility and privacy
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stream_debug.log")

READ_ONLY_TOOLS = {
    "get_files_in_project", "get_file", "file_search", "code_search",
    "get_errors", "get_projects_in_solution", "get_symbols_by_name",
    "find_symbol", "get_web_pages", "nuget_get-package-readme"
}

def log(msg: str):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

def generate_tool_call_id():
    return f"call_{''.join(random.choices(string.ascii_letters + string.digits, k=12))}"

def extract_context_from_history(messages, tool_name, used_paths=None):
    result = {}
    log(f"[CTX] tool={tool_name}, msgs={len(messages)}")
    tool_results = []
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "tool":
            c = msg.get("content", "")
            try: c = json.loads(c) if isinstance(c, str) else c
            except: pass
            tool_results.append({"content": c, "tool_call_id": msg.get("tool_call_id", "")})
    if tool_name == "get_files_in_project":
        for tr in tool_results:
            items = tr["content"] if isinstance(tr["content"], list) else []
            if isinstance(tr["content"], str):
                try:
                    p = json.loads(tr["content"])
                    items = p if isinstance(p, list) else []
                except:
                    for l in tr["content"].split("\n"):
                        l = l.strip()
                        if l.endswith((".csproj", ".sln")): items.append({"name": l})
            for it in items:
                n = it.get("name", "") if isinstance(it, dict) else ""
                if n.endswith((".csproj", ".sln")) and n not in (used_paths or set()):
                    result["projectPath"] = n; return result
    if tool_name == "get_file":
        for tr in tool_results:
            items = tr["content"] if isinstance(tr["content"], list) else []
            if isinstance(tr["content"], str):
                try:
                    p = json.loads(tr["content"])
                    items = p if isinstance(p, list) else [p] if isinstance(p, dict) else []
                except:
                    for l in tr["content"].split("\n"):
                        l = l.strip()
                        if "." in l: items.append({"path": l})
            for it in items:
                fn = it.get("path") or it.get("name") or it.get("filePath", "") if isinstance(it, dict) else ""
                if fn and fn not in (used_paths or set()):
                    result["filename"] = fn; return result
    return result

def parse_qwen_tool_calls(content, tools=None):
    tool_calls = []
    pattern = r'\s*(.*?)\s*'
    matches = list(re.finditer(pattern, content, re.DOTALL))
    if not matches: return None
    log(f"[PARSE] Found {len(matches)} XML blocks")
    for i, match in enumerate(matches):
        json_str = match.group(1).strip()
        try:
            tool_data = json.loads(json_str)
            if not isinstance(tool_data, dict) or "name" not in tool_data: continue
            args = tool_data.get("arguments", {})
            if isinstance(args, str):
                try: args = json.loads(args)
                except: args = {"raw": args}
            if tools and (not args or args == {}):
                for t in tools:
                    if isinstance(t, dict) and t.get("function", {}).get("name") == tool_data["name"]:
                        params = t.get("function", {}).get("parameters", {})
                        args = {k: "" for k in params.get("required", [])}
                        break
            tool_calls.append({
                "id": generate_tool_call_id(),
                "type": "function",
                "index": i,
                "function": {
                    "name": tool_data["name"],
                    "arguments": json.dumps(args) if isinstance(args, dict) else str(args)
                }
            })
        except json.JSONDecodeError as e:
            log(f"[PARSE] JSON error: {e}")
            continue
    return tool_calls if tool_calls else None

def sanitize_chunk(chunk, tool_call_state=None, tools=None):
    if not isinstance(chunk, dict): return chunk
    sanitized = {k: v for k, v in chunk.items() if v is not None}
    choices = chunk.get("choices", [])
    if not isinstance(choices, list): choices = []
    if not choices:
        sanitized["choices"] = [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]
        return sanitized
    first = choices[0]
    delta = first.get("delta", {}) if isinstance(first, dict) else {}
    clean_delta = {}
    role = delta.get("role")
    if role and isinstance(role, str): clean_delta["role"] = role
    content = delta.get("content")
    content_str = ""
    if content is not None:
        content_str = content if isinstance(content, str) else str(content)
        clean_delta["content"] = content_str
    reasoning = delta.get("reasoning_content")
    if reasoning and isinstance(reasoning, str): clean_delta["reasoning_content"] = reasoning
    # Handle XML in streaming buffer
    if tool_call_state is not None and content_str:
        buf = tool_call_state.setdefault("_qwen_buf", "")
        buf += content_str
        tool_call_state["_qwen_buf"] = buf
        start_marker = ""
        end_marker = ""
        if start_marker in buf and end_marker in buf:
            start_idx = buf.find(start_marker)
            end_idx = buf.find(end_marker, start_idx)
            if end_idx != -1:
                xml_block = buf[start_idx:end_idx + len(end_marker)]
                qwen_tool_calls = parse_qwen_tool_calls(xml_block, tools)
                if qwen_tool_calls:
                    clean_delta["tool_calls"] = qwen_tool_calls
                    log(f"[XML] Parsed {len(qwen_tool_calls)} tool calls")
                    tool_call_state["_qwen_buf"] = buf[end_idx + len(end_marker):]
                    clean_delta["content"] = ""
                else:
                    clean_delta["content"] = ""
            else:
                clean_delta["content"] = ""
        elif start_marker in buf:
            clean_delta["content"] = ""
    elif content_str and "" in content_str:
        qwen_tool_calls = parse_qwen_tool_calls(content_str, tools)
        if qwen_tool_calls:
            clean_delta["tool_calls"] = qwen_tool_calls
            clean_delta["content"] = ""
    # Handle standard tool_calls
    tool_calls = delta.get("tool_calls")
    if tool_calls and isinstance(tool_calls, list):
        clean_tool_calls = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                func = tc.get("function", {})
                if not isinstance(func, dict): func = {}
                name = func.get("name", "")
                args_raw = func.get("arguments", "")
                if not name and not args_raw: continue
                clean_tc = {}
                tc_index = tc.get("index", 0)
                if tc.get("id"):
                    clean_tc["id"] = tc["id"]
                    tool_call_state[tc_index] = tc["id"]
                elif tc_index in tool_call_state:
                    clean_tc["id"] = tool_call_state[tc_index]
                clean_tc["index"] = tc_index
                if tc.get("type"): clean_tc["type"] = tc["type"]
                clean_func = {}
                if name and name.strip(): clean_func["name"] = name.strip()
                needs_injection = (not args_raw or args_raw == "{}" or args_raw == "")
                if not needs_injection and args_raw:
                    try:
                        parsed = json.loads(args_raw)
                        if isinstance(parsed, dict) and parsed:
                            values = [v for v in parsed.values()]
                            if values and all(v in [".", "", 0] for v in values): needs_injection = True
                    except: pass
                if needs_injection and name and name.strip() and name in READ_ONLY_TOOLS:
                    messages = tool_call_state.get("_messages", []) if tool_call_state else []
                    used = tool_call_state.setdefault("_used_paths", set())
                    context = extract_context_from_history(messages, name, used)
                    default_args = {}
                    if tools:
                        for t in (tools or []):
                            fn = t.get("function", {}) if isinstance(t, dict) else {}
                            if fn.get("name") == name:
                                required = fn.get("parameters", {}).get("required", [])
                                for req_param in required:
                                    if req_param in context and context[req_param] not in used:
                                        default_args[req_param] = context[req_param]
                                        log(f"[INJECT] {name}.{req_param}={context[req_param]}")
                                break
                    if default_args:
                        clean_func["arguments"] = json.dumps(default_args)
                    else:
                        clean_func["arguments"] = "{}" if not args_raw else args_raw
                else:
                    clean_func["arguments"] = "{}" if not args_raw else args_raw
                if clean_func.get("name") or clean_func.get("arguments"):
                    clean_tc["function"] = clean_func
                    clean_tool_calls.append(clean_tc)
        if clean_tool_calls:
            clean_delta["tool_calls"] = clean_tool_calls
            log(f"[TOOL_CALLS] Preserved {len(clean_tool_calls)} standard tool calls")
    clean_delta.setdefault("content", None)
    if "content" in clean_delta and clean_delta["content"] == "":
        pass
    if not clean_delta.get("tool_calls") and "content" not in clean_delta:
        clean_delta["content"] = ""
    sanitized["choices"] = [{
        "index": first.get("index", 0),
        "delta": clean_delta,
        "finish_reason": None,
    }]
    return sanitized

def stream_chat(messages, tools=None, tool_choice=None):
    """Non-streaming call for faster response (returns full text at once)."""
    if not DASHSCOPE_URL:
        error_msg = "MODEL_URL environment variable is not set"
        yield f"data: {json.dumps({'error': {'message': error_msg, 'type': 'config_error'}})}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
        return
    
    log(f"[REQUEST] model={MODEL_NAME}, msgs={len(messages)}, tools={len(tools or [])}, choice={tool_choice} [NON-STREAMING]")
    
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
        "enable_thinking": True,
    }
    
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice

    try:
        # Send request (non-streaming)
        resp = requests.post(
            DASHSCOPE_URL.rstrip("/") + "/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        
        log(f"[API] HTTP {resp.status_code}")
        if resp.status_code != 200:
            log(f"[API] ERROR: {resp.text[:500]}")
            error_data = {
                "id": "error",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": MODEL_NAME,
                "choices": [{"index": 0, "delta": {"content": f"Error: {resp.status_code} - {resp.text[:200]}"}, "finish_reason": "stop"}]
            }
            yield f"data: {json.dumps(error_data)}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"
            return

        # Parse full JSON response
        full_response = resp.json()
        choices = full_response.get("choices", [])
        if not choices:
            yield b"data: [DONE]\n\n"
            return

        choice = choices[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        reasoning_content = message.get("reasoning_content", "")
        tool_calls = message.get("tool_calls")
        
        # 1. Yield Role
        role_chunk = {
            "id": full_response.get("id", "non-stream-role"),
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": MODEL_NAME,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]
        }
        yield f"data: {json.dumps(role_chunk)}\n\n".encode("utf-8")

        # 2. Yield Content (and Reasoning)
        delta = {}
        if reasoning_content:
            delta["reasoning_content"] = reasoning_content
        
        content_chunk = {
            "id": full_response.get("id", "non-stream-content"),
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": MODEL_NAME,
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}]
        }
        
        if tool_calls:
            clean_tool_calls = []
            for tc in tool_calls:
                func = tc.get("function", {})
                if func: clean_tool_calls.append(tc)
            content_chunk["choices"][0]["delta"]["tool_calls"] = clean_tool_calls
            log(f"[TOOL_CALLS] Found {len(clean_tool_calls)} tool calls")
        else:
            delta["content"] = content

        yield f"data: {json.dumps(content_chunk)}\n\n".encode("utf-8")

        # 3. Yield Done (Signal stream end)
        done_chunk = {
            "id": full_response.get("id", "non-stream-done"),
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": MODEL_NAME,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
        }
        yield f"data: {json.dumps(done_chunk)}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
        
    except requests.exceptions.RequestException as e:
        log(f"[ERROR] {e}")
        error_data = {
            "id": "error",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": MODEL_NAME,
            "choices": [{"index": 0, "delta": {"content": f"Request failed: {str(e)}"}, "finish_reason": "stop"}]
        }
        yield f"data: {json.dumps(error_data)}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"

class StreamHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        log(f"[HTTP] POST path={self.path}")
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            self.send_error(400, f"Invalid JSON: {e}")
            return
        messages = data.get("messages", [])
        tools = data.get("tools", [])
        tool_choice = data.get("tool_choice", None)
        log(f"[HTTP] POST /chat/completions - {len(messages)} messages, {len(tools)} tools")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.flush()
        try:
            for chunk in stream_chat(messages, tools, tool_choice):
                self.wfile.write(chunk)
                self.wfile.flush()
        except BrokenPipeError:
            log("[HTTP] Client disconnected")
        except Exception as e:
            log(f"[HTTP] Error: {e}")
            try:
                error_data = {
                    "id": "error",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": MODEL_NAME,
                    "choices": [{"index": 0, "delta": {"content": f"Server error: {str(e)}"}, "finish_reason": "stop"}]
                }
                self.wfile.write(f"data: {json.dumps(error_data)}\n\n".encode("utf-8"))
            except: pass
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Stream server running")
    def log_message(self, format, *args):
        pass  # Suppress default logging

def start_stream_server():
    server = http.server.HTTPServer(("127.0.0.1", STREAM_PORT), StreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log(f"[SERVER] Started on port {STREAM_PORT}")
    return server

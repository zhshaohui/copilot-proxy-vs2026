import json
import re
import time
import os
from datetime import datetime
from typing import Any, Generator, Iterator

import requests
from mitmproxy import ctx, http

from copilot_proxy.config import (MODEL_API_KEY, MODEL_NAME, MODEL_URL,
                                  URLS_OF_INTEREST)
from copilot_proxy.inject_responses import MODELS_TO_INJECT, TOKEN_TO_INJECT
from copilot_proxy.utils import (generate_random_string, parse_sse_stream)

INTERCEPTED_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "intercepted_requests.log")

def log_intercepted(path, reason=""):
    """Log intercepted requests to a separate file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] INTERCEPTED: {path}"
    if reason:
        log_msg += f" (Reason: {reason})"
    try:
        with open(INTERCEPTED_LOG, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")
    except Exception as e:
        ctx.log.error(f"Failed to write to intercepted log: {e}")


# GH Copilot still uses the completion API, which is deprecated. See below
# https://platform.openai.com/docs/api-reference/completions
# And, Ollama and OpenRouter don't support the completions endpoint well.
# Therefore, we do conversions and use the chat completion API instead.
def code_completion(completion_input: dict) -> Generator[bytes, Any, None]:
    if not MODEL_URL:
        error_msg = "MODEL_URL environment variable is not set"
        yield f"data: {json.dumps({'error': {'message': error_msg, 'type': 'config_error'}})}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
        return
    if not MODEL_API_KEY or not MODEL_NAME:
        raise ValueError(
            "You must specify env vars `MODEL_URL`, `MODEL_API_KEY` and `MODEL_NAME`"
        )

    # Extracting necessary parts from the completion input
    prompt = completion_input.get("prompt", "")
    suffix = completion_input.get("suffix", "")
    max_tokens = completion_input.get("max_tokens", 500)
    temperature = completion_input.get("temperature", 0.2)
    top_p = completion_input.get("top_p", 1)
    n = completion_input.get("n", 3)
    stop = completion_input.get("stop", [])
    stream = completion_input.get("stream", True)
    extra = completion_input.get("extra", {})

    # I haven't found any good models for code completion tasks without fine tuning
    # These prompts definitely need more work
    user_prompt = (
        f"{prompt}<insert_your_completion_here>{suffix}\n\n"
        f"Extra Context:\n{json.dumps(extra)}\n\n"
        f"Now insert your completion at the place marked by `<insert_your_completion_here>`"
    )

    system_prompt = (
        "You are an expert programmer that completes code snippets in code editor."
        "The completion is additional code or comments that users might want to add. "
        "You MUST NOT use markdown, code blocks, or any formatting such as ```python; just print the code or comments directly. "
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    chat_completion_input = {
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "n": n,
        "stop": stop,
        "stream": stream,
    }

    # Making the API call
    url = MODEL_URL.rstrip('/') + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MODEL_API_KEY}",
    }

    try:
        response = requests.post(
            url, headers=headers, data=json.dumps(chat_completion_input),
            stream=stream, timeout=60
        )
        response.raise_for_status()

        for data in parse_sse_stream(response=response):
            decoded_line = data.strip()
            if not decoded_line:
                continue
            if decoded_line == "[DONE]":
                break

            try:
                data_dict = json.loads(decoded_line)
            except json.JSONDecodeError:
                continue

            choices = data_dict.get("choices", [])

            for choice in choices:
                content = choice.get("delta", {}).get("content", "")
                if content:
                    result = {
                        "id": data_dict.get("id") or f"copilot-cc-{generate_random_string(12)}",
                        "object": "text_completion",
                        "created": data_dict.get("created") or int(time.time()),
                        "model": MODEL_NAME,
                        "choices": [
                            {
                                "text": content,
                                "index": choice.get("index") if choice.get("index") is not None else 0,
                                "finish_reason": choice.get("finish_reason"),  # Always present (may be null)
                                "logprobs": choice.get("logprobs"),
                                "p": "aaaa",
                            }
                        ],
                    }
                    yield f"data: {json.dumps(result)}\n\n".encode("utf-8")
        yield "data: [DONE]\n\n".encode("utf-8")

    except requests.exceptions.RequestException as e:
        ctx.log.error(f"Completion request failed: {e}")
        yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'request_error'}})}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"


def sanitize_chunk(chunk: dict) -> dict:
    """Remove null fields and fix types that VS2026 Copilot doesn't handle.
    Also ensures tool_calls have valid non-null IDs."""
    # Remove top-level null fields
    for key in ("usage", "system_fingerprint"):
        if chunk.get(key) is None:
            del chunk[key]
    
    if "choices" in chunk:
        for choice in chunk["choices"]:
            # CRITICAL: VS Copilot requires finish_reason on EVERY chunk.
            # Ensure finish_reason always exists (null for intermediate, "stop" for final).
            if "finish_reason" not in choice:
                choice["finish_reason"] = None
            # Remove null choice-level fields EXCEPT finish_reason
            for key in ("logprobs", "index"):
                if choice.get(key) is None:
                    choice.pop(key, None)
            
            if "delta" in choice:
                delta = choice["delta"]
                # Map reasoning_content to content so VS displays thinking progress
                if delta.get("reasoning_content"):
                    if delta.get("content") is None:
                        delta["content"] = delta["reasoning_content"]
                    del delta["reasoning_content"]
                elif "reasoning_content" in delta and delta["reasoning_content"] is None:
                    del delta["reasoning_content"]
                
                # Fix content: never null
                if delta.get("content") is None and "tool_calls" not in delta:
                    delta["content"] = ""
                elif delta.get("content") is None:
                    del delta["content"]
                
                # Remove null role
                if delta.get("role") is None:
                    del delta["role"]
                
                # Fix tool_calls IDs
                if "tool_calls" in delta and delta["tool_calls"]:
                    for tc in delta["tool_calls"]:
                        if not isinstance(tc, dict):
                            continue
                        # Ensure tool call has a valid non-null ID
                        if not tc.get("id") or not str(tc.get("id")).strip():
                            tc["id"] = f"call_{generate_random_string(12)}"
                        # Ensure function block is valid
                        func = tc.get("function")
                        if isinstance(func, dict):
                            if func.get("arguments") is None:
                                func["arguments"] = ""
                            if func.get("name") is None:
                                func["name"] = ""
    
    return chunk


def code_gen(messages: list, tools: list = None, tool_choice: str = None) -> Generator[bytes, None, None]:
    """Generate code/chat response using the specified model."""
    if not MODEL_URL:
        error_msg = "MODEL_URL environment variable is not set"
        yield f"data: {json.dumps({'error': {'message': error_msg, 'type': 'config_error'}})}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
        return
    if not MODEL_API_KEY or not MODEL_NAME:
        raise ValueError("Missing env vars: MODEL_API_KEY or MODEL_NAME")

    headers = {
        "Authorization": f"Bearer {MODEL_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 4096,
        "stream": True,
        "n": 1,
    }
    # CRITICAL: Don't pass tools/tool_choice to avoid VS2026 "Sequence contains more than one element" crash
    # Agent mode will work as plain chat - model can still reason without explicit tools

    try:
        with requests.post(MODEL_URL, headers=headers, json=data, stream=True, timeout=120) as response:
            if response.status_code != 200:
                error_msg = f"API error {response.status_code}: {response.text[:200]}"
                ctx.log.error(error_msg)
                yield f"data: {json.dumps({'error': {'message': error_msg, 'type': 'api_error'}})}\n\n".encode("utf-8")
                yield b"data: [DONE]\n\n"
                return

            stream_id = None
            
            for line in response.iter_lines():
                if not line:
                    continue
                line_str = line.decode('utf-8')
                
                if not line_str.startswith("data: "):
                    ctx.log.error(f"Unexpected non-SSE line: {line_str[:100]}")
                    continue
                
                data_part = line_str[6:]
                if data_part.strip() == "[DONE]":
                    yield b"data: [DONE]\n\n"
                    continue
                
                try:
                    chunk = json.loads(data_part)
                    chunk = sanitize_chunk(chunk)
                    
                    # Ensure top-level id is always present
                    current_id = chunk.get("id")
                    if not current_id or not str(current_id).strip():
                        if stream_id:
                            chunk["id"] = stream_id
                        else:
                            stream_id = f"chatcmpl-{generate_random_string(12)}"
                            chunk["id"] = stream_id
                    else:
                        if not stream_id:
                            stream_id = current_id
                    
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
                except json.JSONDecodeError:
                    yield f"data: {data_part}\n\n".encode("utf-8")
            
            # Ensure [DONE] is always sent
            yield b"data: [DONE]\n\n"
            
    except requests.exceptions.RequestException as e:
        error_msg = f"Request failed: {str(e)}"
        ctx.log.error(error_msg)
        yield f"data: {json.dumps({'error': {'message': error_msg, 'type': 'request_error'}})}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"


def request(flow: http.HTTPFlow) -> None:
    """
    Log details of the incoming HTTP request.
    """
    # Guard: skip requests with empty/broken URLs (e.g., CONNECT probes)
    if not flow.request.pretty_url or not flow.request.pretty_url.strip():
        return

    # 1. GLOBAL LOGGING: Log ALL requests to diagnose 404s
    ctx.log.info(f"[REQ] {flow.request.method} {flow.request.path}")

    # Intercept token request early to avoid 401 completely
    req_path = flow.request.path
    
    if "copilot_internal/v2/token" in req_path:
        ctx.log.info("Intercepted token request early")
        log_intercepted(req_path, "token")
        flow.response = http.Response.make(
            200,
            json.dumps(TOKEN_TO_INJECT).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        return

    # Catch GitHub API root health-check and user-info probes that VS sends
    # Return plausible responses to prevent VS client-side errors
    if req_path in ("/", "/user", "/rate_limit", "/copilot_internal/user") or req_path.startswith("/user/"):
        ctx.log.info(f"Blocked GitHub API probe: {flow.request.pretty_url}")
        log_intercepted(req_path, "github_probe")
        if req_path == "/user" or req_path == "/copilot_internal/user":
            resp = {
                "login": "copilot-user",
                "id": 12345678,
                "node_id": "U_kgDOCopilot",
                "name": "Copilot User",
                "email": "copilot@example.com",
                "plan": {"name": "pro", "space": 999999, "collaborators": 0, "private_repos": 9999},
            }
        elif req_path == "/rate_limit":
            resp = {
                "resources": {
                    "core": {"limit": 5000, "remaining": 4999, "reset": 9999999999},
                    "search": {"limit": 30, "remaining": 30, "reset": 9999999999},
                }
            }
        else:
            resp = {}
        flow.response = http.Response.make(
            200,
            json.dumps(resp).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        return

    # Handle chat completions: redirect to local streaming server
    # Match /chat/completions, /v1/chat/completions, /api/v1/chat/completions, etc.
    if "/chat/completions" in req_path:
        log_intercepted(req_path, "chat_completion")
        try:
            ctx.log.info(f"Redirecting chat to stream server: {flow.request.pretty_url}")
            body = json.loads(flow.request.content.decode("utf-8"))
            
            # TEST: if model is "test-iter", respond inline
            if body.get("model") == "test-iter":
                test_data = b"data: chunk1\n\ndata: chunk2\n\ndata: [DONE]\n\n"
                flow.response = http.Response.make(
                    200,
                    test_data,
                    {"Content-Type": "text/event-stream"},
                )
                return
            
            # Redirect to local streaming server
            flow.request.host = "127.0.0.1"
            flow.request.port = 15433
            flow.request.scheme = "http"
            flow.request.authority = b"127.0.0.1:15433"
            ctx.log.info("Redirected chat to http://127.0.0.1:15433")
        except Exception as e:
            ctx.log.error(f"Error redirecting chat: {e}")
            flow.response = http.Response.make(
                500,
                json.dumps({"error": {"message": str(e), "type": "proxy_error"}}).encode("utf-8"),
                {"Content-Type": "application/json"},
            )
        return

    # Handle code completions in request phase
    if "/engines/copilot-codex/completions" in req_path:
        log_intercepted(req_path, "code_completion")
        try:
            ctx.log.info(f"Intercepted completion: {flow.request.pretty_url}")
            body = json.loads(flow.request.content.decode("utf-8"))
            
            flow.response = http.Response.make(
                200,
                b"",
                {"Content-Type": "text/event-stream"},
            )
            object.__setattr__(flow.response, "_content", code_completion(body))
        except Exception as e:
            ctx.log.error(f"Error intercepting completion: {e}")
            flow.response = http.Response.make(
                500,
                json.dumps({"error": {"message": str(e), "type": "proxy_error"}}).encode("utf-8"),
                {"Content-Type": "application/json"},
            )
        return

    # Intercept models requests immediately
    # VS2026 expects a list structure with a "data" field
    if req_path == "/models" or req_path == "/v1/models" or req_path.startswith("/models?") or req_path.startswith("/v1/models?"):
        log_intercepted(req_path, "models_list")
        ctx.log.info("Intercepted models list request - returning model list")
        # Return the full MODELS_TO_INJECT structure which has {"data": [...], "object": "list"}
        flow.response = http.Response.make(
            200,
            json.dumps(MODELS_TO_INJECT).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        return
    
    # /models/{id} → return single model
    if req_path.startswith("/models/"):
        log_intercepted(req_path, "single_model")
        ctx.log.info(f"Intercepted single model request: {flow.request.pretty_url}")
        model_id = req_path.split("/")[-1]
        model_data = None
        for m in MODELS_TO_INJECT.get("data", []):
            if m.get("id") == model_id:
                model_data = m
                break
        if model_data:
            flow.response = http.Response.make(
                200,
                json.dumps({"data": model_data}).encode("utf-8"),
                {"Content-Type": "application/json"},
            )
        else:
            flow.response = http.Response.make(
                404,
                json.dumps({"error": "Model not found"}).encode("utf-8"),
                {"Content-Type": "application/json"},
            )
        return

    # 2. CATCH-ALL: VS2026 probes many endpoints (threads, assistants, etc.).
    # If we don't handle them, they hit upstream and fail (404/401).
    # Instead, return 200 OK with empty data to keep VS happy.
    log_intercepted(req_path, "catch_all")
    ctx.log.info(f"[CATCH-ALL] Intercepting unknown request: {flow.request.method} {req_path}")
    flow.response = http.Response.make(
        200,
        json.dumps({}).encode("utf-8"),
        {"Content-Type": "application/json"},
    )
    return


def responseheaders(flow: http.HTTPFlow) -> None:
    """Enable streaming for upstream SSE responses (from our local stream server)."""
    if flow.response is None:
        return
    ct = flow.response.headers.get("Content-Type", "")
    if "text/event-stream" in ct:
        flow.response.stream = True  # Forward chunks as they arrive, don't buffer
        if "content-length" in flow.response.headers:
            del flow.response.headers["content-length"]


def response(flow: http.HTTPFlow) -> None:
    """
    Log details of the outgoing HTTP response and modify specific responses.
    """
    assert flow.response
    ctx.log.info(
        f"Response from {flow.request.pretty_url}: {flow.response.status_code}"
    )
    ctx.log.info(f"Response headers: {dict(flow.response.headers)}")
    try:
        if flow.response.content and re.search(URLS_OF_INTEREST, flow.request.pretty_url):
            ctx.log.info(
                f"Response body for {flow.request.pretty_url}: {flow.response.get_text()}"
            )
    except KeyError:
        pass  # streamed response, no content buffered

    if "copilot_internal/v2/token" in flow.request.pretty_url:
        flow.response = http.Response.make(
            200,
            json.dumps(TOKEN_TO_INJECT).encode("utf-8"),
            {"Content-Type": "application/json"},
        )


addons = [
    request,
    responseheaders,
    response,
]


def run(port: int) -> None:
    from mitmproxy.tools.main import mitmdump
    
    # Start local streaming server for true SSE streaming
    from copilot_proxy.stream_server import start_stream_server
    start_stream_server()
    
    mitmdump(["-p", str(port), "-s", __file__])

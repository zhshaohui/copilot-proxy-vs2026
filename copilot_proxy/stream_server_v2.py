"""
Enhanced stream server for VS2026 GitHub Copilot tool calling support.
Improves XML parsing, tool_call ID generation, and streaming buffer handling.
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
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from copilot_proxy.config import MODEL_URL, MODEL_API_KEY, MODEL_NAME

DASHSCOPE_URL = MODEL_URL
DASHSCOPE_KEY = MODEL_API_KEY
STREAM_PORT = 15433

# VS2026 Copilot 兼容的工具白名单
READ_ONLY_TOOLS = {
    "get_files_in_project", "get_file", "file_search", "code_search",
    "get_errors", "get_projects_in_solution", "get_symbols_by_name",
    "find_symbol", "get_web_pages", "nuget_get-package-readme"
}

def generate_tool_call_id():
    """生成符合 OpenAI 标准的 tool_call ID (call_ + 12位随机字符)"""
    chars = string.ascii_letters + string.digits
    random_part = ''.join(random.choices(chars, k=12))
    return f"call_{random_part}"


def parse_qwen_tool_calls_robust(content: str, tools: list = None) -> list:
    """
    更健壮的 Qwen XML 格式解析器
    
    支持的格式:
    - 标准: {"name": "tool_name", "arguments": {...}}
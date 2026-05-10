# 🚀 VS2026 Copilot Proxy

A custom `mitmproxy` based middleware that enables **GitHub Copilot** in **Visual Studio 2026** to connect to **local/custom LLMs** (such as **Qwen 3.6 Plus** via DashScope).

This project bridges the gap between VS2026's strict Copilot API requirements and custom model providers, enabling features like **Agent Mode (Tool Calls)**, **Deep Thinking**, and fast response times.

---

## ✨ Features

*   **️ VS2026 Compatible**: Specifically engineered to handle VS2026's unique API probes (including a robust "Catch-All" mechanism to prevent `404 Not Found` errors).
*   **🧠 Deep Thinking**: Supports `enable_thinking: True` for complex reasoning capabilities.
*   **🤖 Agent Mode / Tool Calls**: Fully supports VS Copilot's tool usage (e.g., file reading, command execution) by translating Qwen's native XML tool format to OpenAI standard format.
*   **⚡ Non-Streaming Mode**: Optimized for speed by waiting for the complete response before sending, reducing latency jitter.
*   **🔒 Secure Configuration**: API Keys are managed via System Environment Variables; no sensitive data is hardcoded in the source.

---

##  Prerequisites

*   **Python 3.8+**
*   **mitmproxy 12.2+** (Required for the proxy core)

## ️ Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/your-username/copilot-proxy-vs2026.git
    cd copilot-proxy-vs2026
    ```

2.  **Install Dependencies**:
    ```bash
    pip install -e .
    ```
    *(Or use Poetry if you prefer: `poetry install`)*

##  Configuration

### 1. Environment Variables
Set the following variables in your **Windows System Environment Variables** (or user environment):

| Variable | Description | Example |
| :--- | :--- | :--- |
| `MODEL_API_KEY` | **(Required)** Your API Key | `sk-sp-...` |
| `MODEL_URL` | *(Optional)* Base URL | `https://coding.dashscope.aliyuncs.com/v1` |
| `MODEL_NAME` | *(Optional)* Model ID | `qwen3.6-plus` |

### 2. Visual Studio 2026 Settings
Configure VS2026 to route Copilot traffic through the proxy:

1.  Open **Tools > Options**.
2.  Navigate to **Environment > Proxy**.
3.  Set **Override system proxy** and enter: `http://127.0.0.1:15432`
4.  In **Environment > Web Proxy**, ensure **Bypass proxy for local addresses** is **unchecked**.

## 🚀 Usage

### Quick Start
Double-click the batch file to start the proxy in the background:
*   **Start**: Double-click `start_copilot.bat`
*   **Stop**: Double-click `stop_copilot.bat`

### PowerShell
```powershell
# Start
.\start_proxy.ps1

# Stop (Manual)
Get-Process python | Where-Object { $_.CommandLine -like "*copilot_proxy*" } | Stop-Process
```

---

## ️ Architecture

*   **Port 15432**: `mitmproxy` instance that intercepts traffic, handles authentication tokens, and routes requests.
*   **Port 15433**: Local stream server that communicates with the LLM API (DashScope), handles JSON conversion, and manages SSE streaming/non-streaming responses.

**Data Flow**:
`VS2026` ↔ `15432 (mitmproxy)` ↔ `15433 (Stream Server)` ↔ `LLM API`

---

## 🐛 Troubleshooting

*   **Port Already in Use**: Run `stop_copilot.bat` to clear existing processes on port 15432/15433.
*   **Logs**:
    *   `intercepted_requests.log`: Records all requests intercepted by the proxy (useful for debugging 404s).
    *   `stream_debug.log`: detailed request/response logs from the stream server.

---

## 📄 License

MIT License

---

> **Disclaimer**: This tool is for educational and personal use only. Ensure compliance with the terms of service of your chosen LLM provider.

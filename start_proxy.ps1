# CoPaw Copilot Proxy Launcher
# Start the mitmproxy-based DashScope proxy for VS2026
param(
    [int]$Port = 15432
)

$ErrorActionPreference = "Stop"

# Kill any existing proxy on the port
$existing = netstat -ano | Select-String "LISTENING" | Select-String ":$Port "
if ($existing) {
    $oldPid = ($existing -split '\s+')[-1]
    taskkill /PID $oldPid /F 2>$null
    Start-Sleep -Seconds 1
    Write-Host "Killed old proxy (PID $oldPid)"
}

# Environment Configuration
# These values will be read from your System Environment Variables.
# The script checks for required keys before starting.

# 1. API Key (Required)
if (-not $env:MODEL_API_KEY) {
    Write-Error "ERROR: MODEL_API_KEY is not set in your system environment variables!"
    exit
}

# 2. Model URL (Optional - defaults to DashScope)
if (-not $env:MODEL_URL) {
    $env:MODEL_URL = "https://coding.dashscope.aliyuncs.com/v1"
    Write-Host "Using default MODEL_URL."
}

# 3. Model Name (Optional - defaults to qwen3.6-plus)
if (-not $env:MODEL_NAME) {
    $env:MODEL_NAME = "qwen3.6-plus"
    Write-Host "Using default MODEL_NAME."
}

# Configuration
# Update these paths to match your local environment
$pythonExe = "python"  # Assumes your venv is activated or python is in PATH
$srcDir = $PSScriptRoot # Automatically sets to the directory where this script is located

Set-Location $srcDir

Write-Host "Starting copilot-proxy on port $Port ..."
Start-Process -FilePath $pythonExe -ArgumentList "-m", "copilot_proxy", "start", "--port", $Port -NoNewWindow

Start-Sleep -Seconds 2

# Verify
$check = netstat -ano | Select-String "LISTENING" | Select-String ":$Port "
if ($check) {
    Write-Host "Proxy running on port $Port"
    Write-Host "Stream server on port 15433"
} else {
    Write-Host "ERROR: Proxy failed to start"
}

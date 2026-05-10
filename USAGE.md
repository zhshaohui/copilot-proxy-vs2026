# Copilot Proxy 使用指南

## 快速启动

### 方式一：PowerShell脚本（推荐）
```powershell
cd C:\Users\zhsha\.copaw\workspaces\ymw7EE\copilot-proxy-src
.\start_proxy.ps1
```

### 方式二：命令行
```powershell
$env:MODEL_URL = "https://coding.dashscope.aliyuncs.com/v1/chat/completions"
$env:MODEL_NAME = "qwen3.6-plus"
$env:MODEL_API_KEY = "sk-sp-5999a6310389432e81924e296043a894"
cd C:\Users\zhsha\.copaw\workspaces\ymw7EE\copilot-proxy-src
& "C:\Users\zhsha\.qwenpaw\venv\Scripts\python.exe" -m copilot_proxy start --port 15432
```

## VS Code 配置

1. 打开 VS Code 设置（Ctrl+,）
2. 搜索 `proxy`
3. 找到 **Http: Proxy** 设置，填入：`http://127.0.0.1:15432`

或者在 `settings.json` 中添加：
```json
{
    "http.proxy": "http://127.0.0.1:15432",
    "http.proxyStrictSSL": false
}
```

## SSL 证书安装（重要）

如果 Copilot 出现 SSL 错误，需要安装 mitmproxy 的 CA 证书：

**方法一：命令行安装（管理员权限）**
```powershell
certutil -addstore -f "ROOT" "$env:USERPROFILE\.mitmproxy\mitmproxy-ca-cert.pem"
```

**方法二：手动安装**
1. 按 Win+R 输入 `mmc` 打开 Microsoft Management Console
2. 文件 → 添加/删除管理单元 → 证书 → 添加 → 计算机账户 → 本地计算机
3. 展开 证书(本地计算机) → 受信任的根证书颁发机构 → 证书
4. 右键 → 所有任务 → 导入 → 选择 `C:\Users\zhsha\.mitmproxy\mitmproxy-ca-cert.pem`

## 停止代理

```powershell
# 查找进程
Get-NetTCPConnection -LocalPort 15432 | Select-Object OwningProcess

# 停止进程 (替换 PID)
Stop-Process -Id <PID> -Force
```

## 当前配置

| 项目 | 值 |
|------|-----|
| 模型 URL | https://coding.dashscope.aliyuncs.com/v1/chat/completions |
| 模型名称 | qwen3.6-plus |
| 代理端口 | 15432 |
| Python路径 | C:\Users\zhsha\.qwenpaw\venv\Scripts\python.exe |

## 故障排查

**端口被占用：**
```powershell
# 释放端口
Get-NetTCPConnection -LocalPort 15432 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

**证书问题：**
检查证书是否存在：`dir $env:USERPROFILE\.mitmproxy`

**模型API错误：**
确认 MODEL_API_KEY 有效，测试直连：
```powershell
curl -H "Authorization: Bearer $env:MODEL_API_KEY" -H "Content-Type: application/json" -d '{"model":"qwen3.6-plus","messages":[{"role":"user","content":"hi"}]}' $env:MODEL_URL
```

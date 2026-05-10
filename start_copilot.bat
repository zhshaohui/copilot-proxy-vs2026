@echo off
chcp 65001 >nul
echo.
echo ========================================
echo    Starting CoPaw Copilot Proxy
echo ========================================
echo.

:: Run the PowerShell script
powershell -ExecutionPolicy Bypass -File "%~dp0start_proxy.ps1"

echo.
echo ========================================
echo    Done! Check logs if needed.
echo ========================================
timeout /t 3 >nul

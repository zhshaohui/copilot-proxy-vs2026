@echo off
chcp 65001 >nul
echo.
echo ========================================
echo    Stopping CoPaw Copilot Proxy
echo ========================================
echo.

:: Find and kill process on port 15432
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":15432 "') do (
    echo Killing PID %%a
    taskkill /PID %%a /F >nul 2>&1
)

echo.
echo ========================================
echo    Proxy Stopped.
echo ========================================
timeout /t 3 >nul

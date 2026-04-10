@echo off
title Weighbridge Recovery Dashboard
echo.
echo  =========================================
echo   Weighbridge System Recovery Dashboard
echo  =========================================
echo.

REM ── Find Python venv ──────────────────────────────────────────────────────────
set "WORKSPACE=%~dp0"
set "PYTHON=%WORKSPACE%backend\venv\Scripts\python.exe"
set "WATCHDOG=%WORKSPACE%backend\watchdog_server.py"

if not exist "%PYTHON%" (
    echo  ERROR: Python venv not found at:
    echo  %PYTHON%
    echo.
    echo  Please run the installer first.
    pause
    exit /b 1
)

REM ── Check if watchdog is already running ──────────────────────────────────────
netstat -ano | find ":9002" | find "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo  Watchdog already running on port 9002.
) else (
    echo  Starting Recovery Watchdog...
    start "" /B "%PYTHON%" "%WATCHDOG%"
    timeout /t 3 /nobreak >nul
    echo  Watchdog started.
)

REM ── Open in browser ───────────────────────────────────────────────────────────
echo.
echo  Opening dashboard in browser...
echo  URL: http://localhost:9002
echo.
start "" "http://localhost:9002"

echo  Dashboard is open in your browser.
echo  You can close this window.
echo.
timeout /t 5 /nobreak >nul

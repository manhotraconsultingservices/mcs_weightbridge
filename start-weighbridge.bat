@echo off
:: Weighbridge Manual Start — double-click if app is not responding
:: Place a shortcut to this file on the Desktop

echo.
echo Starting Weighbridge services...
echo.

net start WeighbridgeBackend  2>nul
if %errorlevel% == 2 (
    echo   Weighbridge : Already running
) else (
    echo   Weighbridge : Started
)

echo.
echo Done. Open your browser and go to:
echo.
echo     http://localhost:9001
echo.
echo Press any key to close this window...
pause >nul

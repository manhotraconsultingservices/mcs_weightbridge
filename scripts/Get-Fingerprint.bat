@echo off
title Weighbridge ERP - Hardware Fingerprint Capture
color 0B

echo.
echo  +----------------------------------------------------------+
echo  ^|      Weighbridge ERP - Hardware Fingerprint Capture      ^|
echo  +----------------------------------------------------------+
echo.
echo  This will collect hardware information from this computer
echo  and save a fingerprint.json file to your Desktop.
echo.
echo  Please wait...
echo.

:: Run the PowerShell version (no Python needed)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Get-Fingerprint.ps1"

:: If PowerShell failed for some reason, try Python fallback
if errorlevel 1 (
    echo.
    echo  PowerShell script failed. Trying Python...
    echo.
    cd /d "%~dp0.."
    python show_fingerprint.py
    if errorlevel 1 (
        echo.
        echo  ERROR: Could not capture fingerprint.
        echo  Please contact your vendor for assistance.
        echo.
        pause
    )
)

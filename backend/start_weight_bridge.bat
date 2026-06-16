@echo off
REM Weight Bridge — Auto-detecting serial reader
REM Config: weight_bridge.json (auto-created on first detection)
REM
REM Usage:
REM   start_weight_bridge.bat              Auto-detect mode
REM   start_weight_bridge.bat --scan       Force rescan
REM   start_weight_bridge.bat COM4 1200    Manual override

cd /d "%~dp0"
python weight_bridge.py %*
pause

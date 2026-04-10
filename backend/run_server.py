"""
Production entry point for Weighbridge backend.

Used as the PyInstaller compilation target. When compiled to .exe, this
replaces the `python -m uvicorn` command and serves both the API (port 9001)
and the built React frontend as static files.

Usage (source):
    python run_server.py

Usage (compiled):
    weighbridge.exe
"""

import multiprocessing
import os
import sys

# ── Frozen-exe bootstrapping ─────────────────────────────────────────────────
# PyInstaller --onefile spawns worker processes; freeze_support() is required
# on Windows so child processes don't re-execute the startup block.
if getattr(sys, "frozen", False):
    multiprocessing.freeze_support()
    # Change CWD to the folder containing the .exe so that .env and
    # license.key are discovered relative to the executable, not the
    # process's launch directory (which varies when run as a service).
    os.chdir(os.path.dirname(sys.executable))

import uvicorn
from app.main import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=9001,
        workers=1,          # Single worker — required for PyInstaller on Windows
        log_level="info",
    )

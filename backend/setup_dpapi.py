#!/usr/bin/env python3
"""
One-time DPAPI secrets setup script.

Run this ONCE on the deployment machine (as the service account user or SYSTEM)
immediately after installing the software:

    python setup_dpapi.py

    # Non-interactive (used by Install-Client.ps1 automated installer):
    python setup_dpapi.py --no-prompt

What it does:
  1. Reads current secrets from .env
  2. Encrypts them using Windows DPAPI (machine + user account bound)
  3. Writes secrets.dpapi alongside the backend
  4. Renames .env to .env.bak (keeping a backup in case of recovery need)

After this, the application reads from secrets.dpapi. The .env.bak file
should be stored OFFLINE (not on this machine) as a disaster recovery backup,
then deleted from the deployment directory.
"""

import argparse
import os
import sys
import shutil
from pathlib import Path

# Parse arguments first (before any output)
parser = argparse.ArgumentParser(description="Weighbridge DPAPI secrets setup")
parser.add_argument(
    "--no-prompt",
    action="store_true",
    help="Run non-interactively (skip confirmation prompt). Used by automated installers.",
)
args = parser.parse_args()

sys.path.insert(0, str(Path(__file__).parent))

if sys.platform != "win32":
    print("ERROR: DPAPI is only available on Windows.")
    print("       On Linux/Mac deployments, use environment variables + OS secret store.")
    sys.exit(1)

try:
    from app.utils.secrets_manager import encrypt_secrets, SECRETS_FILE
except ImportError as e:
    print(f"ERROR: Import failed: {e}")
    print("Run this from the backend/ directory with the venv activated.")
    sys.exit(1)

from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).parent
ENV_FILE    = BACKEND_DIR / ".env"
ENV_BAK     = BACKEND_DIR / ".env.bak"

print("=" * 60)
print("  Weighbridge ERP — DPAPI Secrets Setup")
print("=" * 60)
print()

if not ENV_FILE.exists():
    print(f"ERROR: {ENV_FILE} not found. Cannot encrypt secrets.")
    sys.exit(1)

# Read all values from .env
secrets = dict(dotenv_values(ENV_FILE))
print(f"Found {len(secrets)} secrets in .env:")
for k in secrets:
    v = secrets[k]
    masked = v[:4] + "****" + v[-4:] if len(v) > 8 else "****"
    print(f"  {k} = {masked}")

print()
if args.no_prompt:
    print("Running non-interactively (--no-prompt). Encrypting now...")
else:
    input("Press ENTER to encrypt these secrets with DPAPI (Ctrl+C to abort)...")
print()

try:
    encrypt_secrets(secrets)
    print(f"Encrypted secrets written to: {SECRETS_FILE}")
except Exception as e:
    print(f"Encryption failed: {e}")
    sys.exit(1)

# Rename .env to .env.bak
shutil.move(str(ENV_FILE), str(ENV_BAK))
print(f"Original .env renamed to: {ENV_BAK}")
print()
print("IMPORTANT:")
print("  1. Copy .env.bak to a SECURE OFFLINE location (encrypted USB, etc.)")
print("  2. Then DELETE .env.bak from this machine")
print("  3. The application now reads secrets exclusively from secrets.dpapi")
print("  4. secrets.dpapi is machine-locked — it cannot be decrypted elsewhere")
print()
print("Setup complete. Restart the Weighbridge service.")

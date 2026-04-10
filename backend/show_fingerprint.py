#!/usr/bin/env python3
"""
Vendor utility: run this on the CLIENT machine to obtain the hardware fingerprint
needed when generating a new hardware-locked license.

Usage:
    python show_fingerprint.py

Output: fingerprint + individual factor hashes to paste into generate_license.py
"""
import sys
import os

# Ensure app package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app.utils.hardware_fingerprint import get_factors, compute_fingerprint, compute_factor_hashes
except ImportError:
    print("ERROR: Could not import hardware_fingerprint module.")
    print("Run this script from the backend/ directory with the venv active.")
    sys.exit(1)

import socket
import json

print("=" * 60)
print("  Weighbridge ERP — Hardware Fingerprint Utility")
print("=" * 60)
print()

print(f"Hostname        : {socket.gethostname()}")
print()

factors = get_factors()
if not any(factors.values()):
    print("WARNING: No hardware factors collected (non-Windows or virtualised).")
    print("         Consider using hostname-only licensing for this machine.")
else:
    print("Hardware Factors (RAW):")
    for k, v in factors.items():
        display = v if v else "(empty)"
        print(f"  {k:10s}: {display}")

print()
fp = compute_fingerprint(factors)
fh = compute_factor_hashes(factors)

print(f"Full Fingerprint (SHA-256):")
print(f"  {fp}")
print()
print("Factor Hashes (for 2-of-4 tolerance):")
for k, h in fh.items():
    print(f"  {k:10s}: {h}")

print()
print("─" * 60)

payload_fragment = {
    "hostname": socket.gethostname().upper(),
    "hardware_fingerprint": fp,
    "factor_hashes": fh,
}

# Save to file for easy transfer to vendor
output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fingerprint.json")
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(payload_fragment, f, indent=4)

print(f"Fingerprint saved to: {output_file}")
print()
print("NEXT STEP:")
print(f"  Send the file '{output_file}' to the vendor (via WhatsApp/email).")
print("  The vendor will use it to generate your license key.")
print()
print("JSON content:")
print(json.dumps(payload_fragment, indent=4))
print("─" * 60)

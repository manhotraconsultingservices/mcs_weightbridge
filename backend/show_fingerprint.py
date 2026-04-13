#!/usr/bin/env python3
"""
Vendor utility: run this on the CLIENT machine to obtain the hardware fingerprint
needed when generating a new hardware-locked license.

STANDALONE — no app dependencies required. Works with any Python 3.6+ on Windows.

Usage:
    python show_fingerprint.py

Output: fingerprint + individual factor hashes saved to fingerprint.json
"""
import hashlib
import json
import os
import socket
import subprocess
import sys

_WMIC_TIMEOUT = 8  # seconds per wmic call


# ── Hardware factor collection (embedded from app/utils/hardware_fingerprint.py) ──

def _wmic(query: str) -> str:
    """Run a wmic command and return clean value string, or empty string on failure."""
    try:
        out = subprocess.check_output(
            f"wmic {query} /value",
            shell=True,
            timeout=_WMIC_TIMEOUT,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="ignore")
        values = [
            line.split("=", 1)[1].strip()
            for line in out.splitlines()
            if "=" in line and line.split("=", 1)[1].strip()
        ]
        return values[0] if values else ""
    except Exception:
        return ""


def _registry_product_id() -> str:
    """Read Windows ProductId from registry (unique per Windows installation)."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        )
        value, _ = winreg.QueryValueEx(key, "ProductId")
        winreg.CloseKey(key)
        return str(value).strip()
    except Exception:
        return ""


def get_factors() -> dict:
    """Collect all 4 hardware factors."""
    if sys.platform != "win32":
        print("WARNING: Non-Windows platform. Hardware factors will be empty.")
        return {}
    return {
        "cpu":     _wmic("cpu get ProcessorId"),
        "mb":      _wmic("baseboard get SerialNumber"),
        "disk":    _wmic("diskdrive get SerialNumber"),
        "winprod": _registry_product_id(),
    }


def compute_fingerprint(factors: dict) -> str:
    """Compute full hardware fingerprint — 64-character SHA-256 hex string."""
    if not any(factors.values()):
        return "NO_HW_INFO"
    canonical = "|".join([
        f"CPU:{factors.get('cpu', '')}",
        f"MB:{factors.get('mb', '')}",
        f"DISK:{factors.get('disk', '')}",
        f"WIN:{factors.get('winprod', '')}",
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_factor_hashes(factors: dict) -> dict:
    """Compute individual SHA-256 hashes for each factor (for 2-of-4 tolerance)."""
    return {
        k: hashlib.sha256(v.encode("utf-8")).hexdigest() if v else ""
        for k, v in factors.items()
    }


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Weighbridge ERP — Hardware Fingerprint Utility")
    print("=" * 60)
    print()

    hostname = socket.gethostname()
    print(f"Hostname        : {hostname}")
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

    print("Full Fingerprint (SHA-256):")
    print(f"  {fp}")
    print()
    print("Factor Hashes (for 2-of-4 tolerance):")
    for k, h in fh.items():
        print(f"  {k:10s}: {h}")

    print()
    print("-" * 60)

    payload = {
        "hostname": hostname.upper(),
        "hardware_fingerprint": fp,
        "factor_hashes": fh,
    }

    output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fingerprint.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)

    print(f"Fingerprint saved to: {output_file}")
    print()
    print("NEXT STEP:")
    print(f"  Send '{output_file}' to the vendor (via WhatsApp/email).")
    print("  The vendor will use it to generate your license key.")
    print()
    print("JSON content:")
    print(json.dumps(payload, indent=4))
    print("-" * 60)

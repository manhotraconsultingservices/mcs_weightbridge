"""
Hardware fingerprinting for license binding.

Collects machine-specific identifiers that cannot be trivially spoofed:
  1. CPU ProcessorId  (unique per CPU chip)
  2. Motherboard SerialNumber
  3. Primary disk SerialNumber
  4. Windows ProductId (from registry)

Hashes them with SHA-256 to produce a 64-char fingerprint.
Vendor must run show_fingerprint.py on the client machine BEFORE issuing a license.

Tolerance: if ANY 2 of the 4 factors match the licensed fingerprint
(factor-level comparison), the license is accepted. This allows for
graceful handling of disk replacement without requiring license reissue.
"""

import hashlib
import logging
import subprocess
import sys
import winreg
from typing import Optional

logger = logging.getLogger(__name__)

_WMIC_TIMEOUT = 8  # seconds per wmic call


def _wmic(query: str) -> str:
    """Run a wmic command and return clean value string, or empty string on failure."""
    try:
        out = subprocess.check_output(
            f"wmic {query} /value",
            shell=True,
            timeout=_WMIC_TIMEOUT,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="ignore")
        # Extract value= lines, join non-empty ones
        values = [
            line.split("=", 1)[1].strip()
            for line in out.splitlines()
            if "=" in line and line.split("=", 1)[1].strip()
        ]
        return values[0] if values else ""
    except Exception as exc:
        logger.debug("wmic '%s' failed: %s", query, exc)
        return ""


def _registry_product_id() -> str:
    """Read Windows ProductId from registry (unique per Windows installation)."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        )
        value, _ = winreg.QueryValueEx(key, "ProductId")
        winreg.CloseKey(key)
        return str(value).strip()
    except Exception:
        return ""


def get_factors() -> dict[str, str]:
    """
    Collect all hardware factors. Returns a dict so callers can inspect
    individual factors for diagnostics.
    """
    if sys.platform != "win32":
        # Non-Windows: return empty factors (license will fall back to hostname check)
        return {}

    return {
        "cpu":      _wmic("cpu get ProcessorId"),
        "mb":       _wmic("baseboard get SerialNumber"),
        "disk":     _wmic("diskdrive get SerialNumber"),
        "winprod":  _registry_product_id(),
    }


def compute_fingerprint(factors: Optional[dict[str, str]] = None) -> str:
    """
    Compute the full hardware fingerprint.
    Returns a 64-character SHA-256 hex string.
    """
    if factors is None:
        factors = get_factors()

    if not any(factors.values()):
        # All factors empty — non-Windows or completely virtual machine.
        # Return a deterministic marker so the license system knows to skip HW check.
        return "NO_HW_INFO"

    canonical = "|".join([
        f"CPU:{factors.get('cpu', '')}",
        f"MB:{factors.get('mb', '')}",
        f"DISK:{factors.get('disk', '')}",
        f"WIN:{factors.get('winprod', '')}",
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_factor_hashes(factors: Optional[dict[str, str]] = None) -> dict[str, str]:
    """
    Compute individual SHA-256 hashes for each factor.
    Used for the 2-of-4 tolerance check in validate_license().
    """
    if factors is None:
        factors = get_factors()
    return {
        k: hashlib.sha256(v.encode("utf-8")).hexdigest() if v else ""
        for k, v in factors.items()
    }


def fingerprint_matches(licensed_fp: str, licensed_factor_hashes: Optional[dict] = None) -> bool:
    """
    Returns True if this machine matches the licensed fingerprint.

    Logic:
      1. Try exact full fingerprint match first (fastest).
      2. If licensed_factor_hashes provided, accept if >= 2 individual factors match
         (tolerates disk replacement or motherboard swap without license reissue).
    """
    actual_factors = get_factors()
    actual_fp = compute_fingerprint(actual_factors)

    # Exact match
    if actual_fp == licensed_fp:
        return True

    # NO_HW_INFO marker: non-Windows machine — skip HW check, fall through to hostname
    if actual_fp == "NO_HW_INFO" or licensed_fp == "NO_HW_INFO":
        return True

    # 2-of-4 tolerance check
    if licensed_factor_hashes:
        actual_hashes = compute_factor_hashes(actual_factors)
        matches = sum(
            1
            for k, h in licensed_factor_hashes.items()
            if h and actual_hashes.get(k) == h
        )
        if matches >= 2:
            logger.info("Hardware fingerprint: %d/4 factors matched (tolerance accepted)", matches)
            return True

    return False

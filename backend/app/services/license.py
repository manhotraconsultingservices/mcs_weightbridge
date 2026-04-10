"""
License validation service.

Verifies Ed25519-signed license files that bind the software to a specific
hostname with an expiry date. The vendor's public key is embedded here;
the private key never leaves the vendor's machine.

License file format:
    -----BEGIN WEIGHBRIDGE LICENSE-----
    <base64-encoded JSON payload>
    -----END WEIGHBRIDGE LICENSE-----
    -----BEGIN SIGNATURE-----
    <base64-encoded Ed25519 signature>
    -----END SIGNATURE-----
"""

import base64
import json
import logging
import os
import socket
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger(__name__)

# Hardware fingerprinting (imported lazily to avoid failure on non-Windows at import time)
def _get_hw_fingerprint_match(licensed_fp: str, licensed_factor_hashes=None) -> bool:
    try:
        from app.utils.hardware_fingerprint import fingerprint_matches
        return fingerprint_matches(licensed_fp, licensed_factor_hashes)
    except Exception as exc:
        logger.warning("Hardware fingerprint check error: %s — falling back to hostname", exc)
        return False

# ── Vendor public key (from generate_license.py --generate-keypair) ─────────
# This is the ONLY key embedded in the application. The private key stays
# with the vendor and is NEVER deployed to client machines.
VENDOR_PUBLIC_KEY_B64 = "Rr1ez74YY2P39a4VeU9+Nn5JQTL6Qsfase9c9t7o9Fk="

# License file location — next to the .exe (frozen) or project root (source)
if getattr(sys, "frozen", False):
    # PyInstaller: sys.executable is the path to weighbridge.exe
    _PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    # Running as Python source: go up from backend/app/services/ → project root
    _THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # backend/app/services/
    _BACKEND_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))  # backend/
    _PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)  # workspace_Weighbridge/
LICENSE_FILE = os.path.join(_PROJECT_ROOT, "license.key")


class LicenseError(Exception):
    """Raised when license validation fails."""
    pass


@dataclass
class LicenseInfo:
    """Parsed and validated license data."""
    customer: str
    hostname: str
    issued: str
    expires: str
    features: list[str]
    max_users: int
    serial: str
    days_remaining: int
    valid: bool = True
    error: str | None = None


def _load_public_key() -> Ed25519PublicKey:
    """Load the embedded vendor public key."""
    raw_bytes = base64.b64decode(VENDOR_PUBLIC_KEY_B64)
    return Ed25519PublicKey.from_public_bytes(raw_bytes)


def _parse_license_file(filepath: str) -> tuple[bytes, bytes]:
    """Parse the PEM-style license file into payload bytes and signature."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        raise LicenseError(
            f"License file not found: {filepath}. "
            "Contact your vendor to obtain a valid license key."
        )

    try:
        payload_b64 = (
            content.split("-----BEGIN WEIGHBRIDGE LICENSE-----")[1]
            .split("-----END WEIGHBRIDGE LICENSE-----")[0]
            .strip()
        )
        sig_b64 = (
            content.split("-----BEGIN SIGNATURE-----")[1]
            .split("-----END SIGNATURE-----")[0]
            .strip()
        )
    except (IndexError, ValueError):
        raise LicenseError("Invalid license file format. The file may be corrupted.")

    return base64.b64decode(payload_b64), base64.b64decode(sig_b64)


def validate_license(filepath: str | None = None) -> LicenseInfo:
    """
    Validate the license file. Checks:
    1. File exists and is parseable
    2. Ed25519 signature is valid (not tampered)
    3. Hostname matches this machine
    4. License has not expired

    Returns LicenseInfo on success, raises LicenseError on failure.
    """
    filepath = filepath or LICENSE_FILE

    # Step 1: Parse
    payload_bytes, signature = _parse_license_file(filepath)

    # Step 2: Verify signature
    public_key = _load_public_key()
    try:
        public_key.verify(signature, payload_bytes)
    except InvalidSignature:
        raise LicenseError(
            "License signature verification FAILED. "
            "The license file may have been tampered with or is not issued by the vendor."
        )

    # Step 3: Parse payload
    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise LicenseError("License payload is malformed.")

    customer = payload.get("customer", "Unknown")
    hostname = payload.get("hostname", "")
    issued = payload.get("issued", "")
    expires = payload.get("expires", "")
    features = payload.get("features", [])
    max_users = payload.get("max_users", 1)
    serial = payload.get("serial", "N/A")

    # Step 4: Hardware fingerprint check (new licenses) or hostname check (legacy licenses)
    hardware_fingerprint = payload.get("hardware_fingerprint", "")
    factor_hashes        = payload.get("factor_hashes", None)

    if hardware_fingerprint:
        # New-style license: multi-factor hardware binding
        if not _get_hw_fingerprint_match(hardware_fingerprint, factor_hashes):
            raise LicenseError(
                "License hardware fingerprint does not match this machine. "
                "The software may have been copied to an unauthorised machine. "
                f"Serial: {serial}. Contact your vendor."
            )
        logger.info("Hardware fingerprint verified OK")
    else:
        # Legacy license: hostname-only binding (backward compatible)
        actual_hostname = socket.gethostname().upper()
        if hostname.upper() != actual_hostname:
            raise LicenseError(
                f"License is bound to hostname '{hostname}' but this machine is "
                f"'{actual_hostname}'. Contact your vendor for a license matching "
                "this machine."
            )

    # Step 5: Check expiry
    try:
        exp_date = date.fromisoformat(expires)
    except ValueError:
        raise LicenseError(f"Invalid expiry date in license: {expires}")

    days_remaining = (exp_date - date.today()).days
    if days_remaining < 0:
        raise LicenseError(
            f"License expired on {expires} ({-days_remaining} days ago). "
            f"Serial: {serial}. Contact your vendor for renewal."
        )

    logger.info(
        "License valid: customer=%s, serial=%s, expires=%s (%d days remaining)",
        customer, serial, expires, days_remaining,
    )

    return LicenseInfo(
        customer=customer,
        hostname=hostname,
        issued=issued,
        expires=expires,
        features=features,
        max_users=max_users,
        serial=serial,
        days_remaining=days_remaining,
    )


def get_license_status(filepath: str | None = None) -> dict:
    """
    Non-throwing version for the status endpoint.
    Returns a dict with validity info regardless of license state.
    """
    try:
        info = validate_license(filepath)
        return {
            "valid": True,
            "customer": info.customer,
            "hostname": info.hostname,
            "serial": info.serial,
            "issued": info.issued,
            "expires": info.expires,
            "days_remaining": info.days_remaining,
            "features": info.features,
            "max_users": info.max_users,
            "error": None,
        }
    except LicenseError as e:
        return {
            "valid": False,
            "customer": None,
            "hostname": None,
            "serial": None,
            "issued": None,
            "expires": None,
            "days_remaining": None,
            "features": [],
            "max_users": 0,
            "error": str(e),
        }

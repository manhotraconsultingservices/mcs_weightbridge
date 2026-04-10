#!/usr/bin/env python3
"""
Weighbridge License Generator — Vendor-side CLI tool.

This utility generates machine-bound, time-limited license keys signed with
Ed25519. The application validates these keys using the embedded public key.

NEVER deploy this tool or the private key to client machines.

Usage:
    # One-time: generate vendor key pair
    python generate_license.py --generate-keypair

    # Generate a license with hardware fingerprint binding (RECOMMENDED)
    python generate_license.py \
        --customer "ABC Stone Crushers" \
        --hostname "WEIGHBRIDGE-PC" \
        --expires 2027-04-02 \
        --fingerprint-file client_fingerprint.json \
        --output license.key

    # Generate a license with hostname-only binding (fallback)
    python generate_license.py \
        --customer "ABC Stone Crushers" \
        --hostname "WEIGHBRIDGE-PC" \
        --expires 2027-04-02 \
        --output license.key

    # Verify an existing license file
    python generate_license.py --verify license.key

    # Show public key (to embed in application source)
    python generate_license.py --show-public-key

Fingerprint workflow:
    1. Client runs: python show_fingerprint.py > fingerprint.json
    2. Client sends fingerprint.json to vendor (WhatsApp/email)
    3. Vendor runs: python generate_license.py --fingerprint-file fingerprint.json ...
    4. The license is now bound to the client's hardware (CPU/MB/Disk/WinProd)
    5. 2-of-4 factor tolerance allows replacing up to 2 components without re-license
"""

import argparse
import base64
import json
import os
import sys
from datetime import date, datetime

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidSignature
except ImportError:
    print("ERROR: 'cryptography' package required. Install with: pip install cryptography")
    sys.exit(1)

PRIVATE_KEY_FILE = os.path.join(os.path.dirname(__file__), "vendor_private.key")
PUBLIC_KEY_FILE = os.path.join(os.path.dirname(__file__), "vendor_public.key")
SERIAL_COUNTER_FILE = os.path.join(os.path.dirname(__file__), ".serial_counter")

# ── Key pair generation ─────────────────────────────────────────────────────

def generate_keypair():
    """Generate a new Ed25519 key pair for license signing."""
    if os.path.exists(PRIVATE_KEY_FILE):
        resp = input(f"WARNING: {PRIVATE_KEY_FILE} already exists. Overwrite? (yes/no): ")
        if resp.strip().lower() != "yes":
            print("Aborted.")
            return

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Save private key (PEM, unencrypted — protect this file!)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(PRIVATE_KEY_FILE, "wb") as f:
        f.write(private_pem)

    # Save public key (PEM)
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with open(PUBLIC_KEY_FILE, "wb") as f:
        f.write(public_pem)

    # Also output the raw public key bytes as base64 for embedding in source
    raw_pub = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(raw_pub).decode()

    print("=" * 60)
    print("KEY PAIR GENERATED SUCCESSFULLY")
    print("=" * 60)
    print(f"Private key: {PRIVATE_KEY_FILE}")
    print(f"Public key:  {PUBLIC_KEY_FILE}")
    print()
    print("EMBED THIS PUBLIC KEY in backend/app/services/license.py:")
    print(f'VENDOR_PUBLIC_KEY_B64 = "{pub_b64}"')
    print()
    print("IMPORTANT: Keep vendor_private.key SECRET. Never deploy it to clients.")
    print("=" * 60)


def show_public_key():
    """Display the public key in embeddable format."""
    if not os.path.exists(PUBLIC_KEY_FILE):
        print("ERROR: No public key found. Run --generate-keypair first.")
        sys.exit(1)

    with open(PUBLIC_KEY_FILE, "rb") as f:
        public_key = serialization.load_pem_public_key(f.read())

    raw_pub = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(raw_pub).decode()
    print(f'VENDOR_PUBLIC_KEY_B64 = "{pub_b64}"')


# ── Serial number ───────────────────────────────────────────────────────────

def _next_serial() -> str:
    """Generate next sequential serial number: WB-YYYY-NNNN."""
    year = date.today().year
    counter = 1
    if os.path.exists(SERIAL_COUNTER_FILE):
        try:
            with open(SERIAL_COUNTER_FILE) as f:
                data = json.load(f)
                if data.get("year") == year:
                    counter = data.get("counter", 0) + 1
        except (json.JSONDecodeError, KeyError):
            pass

    serial = f"WB-{year}-{counter:04d}"
    with open(SERIAL_COUNTER_FILE, "w") as f:
        json.dump({"year": year, "counter": counter}, f)
    return serial


# ── License generation ──────────────────────────────────────────────────────

def generate_license(args):
    """Generate a signed license file."""
    if not os.path.exists(PRIVATE_KEY_FILE):
        print("ERROR: No private key found. Run --generate-keypair first.")
        sys.exit(1)

    # Load private key
    with open(PRIVATE_KEY_FILE, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    # Parse features
    features = [f.strip() for f in args.features.split(",") if f.strip()]

    # Build payload
    serial = _next_serial()
    payload = {
        "v": 1,
        "customer": args.customer,
        "hostname": args.hostname.upper(),  # normalize to uppercase
        "issued": date.today().isoformat(),
        "expires": args.expires,
        "features": features,
        "max_users": args.max_users,
        "serial": serial,
    }

    # Add hardware fingerprint if provided (from show_fingerprint.py JSON output)
    if args.fingerprint_file:
        fp_path = args.fingerprint_file
        if not os.path.exists(fp_path):
            print(f"ERROR: Fingerprint file not found: {fp_path}")
            sys.exit(1)
        try:
            with open(fp_path, "r", encoding="utf-8") as f:
                fp_data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"ERROR: Cannot read fingerprint file: {e}")
            sys.exit(1)

        hw_fp = fp_data.get("hardware_fingerprint", "")
        fh = fp_data.get("factor_hashes", {})
        if not hw_fp or hw_fp == "NO_HW_INFO":
            print("WARNING: Fingerprint file contains NO_HW_INFO — license will use hostname-only binding.")
        else:
            payload["hardware_fingerprint"] = hw_fp
            payload["factor_hashes"] = fh
            print(f"  Hardware fingerprint loaded from: {fp_path}")
            print(f"  Binding: hardware (2-of-4 tolerance)")

        # Override hostname from fingerprint file if present
        if fp_data.get("hostname"):
            payload["hostname"] = fp_data["hostname"].upper()

    # Validate expiry
    try:
        exp_date = date.fromisoformat(args.expires)
    except ValueError:
        print(f"ERROR: Invalid expiry date format: {args.expires}. Use YYYY-MM-DD.")
        sys.exit(1)

    if exp_date <= date.today():
        print(f"WARNING: Expiry date {args.expires} is in the past or today!")

    # Serialize and sign
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_bytes = payload_json.encode("utf-8")
    signature = private_key.sign(payload_bytes)

    # Encode
    payload_b64 = base64.b64encode(payload_bytes).decode()
    sig_b64 = base64.b64encode(signature).decode()

    # Format license file
    license_text = (
        "-----BEGIN WEIGHBRIDGE LICENSE-----\n"
        f"{payload_b64}\n"
        "-----END WEIGHBRIDGE LICENSE-----\n"
        "-----BEGIN SIGNATURE-----\n"
        f"{sig_b64}\n"
        "-----END SIGNATURE-----\n"
    )

    # Write output
    output_path = args.output or "license.key"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(license_text)

    print("=" * 60)
    print("LICENSE GENERATED SUCCESSFULLY")
    print("=" * 60)
    print(f"  Serial:    {serial}")
    print(f"  Customer:  {args.customer}")
    print(f"  Hostname:  {payload['hostname']}")
    if "hardware_fingerprint" in payload:
        print(f"  HW Bound:  YES (2-of-4 factor tolerance)")
        print(f"  HW FP:     {payload['hardware_fingerprint'][:16]}...")
    else:
        print(f"  HW Bound:  NO (hostname-only binding)")
    print(f"  Issued:    {date.today().isoformat()}")
    print(f"  Expires:   {args.expires}")
    print(f"  Features:  {', '.join(features)}")
    print(f"  Max Users: {args.max_users}")
    print(f"  Output:    {output_path}")
    print("=" * 60)


# ── License verification ────────────────────────────────────────────────────

def verify_license(filepath: str):
    """Verify an existing license file."""
    if not os.path.exists(PUBLIC_KEY_FILE):
        print("ERROR: No public key found. Run --generate-keypair first.")
        sys.exit(1)

    with open(PUBLIC_KEY_FILE, "rb") as f:
        public_key = serialization.load_pem_public_key(f.read())

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"ERROR: License file not found: {filepath}")
        sys.exit(1)

    # Parse
    try:
        payload_b64 = content.split("-----BEGIN WEIGHBRIDGE LICENSE-----")[1].split("-----END WEIGHBRIDGE LICENSE-----")[0].strip()
        sig_b64 = content.split("-----BEGIN SIGNATURE-----")[1].split("-----END SIGNATURE-----")[0].strip()
    except (IndexError, ValueError):
        print("ERROR: Invalid license file format.")
        sys.exit(1)

    payload_bytes = base64.b64decode(payload_b64)
    signature = base64.b64decode(sig_b64)

    # Verify signature
    try:
        public_key.verify(signature, payload_bytes)
    except InvalidSignature:
        print("FAILED: Signature verification FAILED. License may be tampered with.")
        sys.exit(1)

    payload = json.loads(payload_bytes)
    exp_date = date.fromisoformat(payload["expires"])
    days_remaining = (exp_date - date.today()).days
    is_expired = days_remaining < 0

    print("=" * 60)
    print("LICENSE VERIFICATION RESULT")
    print("=" * 60)
    print(f"  Signature:  VALID")
    print(f"  Serial:     {payload.get('serial', 'N/A')}")
    print(f"  Customer:   {payload['customer']}")
    print(f"  Hostname:   {payload['hostname']}")
    print(f"  Issued:     {payload['issued']}")
    print(f"  Expires:    {payload['expires']}")
    print(f"  Days Left:  {days_remaining}")
    print(f"  Status:     {'EXPIRED' if is_expired else 'ACTIVE'}")
    print(f"  Features:   {', '.join(payload.get('features', []))}")
    print(f"  Max Users:  {payload.get('max_users', 'N/A')}")
    print("=" * 60)

    if is_expired:
        print("\nWARNING: This license has EXPIRED.")
        sys.exit(1)


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Weighbridge License Generator — Vendor Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Modes
    parser.add_argument("--generate-keypair", action="store_true",
                        help="Generate a new Ed25519 key pair")
    parser.add_argument("--show-public-key", action="store_true",
                        help="Display public key for embedding in source")
    parser.add_argument("--verify", metavar="FILE",
                        help="Verify an existing license file")

    # License generation params
    parser.add_argument("--customer", help="Customer/company name")
    parser.add_argument("--hostname", help="Target server hostname (case-insensitive)")
    parser.add_argument("--expires", help="Expiry date (YYYY-MM-DD)")
    parser.add_argument("--fingerprint-file", metavar="JSON_FILE",
                        help="Path to JSON file from show_fingerprint.py (adds hardware binding)")
    parser.add_argument("--features", default="invoicing,private_invoices,tally,gst_reports",
                        help="Comma-separated feature list (default: all)")
    parser.add_argument("--max-users", type=int, default=5,
                        help="Maximum concurrent users (default: 5)")
    parser.add_argument("--output", "-o", help="Output file path (default: license.key)")

    args = parser.parse_args()

    if args.generate_keypair:
        generate_keypair()
    elif args.show_public_key:
        show_public_key()
    elif args.verify:
        verify_license(args.verify)
    elif args.customer and args.hostname and args.expires:
        generate_license(args)
    else:
        parser.print_help()
        print("\nERROR: Provide --customer, --hostname, and --expires to generate a license.")
        sys.exit(1)


if __name__ == "__main__":
    main()

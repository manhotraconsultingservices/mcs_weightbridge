#!/usr/bin/env python3
"""
Weighbridge ERP — Vendor License Generator
==========================================

VENDOR-ONLY tool. Never ship this script or vendor_private.key to clients.

Prerequisites:
    pip install cryptography

First-time setup (run once, keep private key safe):
    python generate_license.py --keygen

Issue a hardware-locked license:
    python generate_license.py \\
        --fingerprint fingerprint.json \\
        --customer "Shree Ram Stone Crusher Pvt Ltd" \\
        --serial WB-2025-001 \\
        --expires 2026-04-12 \\
        --output license.key

Issue a hostname-only license (legacy / VM environments):
    python generate_license.py \\
        --hostname CLIENT-PC \\
        --customer "Test Corp" \\
        --serial WB-2025-002 \\
        --expires 2026-04-12

Verify an existing license (without starting the server):
    python generate_license.py --verify license.key
"""

import argparse
import base64
import json
import sys
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Key file path (sibling of this script, never committed to git)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
PRIVATE_KEY_FILE = SCRIPT_DIR / "vendor_private.key"
PUBLIC_KEY_FILE  = SCRIPT_DIR / "vendor_public.key"


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

def cmd_keygen():
    """Generate a new Ed25519 key pair."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, PublicFormat, NoEncryption,
    )

    if PRIVATE_KEY_FILE.exists():
        ans = input(f"\nPrivate key already exists at {PRIVATE_KEY_FILE}.\nOverwrite? [y/N] ").strip().lower()
        if ans != "y":
            print("Aborted.")
            return

    private_key = Ed25519PrivateKey.generate()
    pub_key     = private_key.public_key()

    # Save raw private key bytes (32 bytes) as base64 PEM-style
    priv_raw = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_raw  = pub_key.public_bytes(Encoding.Raw, PublicFormat.Raw)

    priv_b64 = base64.b64encode(priv_raw).decode()
    pub_b64  = base64.b64encode(pub_raw).decode()

    PRIVATE_KEY_FILE.write_text(
        f"-----BEGIN WEIGHBRIDGE PRIVATE KEY-----\n{priv_b64}\n-----END WEIGHBRIDGE PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    PUBLIC_KEY_FILE.write_text(
        f"-----BEGIN WEIGHBRIDGE PUBLIC KEY-----\n{pub_b64}\n-----END WEIGHBRIDGE PUBLIC KEY-----\n",
        encoding="utf-8",
    )

    print("\n✅ Key pair generated successfully!")
    print(f"   Private key : {PRIVATE_KEY_FILE}  ← KEEP OFFLINE, NEVER SHARE")
    print(f"   Public key  : {PUBLIC_KEY_FILE}")
    print()
    print("─" * 70)
    print("ACTION REQUIRED — update backend/app/services/license.py:")
    print("─" * 70)
    print(f'\nVENDOR_PUBLIC_KEY_B64 = "{pub_b64}"\n')
    print("Replace the existing VENDOR_PUBLIC_KEY_B64 line with the above,")
    print("then rebuild the application binary.\n")


# ---------------------------------------------------------------------------
# License generation
# ---------------------------------------------------------------------------

def _load_private_key():
    """Load Ed25519 private key from vendor_private.key."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not PRIVATE_KEY_FILE.exists():
        print(f"\n❌ Private key not found: {PRIVATE_KEY_FILE}")
        print("   Run: python generate_license.py --keygen")
        sys.exit(1)

    content = PRIVATE_KEY_FILE.read_text(encoding="utf-8")
    try:
        priv_b64 = (
            content.split("-----BEGIN WEIGHBRIDGE PRIVATE KEY-----")[1]
            .split("-----END WEIGHBRIDGE PRIVATE KEY-----")[0]
            .strip()
        )
        priv_raw = base64.b64decode(priv_b64)
        return Ed25519PrivateKey.from_private_bytes(priv_raw)
    except Exception as e:
        print(f"\n❌ Failed to parse private key: {e}")
        sys.exit(1)


def cmd_generate(args):
    """Generate a signed license file."""
    # ── Validate arguments ────────────────────────────────────────────────
    if not args.fingerprint and not args.hostname:
        print("\n❌ Provide either --fingerprint <file> or --hostname <name>")
        sys.exit(1)

    # ── Parse expiry date ─────────────────────────────────────────────────
    try:
        exp_date = date.fromisoformat(args.expires)
    except ValueError:
        print(f"\n❌ Invalid date format: {args.expires}  (expected YYYY-MM-DD)")
        sys.exit(1)

    if exp_date <= date.today():
        print(f"\n⚠️  Warning: expiry date {args.expires} is in the past or today.")
        if input("   Continue anyway? [y/N] ").strip().lower() != "y":
            sys.exit(0)

    # ── Build payload ─────────────────────────────────────────────────────
    payload: dict = {
        "customer": args.customer,
        "serial":   args.serial,
        "issued":   date.today().isoformat(),
        "expires":  args.expires,
        "features": args.features.split(",") if args.features else [],
        "max_users": args.max_users,
    }

    if args.fingerprint:
        fp_path = Path(args.fingerprint)
        if not fp_path.exists():
            print(f"\n❌ Fingerprint file not found: {fp_path}")
            sys.exit(1)
        fp_data = json.loads(fp_path.read_text(encoding="utf-8"))
        payload["hardware_fingerprint"] = fp_data.get("hardware_fingerprint", "")
        payload["factor_hashes"]        = fp_data.get("factor_hashes", {})
        payload["hostname"]             = fp_data.get("hostname", "")
        # Warn if fingerprint is NO_HW_INFO
        if payload["hardware_fingerprint"] == "NO_HW_INFO":
            print("\n⚠️  Warning: fingerprint.json has NO_HW_INFO (virtualised/non-Windows).")
            print("   License will fall back to hostname binding.")
    else:
        payload["hostname"] = args.hostname.upper()

    # ── Sign ──────────────────────────────────────────────────────────────
    private_key   = _load_private_key()
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature     = private_key.sign(payload_bytes)

    payload_b64 = base64.b64encode(payload_bytes).decode()
    sig_b64     = base64.b64encode(signature).decode()

    license_text = (
        "-----BEGIN WEIGHBRIDGE LICENSE-----\n"
        f"{payload_b64}\n"
        "-----END WEIGHBRIDGE LICENSE-----\n"
        "-----BEGIN SIGNATURE-----\n"
        f"{sig_b64}\n"
        "-----END SIGNATURE-----\n"
    )

    # ── Write output ──────────────────────────────────────────────────────
    out_path = Path(args.output)
    out_path.write_text(license_text, encoding="utf-8")

    days = (exp_date - date.today()).days
    print("\n✅ License generated successfully!")
    print(f"   Customer  : {args.customer}")
    print(f"   Serial    : {args.serial}")
    print(f"   Issued    : {payload['issued']}")
    print(f"   Expires   : {args.expires}  ({days} days remaining)")
    if args.fingerprint:
        print(f"   Binding   : Hardware fingerprint (2-of-4 tolerance)")
        print(f"   Hostname  : {payload.get('hostname', '—')}")
    else:
        print(f"   Binding   : Hostname — {args.hostname.upper()}")
    print(f"   Output    : {out_path.resolve()}")
    print()
    print("NEXT STEPS:")
    print(f"  1. Copy {out_path} to the USB drive root")
    print("  2. The installer will place it at C:\\weighbridge\\license.key")
    print()


# ---------------------------------------------------------------------------
# License verification (without starting the server)
# ---------------------------------------------------------------------------

def cmd_verify(args):
    """Verify an existing license file using the embedded public key."""
    try:
        pub_content = PUBLIC_KEY_FILE.read_text(encoding="utf-8")
        pub_b64 = (
            pub_content.split("-----BEGIN WEIGHBRIDGE PUBLIC KEY-----")[1]
            .split("-----END WEIGHBRIDGE PUBLIC KEY-----")[0]
            .strip()
        )
    except Exception:
        print(f"\n❌ Could not read public key from {PUBLIC_KEY_FILE}")
        print("   Run --keygen first, or check your key files.")
        sys.exit(1)

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature

    lic_path = Path(args.verify)
    if not lic_path.exists():
        print(f"\n❌ License file not found: {lic_path}")
        sys.exit(1)

    content = lic_path.read_text(encoding="utf-8")
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
        payload_bytes = base64.b64decode(payload_b64)
        signature     = base64.b64decode(sig_b64)
    except Exception as e:
        print(f"\n❌ Failed to parse license file: {e}")
        sys.exit(1)

    pub_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64))
    try:
        pub_key.verify(signature, payload_bytes)
    except InvalidSignature:
        print("\n❌ SIGNATURE INVALID — license may be tampered or signed with a different key")
        sys.exit(1)

    payload = json.loads(payload_bytes)
    exp_date = date.fromisoformat(payload["expires"])
    days = (exp_date - date.today()).days

    print("\n✅ Signature valid")
    print()
    print("License details:")
    print(f"  Customer         : {payload.get('customer', '—')}")
    print(f"  Serial           : {payload.get('serial', '—')}")
    print(f"  Issued           : {payload.get('issued', '—')}")
    print(f"  Expires          : {payload.get('expires', '—')}  ({days} days remaining)")
    print(f"  Hostname         : {payload.get('hostname', '—')}")
    hw = payload.get('hardware_fingerprint', '')
    print(f"  HW Fingerprint   : {hw[:16]}...  [{('present' if hw and hw != 'NO_HW_INFO' else 'absent')}]")
    print(f"  Max users        : {payload.get('max_users', 1)}")
    print(f"  Features         : {', '.join(payload.get('features', [])) or 'all'}")
    if days < 0:
        print(f"\n⚠️  License EXPIRED {-days} days ago")
    elif days < 30:
        print(f"\n⚠️  License expiring soon — {days} days remaining")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Weighbridge ERP — Vendor License Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("--keygen", action="store_true",
                        help="Generate a new Ed25519 key pair (run once at vendor setup)")
    parser.add_argument("--fingerprint", metavar="FILE",
                        help="Path to fingerprint.json from client machine")
    parser.add_argument("--hostname", metavar="NAME",
                        help="Hostname to bind (legacy mode, when no fingerprint)")
    parser.add_argument("--customer", metavar="NAME", default="Unknown Customer",
                        help="Customer company name")
    parser.add_argument("--serial", metavar="ID", default="WB-0000",
                        help="License serial number (e.g. WB-2025-001)")
    parser.add_argument("--expires", metavar="YYYY-MM-DD",
                        default=(date.today() + timedelta(days=365)).isoformat(),
                        help="License expiry date (default: 1 year from today)")
    parser.add_argument("--features", metavar="LIST", default="",
                        help="Comma-separated feature list (leave empty = all features)")
    parser.add_argument("--max-users", type=int, default=10, dest="max_users",
                        help="Maximum concurrent users (default: 10)")
    parser.add_argument("--output", metavar="FILE", default="license.key",
                        help="Output license file (default: license.key)")
    parser.add_argument("--verify", metavar="FILE",
                        help="Verify an existing license file")

    args = parser.parse_args()

    print()
    print("┌─────────────────────────────────────────────┐")
    print("│  Weighbridge ERP — Vendor License Generator │")
    print("└─────────────────────────────────────────────┘")

    if args.keygen:
        cmd_keygen()
    elif args.verify:
        cmd_verify(args)
    elif args.fingerprint or args.hostname:
        cmd_generate(args)
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python generate_license.py --keygen")
        print("  python generate_license.py --fingerprint fingerprint.json --customer 'ABC Corp' --serial WB-2025-001 --expires 2026-04-12")
        print("  python generate_license.py --verify license.key")


if __name__ == "__main__":
    main()

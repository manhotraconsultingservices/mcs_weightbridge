#!/usr/bin/env python
"""
USB Key Setup — run once on the server with the USB drive inserted.

Generates a cryptographically secure key pair and writes it to the USB drive.
The key file contains: <uuid>:<hmac_secret_hex>

The HMAC secret is 256 bits of random data. Even if someone knows the UUID
(visible in the database), they CANNOT authenticate without the secret
that only exists on the physical USB drive.

Usage:
    python setup_usb_key.py
    python setup_usb_key.py "Office Main Key"

Security notes:
  - Keep the USB drive physically secure
  - Do NOT copy the .weighbridge_key file to any other location
  - The UUID is stored in the database; the hmac_secret is also stored
    (needed to verify client HMAC signatures) but is NEVER returned via API
  - If the USB is lost, deactivate it immediately via Settings → USB Guard → Deactivate
  - Create a recovery PIN (Settings → USB Guard → Recovery) before you need it
"""
import secrets
import sys
import os
import string
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text

DATABASE_URL = "postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge"
KEY_FILENAME = ".weighbridge_key"


def get_removable_drives() -> list[str]:
    import ctypes
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            if ctypes.windll.kernel32.GetDriveTypeW(drive) == 2:  # DRIVE_REMOVABLE
                drives.append(drive)
    return drives


async def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "Primary Key"

    # Generate cryptographically secure key pair
    key_uuid = secrets.token_hex(16)      # 128-bit unique identifier
    hmac_secret = secrets.token_hex(32)   # 256-bit HMAC secret (never shared)
    file_content = f"{key_uuid}:{hmac_secret}"

    print(f"\n{'='*60}")
    print(f"  Weighbridge USB Key Setup")
    print(f"{'='*60}\n")

    # Find removable drives
    drives = get_removable_drives()
    if not drives:
        print("ERROR: No removable USB drives found.")
        print("  Insert the USB drive and run again.\n")
        return

    print(f"  Found USB drive(s): {', '.join(drives)}")

    # Write key file to each removable drive found
    written = []
    for drive in drives:
        key_path = os.path.join(drive, KEY_FILENAME)
        try:
            with open(key_path, 'w') as f:
                f.write(file_content)
            # Hide the file on Windows
            try:
                import subprocess
                subprocess.run(["attrib", "+H", key_path], capture_output=True)
            except Exception:
                pass
            written.append(drive)
            print(f"  [OK] Written to {key_path}")
        except PermissionError:
            print(f"  [ERROR] Cannot write to {drive} — run as Administrator")

    if not written:
        return

    # Register in database
    print(f"\n  Registering in database...")
    try:
        engine = create_async_engine(DATABASE_URL)
        async with AsyncSession(engine) as db:
            await db.execute(
                text("""
                    INSERT INTO usb_keys (key_uuid, hmac_secret, label)
                    VALUES (:uuid, :secret, :label)
                    ON CONFLICT (key_uuid) DO UPDATE
                    SET is_active = TRUE, hmac_secret = :secret, label = :label
                """),
                {"uuid": key_uuid, "secret": hmac_secret, "label": label}
            )
            await db.commit()
        await engine.dispose()
        print(f"  [OK] Key registered in database")
    except Exception as e:
        print(f"  [ERROR] Database registration failed: {e}")
        print(f"  The key file was written to USB but not registered.")
        print(f"  Register manually via Settings → USB Guard → Register Key")
        print(f"  UUID:   {key_uuid}")

    print(f"\n{'='*60}")
    print(f"  KEY DETAILS (store securely, do not share)")
    print(f"{'='*60}")
    print(f"  Label:       {label}")
    print(f"  UUID:        {key_uuid}")
    print(f"  Key file:    {KEY_FILENAME}")
    print(f"  Security:    HMAC-SHA256 challenge-response")
    print(f"\n  IMPORTANT:")
    print(f"  - Keep the USB physically secure")
    print(f"  - Never copy the .weighbridge_key file elsewhere")
    print(f"  - If USB is lost: Settings → USB Guard → Deactivate Key")
    print(f"  - Create a recovery PIN before you need it")
    print(f"{'='*60}\n")


asyncio.run(main())

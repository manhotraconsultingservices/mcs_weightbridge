"""
Windows DPAPI-based secrets manager.

Encrypts application secrets using the Windows Data Protection API (DPAPI)
with CRYPTPROTECT_LOCAL_MACHINE flag, binding them to this specific machine.
Encrypted blobs cannot be decrypted on a different machine even with the
same Windows credentials.

Usage:
  1. First-time setup: run `python setup_dpapi.py` to encrypt .env secrets
     -> produces `secrets.dpapi` next to the backend
  2. At runtime: SecretsManager reads and decrypts `secrets.dpapi`
  3. Decrypted values live only in memory — never written to disk again

Fallback: if DPAPI is unavailable (non-Windows, testing) or secrets.dpapi
doesn't exist, falls back to .env file. This allows development workflow
to continue unchanged.
"""

import base64
import ctypes
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Location of the DPAPI-encrypted secrets blob
_THIS_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
SECRETS_FILE = _THIS_DIR / "secrets.dpapi"


class _DataBlob(ctypes.Structure):
    """Windows CRYPT_DATA_BLOB structure."""
    _fields_ = [
        ("cbData", ctypes.c_ulong),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _dpapi_encrypt(plaintext: bytes, description: str = "WeighbridgeERP") -> bytes:
    """
    Encrypt bytes using Windows DPAPI (machine-scoped).
    Raises RuntimeError on failure.
    """
    if sys.platform != "win32":
        raise RuntimeError("DPAPI is only available on Windows")

    desc = ctypes.create_unicode_buffer(description)
    buf  = ctypes.create_string_buffer(plaintext)

    input_blob  = _DataBlob(len(plaintext), buf)
    output_blob = _DataBlob()

    # CRYPTPROTECT_LOCAL_MACHINE = 0x4  (any process on same machine can decrypt)
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        desc,
        None, None, None,
        0x4,
        ctypes.byref(output_blob),
    )
    if not ok:
        err = ctypes.windll.kernel32.GetLastError()
        raise RuntimeError(f"CryptProtectData failed with error code {err}")

    encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    ctypes.windll.kernel32.LocalFree(output_blob.pbData)
    return encrypted


def _dpapi_decrypt(encrypted: bytes) -> bytes:
    """
    Decrypt DPAPI-encrypted bytes.
    Raises RuntimeError if decryption fails (wrong machine or corrupted data).
    """
    if sys.platform != "win32":
        raise RuntimeError("DPAPI is only available on Windows")

    buf        = ctypes.create_string_buffer(encrypted)
    input_blob = _DataBlob(len(encrypted), buf)
    output_blob = _DataBlob()

    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None, None, None, None,
        0,
        ctypes.byref(output_blob),
    )
    if not ok:
        err = ctypes.windll.kernel32.GetLastError()
        raise RuntimeError(
            f"CryptUnprotectData failed (code {err}). "
            "This machine may not be the machine on which the secrets were encrypted."
        )

    decrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    ctypes.windll.kernel32.LocalFree(output_blob.pbData)
    return decrypted


def encrypt_secrets(secrets_dict: dict[str, str], output_path: Optional[Path] = None) -> Path:
    """
    Encrypt a dict of secrets and write to secrets.dpapi.
    Called once during deployment setup.
    """
    output_path = output_path or SECRETS_FILE
    payload     = json.dumps(secrets_dict).encode("utf-8")
    encrypted   = _dpapi_encrypt(payload)
    encoded     = base64.b64encode(encrypted).decode("ascii")

    with open(output_path, "w") as f:
        f.write("-----BEGIN WEIGHBRIDGE SECRETS-----\n")
        f.write(encoded + "\n")
        f.write("-----END WEIGHBRIDGE SECRETS-----\n")

    logger.info("DPAPI-encrypted secrets written to %s", output_path)
    return output_path


def decrypt_secrets(secrets_path: Optional[Path] = None) -> dict[str, str]:
    """
    Read and decrypt secrets.dpapi. Returns dict of {key: value}.
    Raises RuntimeError if decryption fails.
    """
    secrets_path = secrets_path or SECRETS_FILE
    with open(secrets_path) as f:
        content = f.read()

    encoded = (
        content
        .split("-----BEGIN WEIGHBRIDGE SECRETS-----")[1]
        .split("-----END WEIGHBRIDGE SECRETS-----")[0]
        .strip()
    )
    encrypted = base64.b64decode(encoded)
    decrypted = _dpapi_decrypt(encrypted)
    return json.loads(decrypted.decode("utf-8"))


class SecretsManager:
    """
    Application-level secrets accessor.

    Priority:
      1. DPAPI-encrypted secrets.dpapi  (production)
      2. .env file via pydantic-settings (development / fallback)
    """
    _cache: Optional[dict[str, str]] = None

    @classmethod
    def _load(cls) -> dict[str, str]:
        if cls._cache is not None:
            return cls._cache

        if SECRETS_FILE.exists():
            try:
                cls._cache = decrypt_secrets()
                logger.info("Secrets loaded from DPAPI-encrypted store")
                return cls._cache
            except Exception as exc:
                logger.critical(
                    "FAILED to decrypt secrets.dpapi: %s. "
                    "This machine may not be authorised to run the software. "
                    "Falling back to .env (development mode only).",
                    exc,
                )

        # Fallback — .env file (development only)
        logger.warning("secrets.dpapi not found — using .env file (development mode)")
        cls._cache = {}
        return cls._cache

    @classmethod
    def get(cls, key: str, default: str = "") -> str:
        secrets = cls._load()
        # DPAPI store takes priority; fall through to env var
        return secrets.get(key) or os.environ.get(key, default)

"""
Field-level AES-256-GCM encryption for private invoice data.

All sensitive fields are encrypted before writing to the database.
Even direct psql SELECT returns only ciphertext — unreadable without the key.

Algorithm: AES-256-GCM
  - 256-bit key from PRIVATE_DATA_KEY env var (hex string → bytes)
  - Random 96-bit nonce per encryption (prepended to ciphertext)
  - 128-bit authentication tag (appended by GCM — detects tampering)
  - Output: base64-encoded(nonce + ciphertext + tag)

Storage format: "ENC:v1:<base64>" prefix makes encrypted fields identifiable.
"""
import base64
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_KEY: Optional[bytes] = None
_PREFIX = "ENC:v1:"


def _get_key() -> bytes:
    global _KEY
    if _KEY is None:
        # Try environment variable first, then pydantic settings
        hex_key = os.environ.get("PRIVATE_DATA_KEY", "")
        if not hex_key:
            try:
                from app.config import get_settings
                hex_key = get_settings().PRIVATE_DATA_KEY
            except Exception:
                pass
        if not hex_key or len(hex_key) < 64:
            raise RuntimeError(
                "PRIVATE_DATA_KEY not set or too short in .env. "
                "Must be a 64-char hex string (256-bit key)."
            )
        _KEY = bytes.fromhex(hex_key[:64])
    return _KEY


def encrypt(value: Optional[str]) -> Optional[str]:
    """
    Encrypt a string value. Returns ENC:v1:<base64> or None if input is None.
    Each call uses a fresh random nonce — same plaintext → different ciphertext.
    """
    if value is None:
        return None
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)          # 96-bit random nonce
    ciphertext = aesgcm.encrypt(nonce, value.encode("utf-8"), None)
    # ciphertext already includes the GCM authentication tag (last 16 bytes)
    encoded = base64.b64encode(nonce + ciphertext).decode("ascii")
    return _PREFIX + encoded


def decrypt(value: Optional[str]) -> Optional[str]:
    """
    Decrypt an ENC:v1:<base64> value. Returns plaintext or None.
    If value is not encrypted (legacy plain text), returns as-is.
    Raises ValueError if ciphertext is tampered.
    """
    if value is None:
        return None
    if not value.startswith(_PREFIX):
        return value   # legacy unencrypted value — pass through
    key = _get_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(value[len(_PREFIX):])
    nonce, ciphertext = raw[:12], raw[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


def encrypt_float(value: Optional[float]) -> Optional[str]:
    """Encrypt a numeric value (stored as string in DB)."""
    if value is None:
        return None
    return encrypt(str(value))


def decrypt_float(value: Optional[str]) -> Optional[float]:
    """Decrypt a numeric value."""
    plain = decrypt(value)
    if plain is None:
        return None
    try:
        return float(plain)
    except (ValueError, TypeError):
        return None


def is_encrypted(value: Optional[str]) -> bool:
    return bool(value and value.startswith(_PREFIX))

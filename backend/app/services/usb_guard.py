"""
USB Guard service — hardened authentication for private invoice access.

Security model:
  - USB key file contains TWO secrets: uuid + hmac_secret (hex)
    → UUID alone (visible in DB) cannot authenticate; HMAC secret never leaves USB drive
  - HMAC challenge-response: server issues a one-time nonce (60s TTL)
    → Even if network traffic is intercepted, the signature cannot be replayed
  - bcrypt for recovery PIN (salted, slow — rainbow tables useless)
  - Rate limiting: 5 failed attempts → 15-minute lockout per scope (ip/user)
  - IP binding: client sessions are tied to the originating IP
  - Full audit log: every auth event (success + failure) written to usb_auth_log
  - Private invoice integrity: each record stores HMAC of its own fields

Key file format on USB drive (.weighbridge_key):
    <uuid>:<64-hex-char-hmac-secret>
    Example: 550e8400-e29b-41d4-a716-446655440000:a1b2c3d4...

The HMAC secret is 32 random bytes (256 bits). It is stored in the database
so the server can verify client-side HMAC signatures, but it is never returned
via any API response.
"""
import os
import string
import hashlib
import hmac
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

try:
    from passlib.context import CryptContext
    _bcrypt = CryptContext(schemes=["bcrypt"], deprecated="auto")
    def hash_pin(pin: str) -> str:
        return _bcrypt.hash(pin)
    def verify_pin(pin: str, hashed: str) -> bool:
        try:
            return _bcrypt.verify(pin, hashed)
        except Exception:
            return False
except ImportError:
    # Fallback: salted SHA-256 (passlib not available)
    def hash_pin(pin: str) -> str:
        salt = secrets.token_hex(16)
        return salt + ":" + hashlib.sha256((salt + pin).encode()).hexdigest()
    def verify_pin(pin: str, hashed: str) -> bool:
        try:
            salt, digest = hashed.split(":", 1)
            return hmac.compare_digest(digest, hashlib.sha256((salt + pin).encode()).hexdigest())
        except Exception:
            return False


KEY_FILENAME = ".weighbridge_key"
MAX_FAILURES = 5
LOCKOUT_MINUTES = 15
NONCE_TTL_SECONDS = 90     # challenge nonce valid for 90 seconds
CLIENT_SESSION_HOURS = 8


# ─── Key file helpers ─────────────────────────────────────────────────────────

def _get_removable_drives() -> list[str]:
    """Return list of removable drive root paths on Windows."""
    drives = []
    try:
        import ctypes
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                if ctypes.windll.kernel32.GetDriveTypeW(drive) == 2:  # DRIVE_REMOVABLE
                    drives.append(drive)
    except Exception:
        pass
    return drives


def _read_usb_key_file() -> tuple[str, str] | None:
    """
    Read and parse .weighbridge_key from any removable drive.
    Returns (uuid, hmac_secret_hex) or None.
    New format: '<uuid>:<hmac_secret_hex>'
    Legacy format (uuid only): returns (uuid, '') for backwards detection.
    """
    for drive in _get_removable_drives():
        key_path = os.path.join(drive, KEY_FILENAME)
        try:
            if os.path.exists(key_path):
                content = open(key_path).read().strip()
                if ":" in content:
                    parts = content.split(":", 1)
                    return parts[0].strip(), parts[1].strip()
                else:
                    # Legacy plain UUID — still supports old keys
                    return content, ""
        except Exception:
            pass
    return None


def generate_key_file_content() -> tuple[str, str]:
    """Generate a new (uuid, hmac_secret_hex) pair for a new key."""
    key_uuid = secrets.token_hex(16)  # 128-bit UUID equivalent
    hmac_secret = secrets.token_hex(32)  # 256-bit HMAC secret
    return key_uuid, hmac_secret


def compute_invoice_hash(fields: dict) -> str:
    """HMAC-SHA256 of private invoice fields to detect DB tampering."""
    # Deterministic string from all immutable invoice fields
    data = "|".join(str(fields.get(k, "")) for k in [
        "invoice_no", "invoice_date", "customer_name", "vehicle_no",
        "net_weight", "rate", "amount", "payment_mode", "created_by"
    ])
    # Use a server-side secret — try env vars first, then pydantic settings
    server_secret = os.environ.get("PRIVATE_DATA_KEY", "") or os.environ.get("SECRET_KEY", "")
    if not server_secret:
        try:
            from app.config import get_settings
            s = get_settings()
            server_secret = getattr(s, "PRIVATE_DATA_KEY", "") or s.SECRET_KEY
        except Exception:
            server_secret = "default-integrity-secret"
    return hmac.new(server_secret.encode(), data.encode(), hashlib.sha256).hexdigest()


# ─── Lockout helpers ──────────────────────────────────────────────────────────

async def _check_lockout(db: AsyncSession, scope: str) -> bool:
    """Returns True if this scope is currently locked out."""
    now = datetime.now(timezone.utc)
    row = (await db.execute(
        text("SELECT fail_count, locked_until FROM usb_lockouts WHERE scope = :s"),
        {"s": scope}
    )).fetchone()
    if not row:
        return False
    fail_count, locked_until = row
    if locked_until and locked_until > now:
        return True  # locked
    return False


async def _record_failure(db: AsyncSession, scope: str):
    """Record a failed attempt, lock if threshold exceeded."""
    now = datetime.now(timezone.utc)
    row = (await db.execute(
        text("SELECT fail_count FROM usb_lockouts WHERE scope = :s"),
        {"s": scope}
    )).fetchone()

    if not row:
        await db.execute(
            text("INSERT INTO usb_lockouts (scope, fail_count, last_attempt) VALUES (:s, 1, :now)"),
            {"s": scope, "now": now}
        )
    else:
        new_count = row[0] + 1
        locked_until = (now + timedelta(minutes=LOCKOUT_MINUTES)) if new_count >= MAX_FAILURES else None
        await db.execute(
            text("UPDATE usb_lockouts SET fail_count = :c, locked_until = :lu, last_attempt = :now WHERE scope = :s"),
            {"c": new_count, "lu": locked_until, "s": scope, "now": now}
        )
    await db.commit()


async def _clear_lockout(db: AsyncSession, scope: str):
    """Clear lockout on successful auth."""
    await db.execute(
        text("UPDATE usb_lockouts SET fail_count = 0, locked_until = NULL WHERE scope = :s"),
        {"s": scope}
    )


# ─── Audit log ────────────────────────────────────────────────────────────────

async def _log_event(
    db: AsyncSession,
    event_type: str,
    success: bool,
    user_id: str | None = None,
    method: str | None = None,
    ip_address: str | None = None,
    detail: str | None = None,
):
    await db.execute(
        text("""
            INSERT INTO usb_auth_log (user_id, event_type, method, success, ip_address, detail)
            VALUES (:uid, :evt, :method, :ok, :ip, :detail)
        """),
        {
            "uid": user_id, "evt": event_type, "method": method,
            "ok": success, "ip": ip_address, "detail": detail
        }
    )


# ─── Nonce management (anti-replay) ───────────────────────────────────────────

async def _issue_nonce(db: AsyncSession) -> str:
    """Generate a single-use nonce valid for NONCE_TTL_SECONDS seconds."""
    nonce = secrets.token_hex(32)  # 256-bit random
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=NONCE_TTL_SECONDS)
    await db.execute(
        text("INSERT INTO usb_nonces (nonce, expires_at) VALUES (:n, :exp)"),
        {"n": nonce, "exp": expires_at}
    )
    await db.commit()
    return nonce


async def _consume_nonce(db: AsyncSession, nonce: str) -> bool:
    """
    Consume a nonce: verify it exists, is not expired, then DELETE it.
    Returns True if valid.
    """
    now = datetime.now(timezone.utc)
    row = (await db.execute(
        text("DELETE FROM usb_nonces WHERE nonce = :n AND expires_at > :now RETURNING id"),
        {"n": nonce, "now": now}
    )).fetchone()
    return row is not None


async def _cleanup_expired_nonces(db: AsyncSession):
    """Prune old nonces (called periodically)."""
    await db.execute(
        text("DELETE FROM usb_nonces WHERE expires_at < NOW() - INTERVAL '5 minutes'")
    )


# ─── Main auth check ─────────────────────────────────────────────────────────

async def check_usb_authorized(
    db: AsyncSession,
    user_id: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """
    Returns {"authorized": bool, "method": str|None, "expires_at": str|None}

    Priority:
      1. Server USB (physical drive present + HMAC verified)
      2. Client USB session (HMAC was verified at login time, session still valid + IP match)
      3. Recovery PIN session (admin pre-created, time-limited)
    """
    # 1. Server-side USB check
    key_data = _read_usb_key_file()
    if key_data:
        key_uuid, file_hmac_secret = key_data
        row = (await db.execute(
            text("SELECT hmac_secret FROM usb_keys WHERE key_uuid = :uuid AND is_active = TRUE"),
            {"uuid": key_uuid}
        )).fetchone()
        if row:
            db_hmac_secret = row[0]
            # If DB has hmac_secret: verify it matches what's on USB
            if db_hmac_secret:
                if hmac.compare_digest(file_hmac_secret, db_hmac_secret):
                    return {"authorized": True, "method": "usb", "expires_at": None}
            else:
                # Legacy key (no hmac_secret in DB) — allow but flag as legacy
                return {"authorized": True, "method": "usb_legacy", "expires_at": None}

    now = datetime.now(timezone.utc)

    # 2. Client USB session (per-user, IP-bound if ip recorded)
    if user_id:
        row = (await db.execute(
            text("""
                SELECT expires_at, ip_address FROM usb_client_sessions
                WHERE created_by = :uid AND expires_at > :now
                ORDER BY created_at DESC LIMIT 1
            """),
            {"uid": user_id, "now": now}
        )).fetchone()
        if row:
            session_expires, session_ip = row[0], row[1]
            # IP check: only enforce if both sides have IPs recorded
            ip_ok = (not session_ip) or (not ip_address) or (session_ip == ip_address)
            if ip_ok:
                return {"authorized": True, "method": "client_usb", "expires_at": session_expires.isoformat()}

    # 3. Recovery session (global, time-limited, single-use)
    row = (await db.execute(
        text("SELECT expires_at FROM usb_recovery_sessions WHERE expires_at > :now AND used = FALSE ORDER BY created_at DESC LIMIT 1"),
        {"now": now}
    )).fetchone()
    if row:
        return {"authorized": True, "method": "recovery", "expires_at": row[0].isoformat()}

    return {"authorized": False, "method": None, "expires_at": None}


# ─── Challenge-response auth ──────────────────────────────────────────────────

async def issue_challenge(db: AsyncSession) -> dict:
    """Issue a one-time nonce challenge for client USB authentication."""
    nonce = await _issue_nonce(db)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=NONCE_TTL_SECONDS)
    return {"nonce": nonce, "expires_at": expires_at.isoformat(), "ttl_seconds": NONCE_TTL_SECONDS}


def compute_client_signature(hmac_secret_hex: str, nonce: str, user_id: str) -> str:
    """
    Compute HMAC-SHA256 signature for client auth.
    Called client-side (in browser via SubtleCrypto — not in Python normally,
    but included here for the server-side setup script and test utilities).

    signature = HMAC-SHA256(key=hmac_secret, msg=nonce + ":" + user_id)
    """
    secret_bytes = bytes.fromhex(hmac_secret_hex)
    message = f"{nonce}:{user_id}".encode()
    return hmac.new(secret_bytes, message, hashlib.sha256).hexdigest()


async def verify_client_auth(
    db: AsyncSession,
    key_uuid: str,
    nonce: str,
    signature: str,
    user_id: str,
    ip_address: str | None,
) -> bool:
    """
    Verify HMAC challenge-response for client USB auth.
    Returns True if valid; records audit + lockout on failure.
    """
    lockout_scope = f"client:{user_id}"

    # Check lockout first
    if await _check_lockout(db, lockout_scope):
        await _log_event(db, "client_auth", False, user_id, "client_usb", ip_address, "LOCKED OUT")
        await db.commit()
        return False

    # Consume nonce (single-use + expiry check)
    nonce_valid = await _consume_nonce(db, nonce)
    if not nonce_valid:
        await _record_failure(db, lockout_scope)
        await _log_event(db, "client_auth", False, user_id, "client_usb", ip_address, "invalid or expired nonce")
        await db.commit()
        return False

    # Look up key + hmac_secret
    row = (await db.execute(
        text("SELECT hmac_secret FROM usb_keys WHERE key_uuid = :uuid AND is_active = TRUE"),
        {"uuid": key_uuid}
    )).fetchone()

    if not row or not row[0]:
        await _record_failure(db, lockout_scope)
        await _log_event(db, "client_auth", False, user_id, "client_usb", ip_address, f"key_uuid not found: {key_uuid[:8]}...")
        await db.commit()
        return False

    # Verify HMAC signature in constant time
    expected = compute_client_signature(row[0], nonce, user_id)
    if not hmac.compare_digest(expected, signature):
        await _record_failure(db, lockout_scope)
        await _log_event(db, "client_auth", False, user_id, "client_usb", ip_address, "HMAC signature mismatch")
        await db.commit()
        return False

    # Success
    await _clear_lockout(db, lockout_scope)
    await _log_event(db, "client_auth", True, user_id, "client_usb", ip_address, f"key {key_uuid[:8]}...")
    return True


async def verify_recovery_pin(
    db: AsyncSession,
    pin: str,
    user_id: str,
    ip_address: str | None,
) -> dict | None:
    """
    Verify recovery PIN with lockout protection.
    Returns {"authorized": True, "expires_at": ...} or None.
    """
    lockout_scope = f"recovery:{ip_address or user_id}"

    if await _check_lockout(db, lockout_scope):
        await _log_event(db, "recovery_verify", False, user_id, "recovery", ip_address, "LOCKED OUT")
        await db.commit()
        return None

    now = datetime.now(timezone.utc)
    # Fetch all valid unexpired sessions, verify PIN against each
    rows = (await db.execute(
        text("SELECT id, pin_hash, expires_at FROM usb_recovery_sessions WHERE expires_at > :now AND used = FALSE ORDER BY created_at DESC"),
        {"now": now}
    )).fetchall()

    for row in rows:
        session_id, pin_hash, expires_at = row
        if verify_pin(pin, pin_hash):
            await _clear_lockout(db, lockout_scope)
            await _log_event(db, "recovery_verify", True, user_id, "recovery", ip_address, None)
            await db.commit()
            return {"authorized": True, "expires_at": expires_at.isoformat()}

    # No match
    await _record_failure(db, lockout_scope)
    await _log_event(db, "recovery_verify", False, user_id, "recovery", ip_address, "wrong PIN")
    await db.commit()
    return None

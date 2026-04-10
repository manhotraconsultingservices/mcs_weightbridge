"""
USB Guard router — hardened authentication endpoints.

Auth flow (client USB):
  1. GET  /challenge             → server returns {nonce, expires_at}
  2. Client computes signature = HMAC-SHA256(usb_secret, nonce + ":" + user_id)
  3. POST /client-auth           → {key_uuid, nonce, signature} → session created

Recovery flow:
  Admin creates PIN via POST /recovery/create
  User enters PIN via POST /recovery/verify (rate-limited, bcrypt)
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.services.usb_guard import (
    check_usb_authorized, hash_pin, verify_pin,
    issue_challenge, verify_client_auth, verify_recovery_pin,
    CLIENT_SESSION_HOURS, MAX_FAILURES, LOCKOUT_MINUTES, NONCE_TTL_SECONDS,
    _log_event,
)

router = APIRouter(prefix="/api/v1/usb-guard", tags=["USB Guard"])


def _get_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ─── Status ───────────────────────────────────────────────────────────────────

class UsbStatusResponse(BaseModel):
    authorized: bool
    method: str | None
    expires_at: str | None


@router.get("/status", response_model=UsbStatusResponse)
async def usb_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await check_usb_authorized(db, user_id=str(current_user.id), ip_address=_get_ip(request))
    return UsbStatusResponse(**result)


# ─── Key registration (admin only) ───────────────────────────────────────────

class RegisterKeyRequest(BaseModel):
    key_uuid: str
    hmac_secret: str = ""       # 64-char hex; empty = legacy support
    label: str = "Primary Key"


@router.post("/register-key", status_code=201)
async def register_key(
    payload: RegisterKeyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Register a USB key (UUID + HMAC secret) into the database."""
    await db.execute(
        text("""
            INSERT INTO usb_keys (key_uuid, hmac_secret, label)
            VALUES (:uuid, :secret, :label)
            ON CONFLICT (key_uuid) DO UPDATE
            SET is_active = TRUE, label = :label,
                hmac_secret = COALESCE(NULLIF(:secret, ''), usb_keys.hmac_secret)
        """),
        {"uuid": payload.key_uuid, "secret": payload.hmac_secret or None, "label": payload.label}
    )
    await db.commit()
    return {"message": "Key registered"}


@router.get("/keys")
async def list_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    rows = (await db.execute(
        text("SELECT id, key_uuid, label, is_active, created_at, (hmac_secret IS NOT NULL) as has_secret FROM usb_keys ORDER BY created_at DESC")
    )).fetchall()
    return [
        {
            "id": str(r[0]),
            "key_uuid": r[1],
            "label": r[2],
            "is_active": r[3],
            "created_at": str(r[4]),
            "is_hardened": r[5],   # True if HMAC secret is set (new-style key)
        }
        for r in rows
    ]


@router.post("/keys/{key_uuid}/deactivate")
async def deactivate_key(
    key_uuid: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await db.execute(
        text("UPDATE usb_keys SET is_active = FALSE WHERE key_uuid = :uuid"),
        {"uuid": key_uuid}
    )
    await db.commit()
    return {"message": "Key deactivated"}


# ─── Challenge-response (client USB) ─────────────────────────────────────────

@router.get("/challenge")
async def get_challenge(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Issue a one-time nonce for HMAC challenge-response authentication.
    The client must compute:
      signature = HMAC-SHA256(key=usb_hmac_secret, msg=nonce + ':' + user_id)
    and send it to POST /client-auth within the TTL window.
    """
    challenge = await issue_challenge(db)
    challenge["user_id"] = str(current_user.id)
    return challenge


class ClientAuthRequest(BaseModel):
    key_uuid: str
    nonce: str
    signature: str          # HMAC-SHA256 hex


@router.post("/client-auth", status_code=201)
async def client_auth(
    payload: ClientAuthRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Authenticate via HMAC challenge-response.
    Requires the USB key's HMAC secret (only on the physical drive).
    """
    ip = _get_ip(request)
    ok = await verify_client_auth(
        db,
        key_uuid=payload.key_uuid,
        nonce=payload.nonce,
        signature=payload.signature,
        user_id=str(current_user.id),
        ip_address=ip,
    )
    if not ok:
        raise HTTPException(403, "USB authentication failed. Check key, or wait if locked out.")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=CLIENT_SESSION_HOURS)
    await db.execute(
        text("""
            INSERT INTO usb_client_sessions (key_uuid, created_by, expires_at, ip_address)
            VALUES (:uuid, :uid, :exp, :ip)
        """),
        {"uuid": payload.key_uuid, "uid": str(current_user.id), "exp": expires_at, "ip": ip}
    )
    await db.commit()
    return {
        "authorized": True,
        "method": "client_usb",
        "expires_at": expires_at.isoformat(),
        "session_hours": CLIENT_SESSION_HOURS,
    }


# ─── Recovery PIN ─────────────────────────────────────────────────────────────

class RecoveryRequest(BaseModel):
    pin: str
    hours: int = 24
    reason: str = ""


class RecoveryVerifyRequest(BaseModel):
    pin: str


@router.post("/recovery/create", status_code=201)
async def create_recovery(
    payload: RecoveryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Admin pre-creates a recovery PIN (bcrypt hashed, time-limited)."""
    if len(payload.pin) < 8:
        raise HTTPException(400, "PIN must be at least 8 characters for security")
    if payload.hours > 72:
        raise HTTPException(400, "Recovery session cannot exceed 72 hours")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.hours)
    pin_hash = hash_pin(payload.pin)   # bcrypt (salted, slow)

    await db.execute(
        text("""
            INSERT INTO usb_recovery_sessions (pin_hash, expires_at, created_by, reason)
            VALUES (:ph, :exp, :uid, :reason)
        """),
        {"ph": pin_hash, "exp": expires_at, "uid": str(current_user.id), "reason": payload.reason}
    )
    await db.commit()
    return {
        "message": f"Recovery PIN created, valid for {payload.hours} hours",
        "expires_at": expires_at.isoformat(),
        "warning": "Share this PIN only with the authorised person. It expires automatically."
    }


@router.post("/recovery/verify")
async def verify_recovery(
    payload: RecoveryVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Verify a recovery PIN.
    Rate-limited: {MAX_FAILURES} attempts per IP, then {LOCKOUT_MINUTES}-min lockout.
    """
    ip = _get_ip(request)
    result = await verify_recovery_pin(db, payload.pin, str(current_user.id), ip)
    if not result:
        raise HTTPException(
            403,
            f"Invalid PIN or too many failed attempts. "
            f"After {MAX_FAILURES} failures the system locks for {LOCKOUT_MINUTES} minutes."
        )
    return result


# ─── Revoke session ───────────────────────────────────────────────────────────

@router.post("/revoke-session")
async def revoke_session(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke all active USB sessions for the current user (client USB + recovery). Called on pendrive removal or Lock button."""
    # Revoke client USB sessions
    await db.execute(
        text("DELETE FROM usb_client_sessions WHERE created_by = :uid"),
        {"uid": str(current_user.id)}
    )
    # Also revoke any active recovery sessions (so Lock button works for recovery sessions too)
    await db.execute(
        text("DELETE FROM usb_recovery_sessions WHERE created_by = :uid AND expires_at > now()"),
        {"uid": str(current_user.id)}
    )
    await _log_event(db, "session_revoked", True, str(current_user.id), "any", None, "user revoked session (client+recovery)")
    await db.commit()
    return {"message": "Session revoked"}


# ─── Auth log (admin view) ────────────────────────────────────────────────────

@router.get("/auth-log")
async def auth_log(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """View recent USB authentication events (successes + failures)."""
    rows = (await db.execute(
        text("""
            SELECT l.event_type, l.method, l.success, l.ip_address, l.detail,
                   l.created_at, u.username
            FROM usb_auth_log l
            LEFT JOIN users u ON u.id = l.user_id
            ORDER BY l.created_at DESC LIMIT :lim
        """),
        {"lim": limit}
    )).fetchall()
    return [
        {
            "event_type": r[0], "method": r[1], "success": r[2],
            "ip_address": r[3], "detail": r[4],
            "created_at": str(r[5]), "username": r[6],
        }
        for r in rows
    ]

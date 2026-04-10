import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.schemas.auth import (
    LoginRequest, TokenResponse, UserCreate, UserUpdate,
    UserResponse, ChangePasswordRequest, AdminResetPasswordRequest,
)
from app.utils.auth import hash_password, verify_password, create_access_token

router = APIRouter()


# ── Constants ─────────────────────────────────────────────────────────────────
_LOCKOUT_THRESHOLD = 5          # failed attempts before lockout
_LOCKOUT_MINUTES   = 15         # lockout duration
_LOCKOUT_WINDOW    = 30         # minutes window to count failures in

from fastapi import Request
from sqlalchemy import text as _sql

@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    client_ip = (request.client.host if request.client else "unknown")
    scope     = f"ip:{client_ip}"
    now       = datetime.now(timezone.utc)

    # ── 1. Check lockout ─────────────────────────────────────────────────────
    lockout_row = (await db.execute(
        _sql("SELECT locked_until, fail_count FROM login_lockouts WHERE scope = :s"),
        {"s": scope},
    )).fetchone()

    if lockout_row and lockout_row[0] and lockout_row[0].replace(tzinfo=timezone.utc) > now:
        remaining = int((lockout_row[0].replace(tzinfo=timezone.utc) - now).total_seconds() / 60) + 1
        await db.execute(
            _sql("INSERT INTO login_audit (username, ip_address, success, detail) VALUES (:u, :ip, FALSE, :d)"),
            {"u": form_data.username, "ip": client_ip, "d": f"Blocked — lockout active ({remaining} min remaining)"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Account locked for {remaining} more minute(s).",
        )

    # ── 2. Look up user ──────────────────────────────────────────────────────
    result = await db.execute(select(User).where(User.username == form_data.username))
    user   = result.scalar_one_or_none()

    # ── 3. Verify password ───────────────────────────────────────────────────
    password_ok = user is not None and verify_password(form_data.password, user.password_hash)

    if not password_ok:
        # Record failure — upsert into lockouts table
        await db.execute(
            _sql("""
                INSERT INTO login_lockouts (scope, fail_count, last_attempt, locked_until)
                VALUES (:s, 1, NOW(), NULL)
                ON CONFLICT (scope) DO UPDATE SET
                    fail_count   = login_lockouts.fail_count + 1,
                    last_attempt = NOW(),
                    locked_until = CASE
                        WHEN login_lockouts.fail_count + 1 >= :thresh
                        THEN NOW() + INTERVAL '15 minutes'
                        ELSE login_lockouts.locked_until
                    END
            """),
            {"s": scope, "thresh": _LOCKOUT_THRESHOLD},
        )
        await db.execute(
            _sql("INSERT INTO login_audit (username, ip_address, success, detail) VALUES (:u, :ip, FALSE, 'Invalid credentials')"),
            {"u": form_data.username, "ip": client_ip},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not user.is_active:
        await db.execute(
            _sql("INSERT INTO login_audit (username, ip_address, user_id, success, detail) VALUES (:u, :ip, :uid, FALSE, 'Account disabled')"),
            {"u": form_data.username, "ip": client_ip, "uid": str(user.id)},
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    # ── 4. Success — clear lockout, write audit, issue token ─────────────────
    await db.execute(_sql("DELETE FROM login_lockouts WHERE scope = :s"), {"s": scope})
    await db.execute(
        _sql("INSERT INTO login_audit (username, ip_address, user_id, success) VALUES (:u, :ip, :uid, TRUE)"),
        {"u": form_data.username, "ip": client_ip, "uid": str(user.id)},
    )
    user.last_login = now
    await db.commit()

    token = create_access_token(data={"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.put("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(req.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.password_hash = hash_password(req.new_password)
    await db.commit()
    return {"message": "Password changed successfully"}


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.company_id == current_user.company_id).order_by(User.full_name)
    )
    return [UserResponse.model_validate(u) for u in result.scalars().all()]


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    data: UserCreate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    user = User(
        company_id=current_user.company_id,
        username=data.username,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
        role=data.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id, User.company_id == current_user.company_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.put("/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: uuid.UUID,
    data: AdminResetPasswordRequest,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Admin resets another user's password without needing the current password."""
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    result = await db.execute(select(User).where(User.id == user_id, User.company_id == current_user.company_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password_hash = hash_password(data.new_password)
    await db.commit()
    return {"message": "Password reset successfully"}


@router.get("/login-audit")
async def get_login_audit(
    page: int = 1,
    page_size: int = 50,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Admin endpoint: view login audit log (success + failures)."""
    offset = (page - 1) * page_size
    total = (await db.execute(_sql("SELECT COUNT(*) FROM login_audit"))).scalar() or 0
    rows = (await db.execute(
        _sql("SELECT id, username, user_id, ip_address, success, detail, created_at FROM login_audit ORDER BY created_at DESC LIMIT :lim OFFSET :off"),
        {"lim": page_size, "off": offset},
    )).fetchall()
    return {
        "items": [
            {
                "id": str(r[0]), "username": r[1], "user_id": str(r[2]) if r[2] else None,
                "ip_address": r[3], "success": r[4], "detail": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
            }
            for r in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }

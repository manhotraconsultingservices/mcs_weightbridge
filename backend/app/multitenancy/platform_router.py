"""Platform Admin API — internal portal for Manhotra Consulting staff.

Endpoints for platform_admin and sales_rep users to manage tenants,
view customer dashboards, and configure platform branding.

JWT tokens for platform users have {platform: true} claim to
distinguish from tenant user tokens.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select, text, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.multitenancy.master_db import get_master_db
from app.multitenancy.models import Tenant
from app.multitenancy.platform_models import PlatformUser, TenantSalesRep, PlatformBranding
from app.schemas.platform import (
    PlatformUserCreate, PlatformUserUpdate, PlatformUserResponse,
    PlatformLoginRequest, PlatformTokenResponse,
    PlatformBrandingResponse, PlatformBrandingUpdate,
    TenantOverview, TenantListResponse, SalesRepBrief, SalesRepAssign,
    PasswordReset,
)
from app.schemas.tenant import TenantCreate, TenantCreateResponse, TenantUpdate, TenantResponse
from app.utils.auth import create_access_token

logger = logging.getLogger(__name__)
router = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Auth Dependencies ─────────────────────────────────────────────────────────

async def get_current_platform_user(
    token: str = Depends(
        __import__("fastapi.security", fromlist=["OAuth2PasswordBearer"]).OAuth2PasswordBearer(
            tokenUrl="/api/v1/platform/auth/login", auto_error=True
        )
    ),
    db: AsyncSession = Depends(get_master_db),
) -> PlatformUser:
    """Decode JWT, verify {platform: true}, return PlatformUser."""
    from jose import jwt, JWTError
    settings = get_settings()

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate platform credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if not payload.get("platform"):
            raise credentials_exception
        user_id = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(
        select(PlatformUser).where(PlatformUser.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise credentials_exception
    return user


def require_platform_role(*roles: str):
    """Dependency factory that checks platform user's role."""
    async def _guard(user: PlatformUser = Depends(get_current_platform_user)):
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient platform privileges")
        return user
    return _guard


# ── Platform Auth ─────────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=PlatformTokenResponse)
async def platform_login(
    payload: PlatformLoginRequest,
    db: AsyncSession = Depends(get_master_db),
):
    """Authenticate a platform user (platform_admin or sales_rep)."""
    result = await db.execute(
        select(PlatformUser).where(PlatformUser.username == payload.username)
    )
    user = result.scalar_one_or_none()

    if not user or not pwd_ctx.verify(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")

    token = create_access_token(data={
        "sub": str(user.id),
        "platform": True,
        "role": user.role,
    })

    return PlatformTokenResponse(
        access_token=token,
        user=PlatformUserResponse(
            id=user.id, username=user.username, full_name=user.full_name,
            email=user.email, phone=user.phone, role=user.role,
            is_active=user.is_active, created_at=user.created_at, updated_at=user.updated_at,
        ),
    )


@router.get("/auth/me", response_model=PlatformUserResponse)
async def platform_me(
    user: PlatformUser = Depends(get_current_platform_user),
):
    """Return current platform user info."""
    return PlatformUserResponse(
        id=user.id, username=user.username, full_name=user.full_name,
        email=user.email, phone=user.phone, role=user.role,
        is_active=user.is_active, created_at=user.created_at, updated_at=user.updated_at,
    )


# ── Tenant Management (platform_admin only) ──────────────────────────────────

async def _build_tenant_overview(db: AsyncSession, tenant: Tenant) -> TenantOverview:
    """Build TenantOverview with sales rep assignments."""
    reps_result = await db.execute(text("""
        SELECT pu.id, pu.username, pu.full_name, pu.email
        FROM tenant_sales_reps tsr
        JOIN platform_users pu ON pu.id = tsr.platform_user_id
        WHERE tsr.tenant_id = :tid
        ORDER BY pu.full_name
    """), {"tid": str(tenant.id)})
    reps = [
        SalesRepBrief(id=r[0], username=r[1], full_name=r[2], email=r[3])
        for r in reps_result.fetchall()
    ]
    return TenantOverview(
        id=tenant.id, slug=tenant.slug, display_name=tenant.display_name,
        db_name=tenant.db_name, is_active=tenant.is_active,
        status=getattr(tenant, "status", "active"),
        amc_start_date=getattr(tenant, "amc_start_date", None),
        amc_expiry_date=getattr(tenant, "amc_expiry_date", None),
        logo_url=getattr(tenant, "logo_url", None),
        contact_email=getattr(tenant, "contact_email", None),
        contact_phone=getattr(tenant, "contact_phone", None),
        agent_api_key=tenant.agent_api_key, config=tenant.config,
        created_at=tenant.created_at, updated_at=tenant.updated_at,
        sales_reps=reps,
    )


@router.get("/tenants", response_model=TenantListResponse)
async def list_tenants(
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin", "sales_rep")),
):
    """List tenants. Platform admins see all; sales reps see only assigned."""
    if user.role == "platform_admin":
        result = await db.execute(select(Tenant).order_by(Tenant.display_name))
        tenants = list(result.scalars().all())
    else:
        # Sales rep — only assigned tenants
        result = await db.execute(text("""
            SELECT t.* FROM tenants t
            JOIN tenant_sales_reps tsr ON tsr.tenant_id = t.id
            WHERE tsr.platform_user_id = :uid
            ORDER BY t.display_name
        """), {"uid": str(user.id)})
        rows = result.fetchall()
        # Reconstruct Tenant objects from rows
        tenants = []
        for r in rows:
            t = Tenant()
            for col in r._mapping:
                setattr(t, col, r._mapping[col])
            tenants.append(t)

    overviews = []
    for t in tenants:
        overviews.append(await _build_tenant_overview(db, t))

    return TenantListResponse(tenants=overviews, total=len(overviews))


@router.get("/tenants/{slug}")
async def get_tenant(
    slug: str,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin", "sales_rep")),
):
    """Get single tenant detail."""
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    # Sales reps can only view assigned tenants
    if user.role == "sales_rep":
        assigned = (await db.execute(text(
            "SELECT 1 FROM tenant_sales_reps WHERE tenant_id = :tid AND platform_user_id = :uid"
        ), {"tid": str(tenant.id), "uid": str(user.id)})).fetchone()
        if not assigned:
            raise HTTPException(403, "Not assigned to this tenant")

    return await _build_tenant_overview(db, tenant)


@router.post("/tenants", response_model=TenantCreateResponse)
async def create_tenant(
    payload: TenantCreate,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Onboard a new company: create database, run DDL, seed data."""
    # Reuse existing tenant creation logic from the admin router
    from app.multitenancy.router import _create_database, _run_tenant_ddl, _seed_tenant_data
    from app.multitenancy.registry import tenant_registry

    settings = get_settings()
    slug = payload.slug
    db_slug = slug.replace("-", "_")  # PG db names can't have hyphens
    db_name = f"{settings.TENANT_DB_PREFIX}{db_slug}"

    # Check uniqueness
    existing = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Tenant '{slug}' already exists")

    # 1. Create PostgreSQL database
    await _create_database(db_name, settings)

    # 2. Register in master DB
    tenant = Tenant(
        slug=slug,
        display_name=payload.display_name,
        db_name=db_name,
        is_active=True,
        status="active",
        agent_api_key=str(uuid.uuid4()),
        amc_start_date=payload.amc_start_date,
        amc_expiry_date=payload.amc_expiry_date,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    # 3. Run DDL migrations
    await _run_tenant_ddl(slug)

    # 4. Seed default data
    await _seed_tenant_data(slug, payload)

    logger.info("Platform admin %s onboarded tenant: %s", user.username, slug)

    return TenantCreateResponse(
        tenant=TenantResponse(
            id=tenant.id, slug=tenant.slug, display_name=tenant.display_name,
            db_name=tenant.db_name, is_active=tenant.is_active,
            status=tenant.status,
            agent_api_key=tenant.agent_api_key, config=tenant.config,
            amc_start_date=tenant.amc_start_date, amc_expiry_date=tenant.amc_expiry_date,
            logo_url=tenant.logo_url, contact_email=tenant.contact_email,
            contact_phone=tenant.contact_phone,
            created_at=tenant.created_at, updated_at=tenant.updated_at,
        ),
        admin_username=payload.admin_username,
        message=f"Tenant '{slug}' created successfully",
    )


@router.put("/tenants/{slug}")
async def update_tenant(
    slug: str,
    payload: TenantUpdate,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Update tenant settings (status, AMC, logo, etc.)."""
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    updates = payload.model_dump(exclude_unset=True)
    # `industry` is not a column — it lives in config JSON. Handle separately.
    industry_val = updates.pop("industry", None)
    # Same treatment: not a column, lives in config JSON.
    restrictions_val = updates.pop("admin_restrictions", None)
    for field, value in updates.items():
        if hasattr(tenant, field):
            setattr(tenant, field, value)
    if industry_val is not None:
        from app.multitenancy.industry import normalize_industry
        from app.multitenancy.middleware import _modules_cache
        cfg = dict(tenant.config or {})
        cfg["industry"] = normalize_industry(industry_val)
        tenant.config = cfg
        _modules_cache.pop(slug, None)   # take effect on next request
    if restrictions_val is not None:
        from app.multitenancy.middleware import _modules_cache
        cfg = dict(tenant.config or {})
        # Normalised + de-duplicated, order preserved so the console shows it back
        # exactly as saved. An empty list clears every restriction.
        seen, clean = set(), []
        for r in restrictions_val:
            r = str(r or "").strip()
            if r and r not in seen:
                seen.add(r); clean.append(r)
        cfg["admin_restrictions"] = clean
        tenant.config = cfg
        _modules_cache.pop(slug, None)

    # Keep is_active in sync with status
    if "status" in updates:
        tenant.is_active = updates["status"] != "suspended"

    await db.commit()
    await db.refresh(tenant)

    logger.info("Platform admin %s updated tenant %s: %s", user.username, slug, list(updates.keys()))
    return await _build_tenant_overview(db, tenant)


# ── Module Config (Feature Gating) ────────────────────────────────────────────

@router.get("/tenants/{slug}/modules")
async def get_tenant_modules(
    slug: str,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Get tenant module flags (merged with defaults)."""
    from app.routers.auth import DEFAULT_MODULES

    tenant = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    from app.multitenancy.industry import industry_modules, normalize_industry
    config = tenant.config or {}
    saved_modules = config.get("modules", {})
    industry = normalize_industry(config.get("industry"))
    # Reflect the industry preset so the panel shows what the tenant actually sees.
    resolved = {**DEFAULT_MODULES, **industry_modules(industry), **saved_modules}
    return {"slug": slug, "modules": resolved, "industry": industry}


@router.put("/tenants/{slug}/modules")
async def update_tenant_modules(
    slug: str,
    payload: dict,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Update tenant module flags. Accepts {module_key: bool, ...}."""
    from app.routers.auth import DEFAULT_MODULES
    from app.multitenancy.middleware import _modules_cache

    tenant = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    # Validate all keys are known modules
    for key in payload:
        if key not in DEFAULT_MODULES:
            raise HTTPException(400, f"Unknown module: {key}")

    # Merge into existing config
    config = dict(tenant.config or {})
    config["modules"] = {**config.get("modules", {}), **payload}
    tenant.config = config

    await db.commit()
    await db.refresh(tenant)

    # Invalidate middleware cache so changes take effect immediately
    _modules_cache.pop(slug, None)

    resolved = {**DEFAULT_MODULES, **config.get("modules", {})}
    logger.info("Platform admin %s updated modules for %s: %s", user.username, slug, payload)
    return {"slug": slug, "modules": resolved}


# ── Sales Rep Assignment ──────────────────────────────────────────────────────

@router.post("/tenants/{slug}/assign-rep")
async def assign_sales_rep(
    slug: str,
    payload: SalesRepAssign,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Assign a sales rep to a tenant."""
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    platform_user = (await db.execute(
        select(PlatformUser).where(PlatformUser.id == payload.platform_user_id)
    )).scalar_one_or_none()
    if not platform_user:
        raise HTTPException(404, "Platform user not found")

    # Check if already assigned
    existing = (await db.execute(text(
        "SELECT 1 FROM tenant_sales_reps WHERE tenant_id = :tid AND platform_user_id = :uid"
    ), {"tid": str(tenant.id), "uid": str(payload.platform_user_id)})).fetchone()
    if existing:
        raise HTTPException(409, "Sales rep already assigned to this tenant")

    assignment = TenantSalesRep(tenant_id=tenant.id, platform_user_id=payload.platform_user_id)
    db.add(assignment)
    await db.commit()

    logger.info("Assigned sales rep %s to tenant %s", platform_user.username, slug)
    return {"message": f"Sales rep '{platform_user.username}' assigned to '{slug}'"}


@router.delete("/tenants/{slug}/reps/{platform_user_id}")
async def remove_sales_rep(
    slug: str,
    platform_user_id: uuid.UUID,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Remove a sales rep assignment from a tenant."""
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    result = await db.execute(
        delete(TenantSalesRep).where(
            TenantSalesRep.tenant_id == tenant.id,
            TenantSalesRep.platform_user_id == platform_user_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Assignment not found")
    await db.commit()

    return {"message": "Sales rep removed from tenant"}


# ── Platform User Management (platform_admin only) ───────────────────────────

@router.get("/users", response_model=list[PlatformUserResponse])
async def list_platform_users(
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """List all platform users."""
    result = await db.execute(select(PlatformUser).order_by(PlatformUser.full_name))
    users = result.scalars().all()
    return [
        PlatformUserResponse(
            id=u.id, username=u.username, full_name=u.full_name,
            email=u.email, phone=u.phone, role=u.role,
            is_active=u.is_active, created_at=u.created_at, updated_at=u.updated_at,
        )
        for u in users
    ]


@router.post("/users", response_model=PlatformUserResponse, status_code=201)
async def create_platform_user(
    payload: PlatformUserCreate,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Create a new platform user (platform_admin or sales_rep)."""
    existing = (await db.execute(
        select(PlatformUser).where(PlatformUser.username == payload.username)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Username '{payload.username}' already exists")

    new_user = PlatformUser(
        username=payload.username,
        password_hash=pwd_ctx.hash(payload.password),
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        role=payload.role,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info("Platform admin %s created user: %s (%s)", user.username, payload.username, payload.role)
    return PlatformUserResponse(
        id=new_user.id, username=new_user.username, full_name=new_user.full_name,
        email=new_user.email, phone=new_user.phone, role=new_user.role,
        is_active=new_user.is_active, created_at=new_user.created_at, updated_at=new_user.updated_at,
    )


@router.put("/users/{user_id}", response_model=PlatformUserResponse)
async def update_platform_user(
    user_id: uuid.UUID,
    payload: PlatformUserUpdate,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Update a platform user."""
    target = (await db.execute(
        select(PlatformUser).where(PlatformUser.id == user_id)
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if hasattr(target, field):
            setattr(target, field, value)
    await db.commit()
    await db.refresh(target)

    return PlatformUserResponse(
        id=target.id, username=target.username, full_name=target.full_name,
        email=target.email, phone=target.phone, role=target.role,
        is_active=target.is_active, created_at=target.created_at, updated_at=target.updated_at,
    )


@router.put("/users/{user_id}/reset-password")
async def reset_platform_user_password(
    user_id: uuid.UUID,
    payload: PasswordReset,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Reset a platform user's password."""
    target = (await db.execute(
        select(PlatformUser).where(PlatformUser.id == user_id)
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found")

    target.password_hash = pwd_ctx.hash(payload.new_password)
    await db.commit()
    return {"message": f"Password reset for '{target.username}'"}


# ── Platform Branding ─────────────────────────────────────────────────────────

@router.get("/branding", response_model=PlatformBrandingResponse)
async def get_branding(
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Get platform branding settings."""
    row = (await db.execute(
        text("SELECT company_name, website, email, logo_url FROM platform_branding WHERE id = 1")
    )).fetchone()
    if row:
        return PlatformBrandingResponse(
            company_name=row[0], website=row[1], email=row[2], logo_url=row[3],
        )
    return PlatformBrandingResponse(company_name="Manhotra Consulting")


@router.put("/branding", response_model=PlatformBrandingResponse)
async def update_branding(
    payload: PlatformBrandingUpdate,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Update platform branding settings."""
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "No fields to update")

    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    updates["now"] = datetime.now(timezone.utc)
    await db.execute(
        text(f"UPDATE platform_branding SET {set_clauses}, updated_at = :now WHERE id = 1"),
        updates,
    )
    await db.commit()

    logger.info("Platform admin %s updated branding: %s", user.username, list(updates.keys()))
    return await get_branding(db=db, user=user)


# ── Telegram messaging usage (platform_admin) ─────────────────────────────────

@router.get("/telegram-stats")
async def telegram_stats(
    days: int = 30,
    db: AsyncSession = Depends(get_master_db),
    _user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Telegram messages per IST day, aggregated across ALL active tenants.

    Each tenant keeps its own ``notification_log``; this fans out to every active
    tenant DB, counts ``channel='telegram'`` rows grouped by IST day + status,
    and aggregates. Returns a gap-filled daily series (oldest→newest) + per-tenant
    totals + KPI roll-ups. A tenant DB that errors (or lacks the table) is skipped.
    """
    from datetime import timedelta
    from app.database import get_tenant_session

    days = max(1, min(int(days or 30), 365))
    IST = timezone(timedelta(hours=5, minutes=30))
    ist_today = datetime.now(IST).date()
    from_date = ist_today - timedelta(days=days - 1)
    from_ts = datetime(from_date.year, from_date.month, from_date.day, tzinfo=IST).astimezone(timezone.utc)

    day_map: dict[str, dict] = {}
    by_tenant: list[dict] = []

    tenants = (await db.execute(
        select(Tenant).where(Tenant.is_active == True).order_by(Tenant.slug)
    )).scalars().all()

    for t in tenants:
        t_sent = t_failed = 0
        try:
            async with await get_tenant_session(t.slug) as tdb:
                rows = (await tdb.execute(text(
                    "SELECT (sent_at AT TIME ZONE 'Asia/Kolkata')::date AS d, "
                    "       COALESCE(status,'') AS st, count(*) AS c "
                    "FROM notification_log "
                    "WHERE lower(channel) = 'telegram' AND sent_at >= :from_ts "
                    "GROUP BY 1, 2"
                ), {"from_ts": from_ts})).all()
            for d, st, c in rows:
                c = int(c or 0)
                m = day_map.setdefault(d.isoformat(), {"sent": 0, "failed": 0})
                if st == "failed":
                    m["failed"] += c; t_failed += c
                else:                       # 'sent' (and any non-failed) → a delivered message
                    m["sent"] += c; t_sent += c
        except Exception as e:
            logger.warning("telegram-stats: tenant %s skipped: %s", t.slug, str(e)[:150])
        if t_sent or t_failed:
            by_tenant.append({
                "slug": t.slug, "name": getattr(t, "display_name", None) or t.slug,
                "sent": t_sent, "failed": t_failed,
            })

    series = []
    total_sent = total_failed = 0
    for i in range(days):
        d = (from_date + timedelta(days=i)).isoformat()
        m = day_map.get(d, {"sent": 0, "failed": 0})
        series.append({"date": d, "sent": m["sent"], "failed": m["failed"], "total": m["sent"] + m["failed"]})
        total_sent += m["sent"]; total_failed += m["failed"]

    by_tenant.sort(key=lambda x: -x["sent"])
    return {
        "days": days,
        "from_date": from_date.isoformat(),
        "to_date": ist_today.isoformat(),
        "series": series,
        "by_tenant": by_tenant,
        "totals": {
            "sent": total_sent,
            "failed": total_failed,
            "today": day_map.get(ist_today.isoformat(), {}).get("sent", 0),
            "last7": sum(x["sent"] for x in series[-7:]),
            "tenants": len(by_tenant),
        },
    }


# ── Sales Rep — My Tenants ────────────────────────────────────────────────────

@router.get("/my-tenants")
async def my_tenants(
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin", "sales_rep")),
):
    """List tenants assigned to the current sales rep. Platform admins see all."""
    if user.role == "platform_admin":
        result = await db.execute(select(Tenant).order_by(Tenant.display_name))
        tenants = list(result.scalars().all())
    else:
        result = await db.execute(text("""
            SELECT t.* FROM tenants t
            JOIN tenant_sales_reps tsr ON tsr.tenant_id = t.id
            WHERE tsr.platform_user_id = :uid
            ORDER BY t.display_name
        """), {"uid": str(user.id)})
        tenants = []
        for r in result.fetchall():
            t = Tenant()
            for col in r._mapping:
                setattr(t, col, r._mapping[col])
            tenants.append(t)

    overviews = []
    for t in tenants:
        overviews.append(await _build_tenant_overview(db, t))

    return {"tenants": overviews, "total": len(overviews)}


@router.get("/my-tenants/{slug}/summary")
async def tenant_summary(
    slug: str,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin", "sales_rep")),
):
    """Read-only dashboard summary for a tenant. Sales reps can only view assigned tenants."""
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    # Verify access for sales reps
    if user.role == "sales_rep":
        assigned = (await db.execute(text(
            "SELECT 1 FROM tenant_sales_reps WHERE tenant_id = :tid AND platform_user_id = :uid"
        ), {"tid": str(tenant.id), "uid": str(user.id)})).fetchone()
        if not assigned:
            raise HTTPException(403, "Not assigned to this tenant")

    # Open a read-only session to the tenant DB for summary stats
    from app.multitenancy.registry import tenant_registry
    factory = await tenant_registry.get_session_factory(slug)
    async with factory() as tenant_db:
        # Basic counts
        users_count = (await tenant_db.execute(text("SELECT COUNT(*) FROM users WHERE is_active = TRUE"))).scalar() or 0
        tokens_today = (await tenant_db.execute(text(
            "SELECT COUNT(*) FROM tokens WHERE token_date = CURRENT_DATE"
        ))).scalar() or 0
        invoices_count = (await tenant_db.execute(text("SELECT COUNT(*) FROM invoices"))).scalar() or 0
        revenue_month = (await tenant_db.execute(text("""
            SELECT COALESCE(SUM(grand_total), 0) FROM invoices
            WHERE invoice_type = 'sale' AND status = 'final'
            AND invoice_date >= date_trunc('month', CURRENT_DATE)
        """))).scalar() or 0

    return {
        "slug": slug,
        "display_name": tenant.display_name,
        "status": getattr(tenant, "status", "active"),
        "amc_expiry_date": str(tenant.amc_expiry_date) if getattr(tenant, "amc_expiry_date", None) else None,
        "stats": {
            "active_users": users_count,
            "tokens_today": tokens_today,
            "total_invoices": invoices_count,
            "revenue_this_month": float(revenue_month),
        },
    }


# ════════════════════════════════════════════════════════════════════════════
#  Tenant data: backup · download · reset
#  Every tenant is its own database, so all three are naturally isolated — none
#  of this can reach another tenant's rows.
# ════════════════════════════════════════════════════════════════════════════

class TenantResetRequest(BaseModel):
    mode: str                              # "transactions" | "full"
    confirm_slug: str                      # must be typed to match — no generic yes/no
    backup_downloaded: bool = False        # the operator confirms they hold a copy
    admin_username: Optional[str] = None   # full mode only: the new tenant login
    admin_password: Optional[str] = None


async def _tenant_or_404(db: AsyncSession, slug: str) -> Tenant:
    t = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if not t:
        raise HTTPException(404, f"Tenant '{slug}' not found")
    return t


@router.post("/tenants/{slug}/backup")
async def platform_backup_tenant(
    slug: str,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """pg_dump one tenant. The file stays on the server only until it is
    downloaded — the download endpoint removes it."""
    import os
    from app.multitenancy.router import _backup_tenant_db

    tenant = await _tenant_or_404(db, slug)
    try:
        path = await _backup_tenant_db(tenant.db_name, slug)
    except Exception as e:
        raise HTTPException(500, f"Backup failed: {e}")

    size = os.path.getsize(path) if os.path.exists(path) else 0
    # A dump that produced nothing is worse than no dump, because it invites a
    # reset that cannot be undone. Refuse to report success for it.
    if size < 1024:
        raise HTTPException(500, "Backup produced an empty file — refusing to report success")
    logger.info("platform backup: %s by %s (%s bytes)", slug, user.username, size)
    return {"slug": slug, "file": os.path.basename(path), "size_bytes": size}


@router.get("/tenants/{slug}/backup/download")
async def platform_download_backup(
    slug: str,
    file: str,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Stream a tenant dump to the caller, then delete the server copy."""
    import os
    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask

    await _tenant_or_404(db, slug)
    name = os.path.basename(file)          # never let a path escape the folder
    if not name.startswith(f"tenant_{slug}_") or not name.endswith(".sql"):
        raise HTTPException(400, "That file does not belong to this tenant")
    backup_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "backups",
    )
    path = os.path.join(backup_dir, name)
    if not os.path.isfile(path):
        raise HTTPException(404, "Backup not found — it may already have been downloaded")

    def _remove():
        try:
            os.remove(path)
            logger.info("platform backup downloaded and removed from server: %s", name)
        except OSError as e:
            logger.warning("could not remove backup %s: %s", name, e)

    return FileResponse(path, filename=name, media_type="application/sql",
                        background=BackgroundTask(_remove))


@router.post("/tenants/{slug}/reset")
async def platform_reset_tenant(
    slug: str,
    payload: TenantResetRequest,
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Give a tenant a clean slate. Irreversible — take the backup first."""
    from app.multitenancy import tenant_reset as tr
    from app.multitenancy.registry import tenant_registry

    tenant = await _tenant_or_404(db, slug)
    if payload.confirm_slug.strip() != slug:
        raise HTTPException(400, "Type the tenant slug exactly to confirm this reset")
    if payload.mode not in ("transactions", "full"):
        raise HTTPException(400, "mode must be 'transactions' or 'full'")
    if not payload.backup_downloaded:
        raise HTTPException(400, "Download a backup first — this cannot be undone")
    if payload.mode == "full" and not (payload.admin_username and payload.admin_password):
        raise HTTPException(
            400, "A full reset removes every login — supply the new tenant admin username and password")

    # Resolve the tenant's uploaded files BEFORE the rows that name them are gone.
    factory = await tenant_registry.get_session_factory(slug)
    async with factory() as tdb:
        paths = await tr.collect_upload_paths(tdb, slug)

    was_active = tenant.is_active
    tenant.is_active = False               # keep operators out of a database being rebuilt
    await db.commit()
    try:
        if payload.mode == "transactions":
            async with factory() as tdb:
                result = await tr.reset_transactions(tdb, slug)
        else:
            result = await tr.reset_full(
                slug, tenant.name if hasattr(tenant, "name") else slug,
                payload.admin_username, payload.admin_password)
    finally:
        tenant.is_active = was_active
        await db.commit()

    files = tr.purge_paths(paths)
    logger.warning("TENANT RESET (%s) mode=%s by %s — %s tables, %s files",
                   slug, payload.mode, user.username,
                   len(result.get("truncated") or []), files.get("files_deleted"))
    return {"slug": slug, "mode": payload.mode, "performed_by": user.username,
            "uploads": files, **result}


@router.post("/tenants/{slug}/restore")
async def platform_restore_tenant(
    slug: str,
    file: UploadFile = File(...),
    confirm_slug: str = Form(...),
    backup_downloaded: bool = Form(False),
    db: AsyncSession = Depends(get_master_db),
    user: PlatformUser = Depends(require_platform_role("platform_admin")),
):
    """Roll a tenant back to a dump taken earlier.

    This REPLACES everything the tenant currently has, so it demands the same
    discipline as a reset: a fresh backup downloaded first, and the slug typed out.
    """
    import os
    import tempfile

    from app.multitenancy import tenant_reset as tr

    tenant = await _tenant_or_404(db, slug)
    if confirm_slug.strip() != slug:
        raise HTTPException(400, "Type the tenant slug exactly to confirm this restore")
    if not backup_downloaded:
        raise HTTPException(400, "Back up the CURRENT data first — a restore overwrites it")

    name = os.path.basename(file.filename or "")
    # Our dumps are named tenant_<slug>_<timestamp>.sql. Insisting on that is a
    # real guard against the actual mistake: picking the wrong tenant's file out of
    # a folder full of similar-looking dumps.
    if not name.startswith(f"tenant_{slug}_") or not name.endswith(".sql"):
        raise HTTPException(
            400,
            f"That file is not a backup of '{slug}'. Expected a file named "
            f"tenant_{slug}_<timestamp>.sql",
        )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".sql")
    size = 0
    try:
        while chunk := await file.read(1024 * 1024):     # stream: dumps can be large
            size += len(chunk)
            tmp.write(chunk)
        tmp.close()

        ok, why = tr.looks_like_pg_dump(tmp.name)
        if not ok:
            raise HTTPException(400, why)          # rejected while the data is still there

        was_active = tenant.is_active
        tenant.is_active = False
        await db.commit()
        try:
            result = await tr.restore_from_dump(slug, tenant.db_name, tmp.name)
        finally:
            tenant.is_active = was_active
            await db.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Restore failed: {e}")
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    logger.warning("TENANT RESTORE (%s) by %s from %s (%s bytes)",
                   slug, user.username, name, size)
    return {"slug": slug, "restored_from": name, "size_bytes": size,
            "performed_by": user.username, **result}

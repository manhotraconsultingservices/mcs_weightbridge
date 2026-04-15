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

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
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
    for field, value in updates.items():
        if hasattr(tenant, field):
            setattr(tenant, field, value)
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

    config = tenant.config or {}
    saved_modules = config.get("modules", {})
    resolved = {**DEFAULT_MODULES, **saved_modules}
    return {"slug": slug, "modules": resolved}


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

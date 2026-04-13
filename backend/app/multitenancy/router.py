"""Tenant management API — super-admin endpoints for creating, listing,
updating, and backing up tenants.

Auth: requires X-Super-Admin header matching settings.SUPER_ADMIN_SECRET,
OR a valid JWT from any tenant with role=admin (for listing only).
"""

import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.multitenancy.master_db import get_master_db, get_master_session_factory
from app.multitenancy.models import Tenant
from app.multitenancy.registry import tenant_registry, SLUG_PATTERN
from app.schemas.tenant import (
    TenantCreate,
    TenantCreateResponse,
    TenantListResponse,
    TenantResponse,
    TenantUpdate,
)
from app.schemas.platform import TenantPublicInfo, PlatformBrandingResponse

logger = logging.getLogger(__name__)
router = APIRouter()
public_router = APIRouter()   # no auth required — mounted separately


# ── Public tenant info (no auth — used by login page) ─────────────────────────

@public_router.get("/tenant-info/{slug}", response_model=TenantPublicInfo)
async def get_tenant_public_info(
    slug: str,
    db: AsyncSession = Depends(get_master_db),
):
    """Return public tenant info + platform branding for the login page.

    No authentication required — the login page needs this before the user logs in.
    Only returns safe, public-facing fields (no API keys, no config).
    """
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")

    # Fetch platform branding
    branding_row = (await db.execute(
        text("SELECT company_name, website, email, logo_url FROM platform_branding WHERE id = 1")
    )).fetchone()

    if branding_row:
        branding = PlatformBrandingResponse(
            company_name=branding_row[0] or "Manhotra Consulting",
            website=branding_row[1],
            email=branding_row[2],
            logo_url=branding_row[3],
        )
    else:
        branding = PlatformBrandingResponse(company_name="Manhotra Consulting")

    return TenantPublicInfo(
        slug=tenant.slug,
        display_name=tenant.display_name,
        logo_url=getattr(tenant, "logo_url", None),
        status=getattr(tenant, "status", "active"),
        branding=branding,
    )


# ── Auth helper ──────────────────────────────────────────────────────────────

async def _require_super_admin(
    x_super_admin: Optional[str] = Header(None, alias="X-Super-Admin"),
):
    """Validate the super-admin secret header."""
    settings = get_settings()
    if not settings.SUPER_ADMIN_SECRET:
        raise HTTPException(500, "SUPER_ADMIN_SECRET not configured on server")
    if x_super_admin != settings.SUPER_ADMIN_SECRET:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid super-admin secret")


# ── Tenant CRUD ──────────────────────────────────────────────────────────────

@router.post("/tenants", response_model=TenantCreateResponse)
async def create_tenant(
    payload: TenantCreate,
    db: AsyncSession = Depends(get_master_db),
    _auth=Depends(_require_super_admin),
):
    """Create a new tenant: register in master DB, create database, seed data."""
    settings = get_settings()
    slug = payload.slug
    db_name = f"{settings.TENANT_DB_PREFIX}{slug}"

    # Check slug doesn't already exist
    existing = await db.execute(select(Tenant).where(Tenant.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Tenant '{slug}' already exists")

    # 1. Create the PostgreSQL database
    try:
        await _create_database(db_name, settings)
    except Exception as e:
        logger.error("Failed to create database %s: %s", db_name, e)
        raise HTTPException(500, f"Failed to create database: {e}")

    # 2. Register in master DB
    agent_key = str(uuid.uuid4())
    tenant = Tenant(
        slug=slug,
        display_name=payload.display_name,
        db_name=db_name,
        is_active=True,
        agent_api_key=agent_key,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    # 3. Run DDL migrations on the new tenant database
    try:
        await _run_tenant_ddl(slug)
    except Exception as e:
        logger.error("DDL migration failed for %s: %s", slug, e)
        raise HTTPException(500, f"Database created but DDL failed: {e}")

    # 4. Seed default data (company, admin user, financial year)
    try:
        await _seed_tenant_data(slug, payload)
    except Exception as e:
        logger.error("Data seeding failed for %s: %s", slug, e)
        raise HTTPException(500, f"Database ready but seeding failed: {e}")

    logger.info("Tenant created: slug=%s, db=%s", slug, db_name)
    return TenantCreateResponse(
        tenant=TenantResponse.model_validate(tenant),
        admin_username=payload.admin_username,
        message=f"Tenant '{slug}' created successfully. Agent API key: {agent_key}",
    )


@router.get("/tenants", response_model=TenantListResponse)
async def list_tenants(
    db: AsyncSession = Depends(get_master_db),
    _auth=Depends(_require_super_admin),
):
    """List all tenants."""
    result = await db.execute(select(Tenant).order_by(Tenant.slug))
    tenants = list(result.scalars().all())
    return TenantListResponse(
        tenants=[TenantResponse.model_validate(t) for t in tenants],
        total=len(tenants),
    )


@router.get("/tenants/{slug}", response_model=TenantResponse)
async def get_tenant(
    slug: str,
    db: AsyncSession = Depends(get_master_db),
    _auth=Depends(_require_super_admin),
):
    """Get tenant details."""
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(404, f"Tenant '{slug}' not found")
    return TenantResponse.model_validate(tenant)


@router.put("/tenants/{slug}", response_model=TenantResponse)
async def update_tenant(
    slug: str,
    payload: TenantUpdate,
    db: AsyncSession = Depends(get_master_db),
    _auth=Depends(_require_super_admin),
):
    """Update tenant display name, active status, or config."""
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(404, f"Tenant '{slug}' not found")

    if payload.display_name is not None:
        tenant.display_name = payload.display_name
    if payload.is_active is not None:
        tenant.is_active = payload.is_active
        if not payload.is_active:
            # Remove engine from cache when deactivating
            await tenant_registry.remove_tenant(slug)
    if payload.config is not None:
        tenant.config = payload.config

    await db.commit()
    await db.refresh(tenant)
    logger.info("Tenant updated: %s", slug)
    return TenantResponse.model_validate(tenant)


@router.post("/tenants/{slug}/rotate-key", response_model=TenantResponse)
async def rotate_agent_key(
    slug: str,
    db: AsyncSession = Depends(get_master_db),
    _auth=Depends(_require_super_admin),
):
    """Generate a new agent API key for a tenant."""
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(404, f"Tenant '{slug}' not found")

    tenant.agent_api_key = str(uuid.uuid4())
    await db.commit()
    await db.refresh(tenant)
    logger.info("Agent key rotated for tenant: %s", slug)
    return TenantResponse.model_validate(tenant)


@router.post("/tenants/{slug}/backup")
async def backup_tenant(
    slug: str,
    db: AsyncSession = Depends(get_master_db),
    _auth=Depends(_require_super_admin),
):
    """Create a pg_dump backup for a specific tenant."""
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(404, f"Tenant '{slug}' not found")

    try:
        filepath = await _backup_tenant_db(tenant.db_name, slug)
        return {"message": f"Backup created for '{slug}'", "file": filepath}
    except Exception as e:
        raise HTTPException(500, f"Backup failed: {e}")


@router.post("/tenants/backup-all")
async def backup_all_tenants(
    db: AsyncSession = Depends(get_master_db),
    _auth=Depends(_require_super_admin),
):
    """Backup all active tenant databases."""
    result = await db.execute(
        select(Tenant).where(Tenant.is_active == True).order_by(Tenant.slug)
    )
    tenants = list(result.scalars().all())
    results = []
    for t in tenants:
        try:
            fp = await _backup_tenant_db(t.db_name, t.slug)
            results.append({"slug": t.slug, "status": "ok", "file": fp})
        except Exception as e:
            results.append({"slug": t.slug, "status": "error", "error": str(e)})
    return {"message": f"Backup completed for {len(tenants)} tenants", "results": results}


# ── Internal helpers ─────────────────────────────────────────────────────────

async def _create_database(db_name: str, settings):
    """Create a new PostgreSQL database using a sync psycopg connection.

    CREATE DATABASE cannot run inside a transaction block, so we use
    psycopg with autocommit=True (sync driver) instead of asyncpg.
    Falls back to docker exec + psql if psycopg is unavailable.
    """
    import asyncio

    def _create_sync():
        try:
            import psycopg
        except ImportError:
            # Fallback: use docker exec + psql
            _create_via_docker(db_name, settings)
            return

        from urllib.parse import urlparse
        parsed = urlparse(settings.MASTER_DATABASE_URL_SYNC)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        user = parsed.username or "weighbridge"
        password = parsed.password or ""

        conninfo = f"host={host} port={port} user={user} password={password} dbname=postgres"
        with psycopg.connect(conninfo, autocommit=True) as conn:
            # Check if database already exists
            cur = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
            )
            if cur.fetchone():
                logger.info("Database %s already exists", db_name)
                return

            # CREATE DATABASE — must run outside transaction
            conn.execute(f"CREATE DATABASE {db_name} OWNER {user}")
            logger.info("Created database: %s", db_name)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _create_sync)


def _create_via_docker(db_name: str, settings):
    """Fallback: create database via docker exec + psql."""
    from urllib.parse import urlparse
    parsed = urlparse(settings.MASTER_DATABASE_URL_SYNC)
    user = parsed.username or "weighbridge"
    password = parsed.password or ""
    container = os.environ.get("PG_CONTAINER", "weighbridge_db")

    # Check if exists
    check = subprocess.run(
        ["docker", "exec", "-e", f"PGPASSWORD={password}", container,
         "psql", "-U", user, "-d", "postgres", "-tAc",
         f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"],
        capture_output=True, text=True, timeout=15,
    )
    if check.stdout.strip() == "1":
        logger.info("Database %s already exists", db_name)
        return

    result = subprocess.run(
        ["docker", "exec", "-e", f"PGPASSWORD={password}", container,
         "psql", "-U", user, "-d", "postgres", "-c",
         f"CREATE DATABASE {db_name} OWNER {user}"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker exec psql failed: {result.stderr}")
    logger.info("Created database via docker exec: %s", db_name)


async def _run_tenant_ddl(slug: str):
    """Run all DDL migrations on a tenant database.

    First creates core ORM tables (companies, users, tokens, invoices, etc.)
    from SQLAlchemy metadata, then runs runtime DDL for additional tables.
    """
    from app.ddl import get_runtime_ddl, get_column_migrations, get_supplier_ddl, get_supplier_master_ddl
    from app.database import Base

    # Import all ORM models so Base.metadata knows about them
    import app.models.user       # noqa: F401
    import app.models.company    # noqa: F401
    import app.models.party      # noqa: F401
    import app.models.product    # noqa: F401
    import app.models.vehicle    # noqa: F401
    import app.models.token      # noqa: F401
    import app.models.invoice    # noqa: F401
    import app.models.settings   # noqa: F401
    import app.models.quotation  # noqa: F401

    # Step 0: Create core ORM tables from SQLAlchemy metadata
    # This replaces the need for Alembic migrations on new tenant DBs
    try:
        engine = await tenant_registry.get_engine(slug)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Core ORM tables created for tenant: %s", slug)
    except Exception as e:
        logger.warning("Core ORM table creation failed for %s: %s", slug, e)

    factory = await tenant_registry.get_session_factory(slug)

    # Runtime tables (USB, notifications, compliance, camera, inventory, etc.)
    try:
        async with factory() as db:
            for ddl in get_runtime_ddl():
                await db.execute(text(ddl))
            await db.commit()
    except Exception as e:
        logger.warning("Runtime DDL failed for %s: %s", slug, e)

    # Supplier item-level table
    try:
        async with factory() as db:
            await db.execute(text(get_supplier_ddl()))
            await db.commit()
    except Exception as e:
        logger.warning("inventory_item_suppliers DDL failed for %s: %s", slug, e)

    # Supplier master table
    try:
        async with factory() as db:
            await db.execute(text(get_supplier_master_ddl()))
            await db.commit()
    except Exception as e:
        logger.warning("inventory_suppliers DDL failed for %s: %s", slug, e)

    # Link column between item-suppliers and master-suppliers
    try:
        async with factory() as db:
            await db.execute(text(
                "ALTER TABLE inventory_item_suppliers ADD COLUMN IF NOT EXISTS master_supplier_id UUID REFERENCES inventory_suppliers(id)"
            ))
            await db.commit()
    except Exception as e:
        logger.warning("master_supplier_id column failed for %s: %s", slug, e)

    # Column migrations
    try:
        async with factory() as db:
            for col_mig in get_column_migrations():
                await db.execute(text(col_mig))
            await db.commit()
    except Exception as e:
        logger.warning("Column migrations failed for %s: %s", slug, e)

    logger.info("DDL migrations complete for tenant: %s", slug)


async def _seed_tenant_data(slug: str, payload: TenantCreate):
    """Seed a new tenant database with company, admin user, and financial year."""
    from app.utils.auth import hash_password

    factory = await tenant_registry.get_session_factory(slug)
    async with factory() as db:
        now = datetime.now(timezone.utc)

        # Compute financial year (April-March for India)
        from datetime import date as date_cls
        year = now.year
        if now.month < 4:
            fy_start = date_cls(year - 1, 4, 1)
            fy_end = date_cls(year, 3, 31)
            fy_label = f"{year - 1}-{str(year)[2:]}"
        else:
            fy_start = date_cls(year, 4, 1)
            fy_end = date_cls(year + 1, 3, 31)
            fy_label = f"{year}-{str(year + 1)[2:]}"

        # Create company (includes current FY dates)
        company_id = str(uuid.uuid4())
        await db.execute(text("""
            INSERT INTO companies (id, name, invoice_prefix, quotation_prefix, purchase_prefix,
                                   current_fy_start, current_fy_end)
            VALUES (:id, :name, 'INV', 'QTN', 'PUR', :fy_start, :fy_end)
            ON CONFLICT DO NOTHING
        """), {"id": company_id, "name": payload.company_name,
               "fy_start": fy_start, "fy_end": fy_end})

        # Create financial year
        fy_id = str(uuid.uuid4())
        await db.execute(text("""
            INSERT INTO financial_years (id, company_id, label, start_date, end_date, is_active)
            VALUES (:id, :cid, :label, :start, :end, TRUE)
            ON CONFLICT DO NOTHING
        """), {
            "id": fy_id, "cid": company_id,
            "label": fy_label, "start": fy_start, "end": fy_end,
        })

        # Create admin user
        admin_id = str(uuid.uuid4())
        pw_hash = hash_password(payload.admin_password)
        await db.execute(text("""
            INSERT INTO users (id, company_id, username, password_hash, full_name, role, is_active)
            VALUES (:id, :cid, :username, :pw, :fullname, 'admin', TRUE)
            ON CONFLICT (username) DO NOTHING
        """), {
            "id": admin_id, "cid": company_id,
            "username": payload.admin_username,
            "pw": pw_hash,
            "fullname": "Administrator",
        })

        await db.commit()
    logger.info("Seeded tenant %s: company=%s, user=%s", slug, payload.company_name, payload.admin_username)


async def _backup_tenant_db(db_name: str, slug: str) -> str:
    """Run pg_dump for a tenant database and return the backup file path.
    Uses docker exec if pg_dump is not available locally.
    """
    from urllib.parse import urlparse
    import asyncio

    settings = get_settings()
    parsed = urlparse(settings.MASTER_DATABASE_URL_SYNC)

    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    user = parsed.username or "weighbridge"
    password = parsed.password or ""
    container = os.environ.get("PG_CONTAINER", "weighbridge_db")

    backup_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "backups",
    )
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"tenant_{slug}_{timestamp}.sql"
    filepath = os.path.join(backup_dir, filename)

    def _do_backup():
        env = os.environ.copy()
        env["PGPASSWORD"] = password

        # Try local pg_dump first, fall back to docker exec
        try:
            result = subprocess.run(
                ["pg_dump", "-h", host, "-p", str(port), "-U", user,
                 "-d", db_name, "--no-owner", "--no-acl",
                 "-f", filepath],
                capture_output=True, text=True, env=env, timeout=120,
            )
            if result.returncode == 0:
                return
        except FileNotFoundError:
            pass

        # Fallback: docker exec pg_dump
        result = subprocess.run(
            ["docker", "exec", "-e", f"PGPASSWORD={password}", container,
             "pg_dump", "-U", user, "-d", db_name, "--no-owner", "--no-acl"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {result.stderr}")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(result.stdout)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _do_backup)

    logger.info("Backup created: %s", filepath)
    return filepath

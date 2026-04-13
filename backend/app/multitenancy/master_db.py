"""Master database engine and session factory.

The master database (weighbridge_master) stores the tenant registry.
Only initialized when MULTI_TENANT=True.
"""

import logging
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Module-level — lazily initialized
_master_engine = None
_master_session_factory = None


def _ensure_initialized():
    """Create master engine + session factory on first use."""
    global _master_engine, _master_session_factory
    if _master_engine is not None:
        return

    from app.config import get_settings
    settings = get_settings()

    _master_engine = create_async_engine(
        settings.MASTER_DATABASE_URL,
        echo=False,
        pool_size=2,
        max_overflow=3,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "server_settings": {"application_name": "weighbridge_master"},
            "command_timeout": 30,
        },
    )
    _master_session_factory = async_sessionmaker(
        _master_engine, class_=AsyncSession, expire_on_commit=False
    )


async def get_master_db():
    """FastAPI dependency — yields an AsyncSession on the master database."""
    _ensure_initialized()
    async with _master_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


def get_master_session_factory():
    """Direct access for non-dependency contexts (startup, background tasks)."""
    _ensure_initialized()
    return _master_session_factory


async def init_master_db():
    """Create/migrate all master database tables."""
    _ensure_initialized()

    ddl_statements = [
        # ── Tenants table (original) ──
        """
        CREATE TABLE IF NOT EXISTS tenants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            slug VARCHAR(50) NOT NULL UNIQUE,
            display_name VARCHAR(200) NOT NULL,
            db_name VARCHAR(100) NOT NULL UNIQUE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            agent_api_key VARCHAR(200) NOT NULL UNIQUE,
            config JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # ── Tenant column migrations (new SaaS fields) ──
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS amc_start_date DATE",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS amc_expiry_date DATE",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500)",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS contact_email VARCHAR(200)",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(20)",

        # ── Platform users (internal staff: platform_admin, sales_rep) ──
        """
        CREATE TABLE IF NOT EXISTS platform_users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username VARCHAR(50) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            full_name VARCHAR(100),
            email VARCHAR(200),
            phone VARCHAR(20),
            role VARCHAR(20) NOT NULL DEFAULT 'sales_rep',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,

        # ── Tenant ↔ Sales rep junction ──
        """
        CREATE TABLE IF NOT EXISTS tenant_sales_reps (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            platform_user_id UUID NOT NULL REFERENCES platform_users(id) ON DELETE CASCADE,
            assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tenant_id, platform_user_id)
        )
        """,

        # ── Platform branding (singleton row) ──
        """
        CREATE TABLE IF NOT EXISTS platform_branding (
            id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            company_name VARCHAR(200) NOT NULL DEFAULT 'Manhotra Consulting',
            website VARCHAR(500),
            email VARCHAR(200),
            logo_url VARCHAR(500),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ]

    async with _master_session_factory() as db:
        for ddl in ddl_statements:
            await db.execute(text(ddl))
        await db.commit()

    # Seed defaults
    await _seed_platform_defaults()
    logger.info("Master database initialized (all platform tables ensured)")


async def _seed_platform_defaults():
    """Seed default platform admin user and branding row if tables are empty."""
    from passlib.context import CryptContext
    from app.config import get_settings

    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    settings = get_settings()

    async with _master_session_factory() as db:
        # Seed default branding
        row = (await db.execute(text("SELECT id FROM platform_branding WHERE id = 1"))).fetchone()
        if not row:
            await db.execute(text("""
                INSERT INTO platform_branding (id, company_name, website, email)
                VALUES (1, 'Manhotra Consulting', 'https://manhotraconsulting.com', 'info@manhotraconsulting.com')
            """))
            logger.info("Seeded default platform branding")

        # Seed default platform admin
        admin_user = getattr(settings, "PLATFORM_ADMIN_USER", "platform_admin")
        admin_pass = getattr(settings, "PLATFORM_ADMIN_PASSWORD", "Admin@123")
        existing = (await db.execute(
            text("SELECT id FROM platform_users WHERE username = :u"),
            {"u": admin_user},
        )).fetchone()
        if not existing:
            hashed = pwd_ctx.hash(admin_pass)
            await db.execute(text("""
                INSERT INTO platform_users (username, password_hash, full_name, role)
                VALUES (:u, :h, 'Platform Administrator', 'platform_admin')
            """), {"u": admin_user, "h": hashed})
            logger.info("Seeded default platform admin user: %s", admin_user)

        await db.commit()


async def dispose_master():
    """Shutdown: dispose the master engine."""
    global _master_engine, _master_session_factory
    if _master_engine:
        await _master_engine.dispose()
        _master_engine = None
        _master_session_factory = None

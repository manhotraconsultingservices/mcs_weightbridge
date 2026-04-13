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
    """Create the tenants table in the master database if it doesn't exist."""
    _ensure_initialized()
    ddl = """
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
    """
    async with _master_session_factory() as db:
        await db.execute(text(ddl))
        await db.commit()
    logger.info("Master database initialized (tenants table ensured)")


async def dispose_master():
    """Shutdown: dispose the master engine."""
    global _master_engine, _master_session_factory
    if _master_engine:
        await _master_engine.dispose()
        _master_engine = None
        _master_session_factory = None

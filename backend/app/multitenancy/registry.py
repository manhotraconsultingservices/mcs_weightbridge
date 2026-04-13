"""Tenant Registry — manages per-tenant database engines and session factories.

Lazily creates an AsyncEngine + async_sessionmaker for each tenant on first
access, caching them for the lifetime of the process.  All tenant databases
live in the same PostgreSQL instance; only the database name differs.
"""

import asyncio
import logging
import re
from urllib.parse import urlparse, urlunparse

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)

from app.multitenancy.models import Tenant

logger = logging.getLogger(__name__)

# Slug validation: lowercase alpha start, then alpha/digits/underscore, 3-31 chars
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,30}$")


class TenantRegistry:
    """Singleton that caches per-tenant engines and session factories."""

    def __init__(self):
        self._engines: dict[str, AsyncEngine] = {}
        self._factories: dict[str, async_sessionmaker] = {}
        self._lock = asyncio.Lock()

    # ── URL builder ──────────────────────────────────────────────────────────

    def build_db_url(self, slug: str) -> str:
        """Replace the database name in MASTER_DATABASE_URL with wb_{slug}."""
        from app.config import get_settings
        settings = get_settings()
        parsed = urlparse(settings.MASTER_DATABASE_URL)
        # path is  /weighbridge_master  →  /wb_{slug}
        new_path = f"/{settings.TENANT_DB_PREFIX}{slug}"
        return urlunparse(parsed._replace(path=new_path))

    def build_db_url_sync(self, slug: str) -> str:
        """Sync version (psycopg) for pg_dump / CREATE DATABASE."""
        from app.config import get_settings
        settings = get_settings()
        parsed = urlparse(settings.MASTER_DATABASE_URL_SYNC)
        new_path = f"/{settings.TENANT_DB_PREFIX}{slug}"
        return urlunparse(parsed._replace(path=new_path))

    # ── Engine / session factory ─────────────────────────────────────────────

    async def get_session_factory(self, slug: str) -> async_sessionmaker:
        """Return (and cache) the session factory for the given tenant."""
        if slug in self._factories:
            return self._factories[slug]

        async with self._lock:
            # Double-check after acquiring lock
            if slug in self._factories:
                return self._factories[slug]

            from app.config import get_settings
            settings = get_settings()

            url = self.build_db_url(slug)
            engine = create_async_engine(
                url,
                echo=False,
                pool_size=settings.TENANT_POOL_SIZE,
                max_overflow=settings.TENANT_MAX_OVERFLOW,
                pool_pre_ping=True,
                pool_recycle=1800,
                connect_args={
                    "server_settings": {
                        "application_name": f"weighbridge_{slug}"
                    },
                    "command_timeout": 30,
                },
            )
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            self._engines[slug] = engine
            self._factories[slug] = factory
            logger.info("Created engine for tenant: %s", slug)
            return factory

    async def get_engine(self, slug: str) -> AsyncEngine:
        """Return the engine for a tenant (creates if needed)."""
        await self.get_session_factory(slug)  # ensures engine exists
        return self._engines[slug]

    # ── Master DB queries ────────────────────────────────────────────────────

    async def list_active_tenants(self) -> list[Tenant]:
        """Return all active tenants from the master database."""
        from app.multitenancy.master_db import get_master_session_factory
        factory = get_master_session_factory()
        async with factory() as db:
            result = await db.execute(
                select(Tenant).where(Tenant.is_active == True).order_by(Tenant.slug)
            )
            return list(result.scalars().all())

    async def list_all_tenants(self) -> list[Tenant]:
        """Return ALL tenants (including inactive) from master database."""
        from app.multitenancy.master_db import get_master_session_factory
        factory = get_master_session_factory()
        async with factory() as db:
            result = await db.execute(select(Tenant).order_by(Tenant.slug))
            return list(result.scalars().all())

    async def get_tenant(self, slug: str) -> Tenant | None:
        """Look up a single tenant by slug."""
        from app.multitenancy.master_db import get_master_session_factory
        factory = get_master_session_factory()
        async with factory() as db:
            result = await db.execute(
                select(Tenant).where(Tenant.slug == slug)
            )
            return result.scalar_one_or_none()

    async def validate_agent_key(self, slug: str, key: str) -> bool:
        """Validate an agent API key for the given tenant slug."""
        from app.multitenancy.master_db import get_master_session_factory
        factory = get_master_session_factory()
        async with factory() as db:
            result = await db.execute(
                select(Tenant).where(
                    Tenant.slug == slug,
                    Tenant.agent_api_key == key,
                    Tenant.is_active == True,
                )
            )
            return result.scalar_one_or_none() is not None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def dispose_all(self):
        """Shutdown: dispose all cached tenant engines."""
        for slug, engine in self._engines.items():
            try:
                await engine.dispose()
                logger.info("Disposed engine for tenant: %s", slug)
            except Exception as e:
                logger.warning("Error disposing engine for %s: %s", slug, e)
        self._engines.clear()
        self._factories.clear()

    async def remove_tenant(self, slug: str):
        """Remove a single tenant's engine from cache (e.g. after deactivation)."""
        async with self._lock:
            engine = self._engines.pop(slug, None)
            self._factories.pop(slug, None)
            if engine:
                await engine.dispose()


# Singleton instance
tenant_registry = TenantRegistry()

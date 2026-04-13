from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=5,           # 5 persistent connections — well under PostgreSQL's limit
    max_overflow=10,       # up to 15 total; leaves headroom for other tools/pgAdmin
    pool_pre_ping=True,    # test connection health before handing it to a request
    pool_recycle=1800,     # recycle connections every 30 min; prevents stale-connection errors
    connect_args={
        "server_settings": {"application_name": "weighbridge"},
        "command_timeout": 30,   # hard timeout on any individual query
    },
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI dependency — yields a database session.

    In single-tenant mode (MULTI_TENANT=false): uses the default engine.
    In multi-tenant mode: reads ContextVar set by TenantMiddleware to
    route to the correct tenant's database engine.
    """
    if not settings.MULTI_TENANT:
        # Original single-tenant path — unchanged
        async with async_session() as session:
            try:
                yield session
            finally:
                await session.close()
        return

    # Multi-tenant: route by context var
    from app.multitenancy.context import current_tenant_slug
    slug = current_tenant_slug.get()
    if not slug:
        # No tenant context — e.g. login endpoint before JWT is issued.
        # Yield None; endpoints that need a tenant session must handle this
        # or get their own session (like auth.login does via factory()).
        yield None
        return

    from app.multitenancy.registry import tenant_registry
    factory = await tenant_registry.get_session_factory(slug)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_tenant_session(slug: str | None) -> AsyncSession:
    """For background tasks running outside request context.

    In single-tenant mode: returns a session from the default engine.
    In multi-tenant mode: returns a session for the specified tenant.
    Usage:
        async with await get_tenant_session(slug) as db:
            ...
    """
    if not settings.MULTI_TENANT or not slug:
        return async_session()

    from app.multitenancy.registry import tenant_registry
    factory = await tenant_registry.get_session_factory(slug)
    return factory()

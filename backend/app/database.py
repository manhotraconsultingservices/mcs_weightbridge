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
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

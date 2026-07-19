"""Async SQLite engine + session factory for the edge agent.

The schema is emitted from the SAME ORM models the server uses (see schema.py),
so the local database stays in lockstep with the app with no parallel DDL.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

from agents.edge.schema import (
    Base, EDGE_REQUIRED_TABLES, configure_sqlite,
)

_engine = None
_Session: async_sessionmaker[AsyncSession] | None = None


def get_engine(db_path: str):
    global _engine, _Session
    if _engine is None:
        # check_same_thread is a threading guard, irrelevant under asyncio.
        _engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        # The pragmas (WAL, foreign_keys=ON, synchronous=FULL) attach to the
        # underlying sync engine's connect event — every real sqlite3 connection
        # aiosqlite opens gets them.
        configure_sqlite(_engine.sync_engine)
        _Session = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _Session is None:
        raise RuntimeError("edge DB not initialised — call init_db() first")
    return _Session


async def init_db(db_path: str):
    """Create the full edge schema on the SQLite file. Idempotent."""
    engine = get_engine(db_path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        present = await conn.run_sync(
            lambda sync_conn: set(__import__("sqlalchemy").inspect(sync_conn).get_table_names())
        )
    missing = [t for t in EDGE_REQUIRED_TABLES if t not in present]
    if missing:
        raise RuntimeError("edge schema incomplete — missing: " + ", ".join(missing))
    return engine

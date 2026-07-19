"""Apply a cloud masters snapshot into the local SQLite mirror.

The snapshot (from ``POST /api/v1/offline/masters``) is an ORDERED list of
``{table, rows}`` where a parent table always precedes any child that references
it, so the upsert runs cleanly with ``foreign_keys=ON``.

Upsert, not replace: ``INSERT … ON CONFLICT(id) DO UPDATE`` refreshes each row
in place. A DELETE-then-INSERT (``INSERT OR REPLACE``) would drop the row a
locally-created token references and trip the FK, so it is deliberately avoided.
Every mirrored table has a single ``id`` primary key.

The mirror is a cache: it is refreshed while online and read (never mutated) by
the offline routes, so it is safe to overwrite last-known-good in place. It is
NEVER wiped — an outage that starts right after a wipe would leave the operator
with no parties/products and unable to create a token at all.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker


def _upsert_sql(table: str, cols: list[str]) -> str:
    placeholders = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "id")
    if not updates:                       # single-column (id only) — nothing to update
        return (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO NOTHING")
    return (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}")


async def apply_snapshot(session_factory: async_sessionmaker, snapshot: dict[str, Any]) -> dict[str, int]:
    """Upsert every entity in the snapshot. Returns {table: rows_applied}.

    The whole snapshot is applied in ONE transaction so the mirror is never left
    half-refreshed (a token created against a partial mirror could reference a
    product that hadn't landed yet).
    """
    counts: dict[str, int] = {}
    entities = snapshot.get("entities") or []
    async with session_factory() as db:
        for entity in entities:
            table = entity["table"]
            rows = entity.get("rows") or []
            for row in rows:
                cols = list(row.keys())
                if "id" not in cols:
                    continue                # every master table is keyed by id
                await db.execute(text(_upsert_sql(table, cols)), row)
            counts[table] = len(rows)
        await db.commit()
    return counts

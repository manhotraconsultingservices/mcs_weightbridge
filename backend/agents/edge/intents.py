"""Edge intent spool — the durable, ordered record of what to replay.

Every local mutation writes BOTH the business row and an ordered intent in the
SAME SQLite transaction (see routes.py). On reconnect the replay engine pushes
intents to the cloud in strict `seq` order; the cloud dedupes by client_op_id,
so a re-push is a no-op.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def add_intent(
    db: AsyncSession, *, op_type: str, method: str, url: str,
    payload: dict[str, Any], entity_id: Optional[str] = None,
    depends_on: Optional[str] = None,
) -> str:
    """Insert one intent in the CALLER'S transaction (no commit). Returns op_id.

    The op_id doubles as the client_op_id the cloud dedupes on, so it is stamped
    into the replay payload here.
    """
    op_id = str(uuid.uuid4())
    body = dict(payload)
    body["client_op_id"] = op_id
    await db.execute(text(
        "INSERT INTO intents (op_id, op_type, method, url, payload, entity_id, depends_on) "
        "VALUES (:op, :ot, :m, :u, :p, :eid, :dep)"
    ), {
        "op": op_id, "ot": op_type, "m": method, "u": url,
        "p": json.dumps(body), "eid": entity_id, "dep": depends_on,
    })
    return op_id


async def pending_intents(db: AsyncSession) -> list[dict]:
    """All not-yet-synced intents, oldest first.

    Includes needs_review/needs_auth deliberately: ordering is load-bearing, so
    a parked item must BLOCK everything behind it. The replay engine halts the
    moment it sees a needs_review item rather than skipping ahead to a later
    pending one (which would replay a second weight before its first weight was
    resolved). Only 'done' items are excluded.
    """
    rows = (await db.execute(text(
        "SELECT seq, op_id, op_type, method, url, payload, entity_id, depends_on, "
        "status, attempts, last_error, assigned "
        "FROM intents WHERE status != 'done' ORDER BY seq ASC"
    ))).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
        d["assigned"] = json.loads(d["assigned"]) if d.get("assigned") else None
        out.append(d)
    return out


async def counts(db: AsyncSession) -> dict[str, int]:
    rows = (await db.execute(text(
        "SELECT status, COUNT(*) AS n FROM intents GROUP BY status"
    ))).all()
    return {status: n for status, n in rows}


async def mark(db: AsyncSession, op_id: str, status: str, *,
               last_error: Optional[str] = None, assigned: Optional[dict] = None,
               bump_attempts: bool = False) -> None:
    sql = "UPDATE intents SET status = :s, last_error = :e"
    params: dict[str, Any] = {"s": status, "e": last_error, "op": op_id}
    if bump_attempts:
        sql += ", attempts = attempts + 1"
    if assigned is not None:
        sql += ", assigned = :a"
        params["a"] = json.dumps(assigned)
    if status == "done":
        # Stamp the sync time so the pruner can retain from sync — not creation.
        # An intent created at 23:00 and synced at 09:00 must survive the 04:00
        # prune the next morning.
        sql += ", synced_at = datetime('now')"
    sql += " WHERE op_id = :op"
    await db.execute(text(sql), params)

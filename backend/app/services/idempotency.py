"""Idempotency ledger for replayable mutations.

Every mutation the offline edge captures carries a client-generated
``client_op_id``. When that operation replays to the cloud (once, or several
times if a retry races a slow first attempt), the server must apply it EXACTLY
once and return the same result on every replay.

Two layers, deliberately:

  1. ``find_applied`` — a fast PK lookup in ``sync_operations``. If the op was
     already applied, the caller returns the stored entity without re-running
     any business logic.
  2. The partial unique indexes ``ux_tokens_client_op`` / ``ux_invoices_client_op``
     on the business tables — the correctness backstop. If two replays race past
     the ledger check, the DB rejects the second at flush time; the caller
     catches ``IntegrityError`` and converts it into the replay response.

The ledger row is written in the SAME transaction as the business row, so there
is never a window where the entity exists but the ledger doesn't (or vice
versa). ``client_op_id`` is sent online too, so this path runs in production
continuously — not only during the rare outage nobody is watching.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

OP_ID_HEADER = "X-Client-Op-Id"
ORIGIN_HEADER = "X-Op-Origin"


def get_op_id(request: Request) -> Optional[str]:
    """Return a valid client op id from the request header, or None."""
    raw = request.headers.get(OP_ID_HEADER)
    if not raw:
        return None
    try:
        return str(uuid.UUID(raw.strip()))
    except (ValueError, AttributeError):
        return None


def get_origin(request: Request) -> str:
    o = (request.headers.get(ORIGIN_HEADER) or "").strip().lower()
    return "edge" if o == "edge" else "online"


@dataclass
class AppliedOp:
    op_id: str
    entity_type: Optional[str]
    entity_id: Optional[str]
    assigned: Optional[dict]


async def find_applied(db: AsyncSession, company_id, op_id: str) -> Optional[AppliedOp]:
    """Fast path: has this op already been applied for this company?"""
    row = (await db.execute(text(
        "SELECT entity_type, entity_id, assigned_json FROM sync_operations "
        "WHERE op_id = :op AND company_id = :cid AND status = 'applied'"
    ), {"op": op_id, "cid": str(company_id)})).fetchone()
    if row is None:
        return None
    assigned = row.assigned_json
    if isinstance(assigned, str):
        import json
        try:
            assigned = json.loads(assigned)
        except Exception:
            assigned = None
    return AppliedOp(op_id, row.entity_type, str(row.entity_id) if row.entity_id else None, assigned)


async def record_operation(
    db: AsyncSession, *, company_id, op_id: str, op_type: str,
    entity_type: str, entity_id, assigned: dict[str, Any] | None,
    user_id=None, origin: str = "online",
) -> None:
    """Write the ledger row IN THE CALLER'S TRANSACTION (no commit here).

    Uses ON CONFLICT DO NOTHING on the op_id PK so a benign duplicate insert
    doesn't raise; the real duplicate protection is the business-table unique
    index, which the caller catches.
    """
    import json
    await db.execute(text(
        "INSERT INTO sync_operations "
        "(op_id, company_id, user_id, op_type, entity_type, entity_id, assigned_json, origin, status) "
        "VALUES (:op, :cid, :uid, :otype, :etype, :eid, CAST(:assigned AS JSONB), :origin, 'applied') "
        "ON CONFLICT (op_id) DO NOTHING"
    ), {
        "op": op_id, "cid": str(company_id),
        "uid": str(user_id) if user_id else None,
        "otype": op_type, "etype": entity_type,
        "eid": str(entity_id) if entity_id else None,
        "assigned": json.dumps(assigned) if assigned is not None else None,
        "origin": origin,
    })

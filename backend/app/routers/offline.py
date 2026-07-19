"""Offline edge-sync API (SaaS/relay mode).

The LAN-side **edge agent** on the weighbridge PC talks to these endpoints to
(a) mirror the tenant's masters into its local SQLite while online, and
(b) replay the intents it captured during an outage, in strict order, when the
link returns.

Auth mirrors the scale agent + Tally connector: ``{tenant, agent_key}`` in the
POST body, validated against the master DB — **no user JWT**. Because there is
no JWT and no ``X-Tenant`` header, ``TenantMiddleware`` sets no tenant context
and skips module-gating entirely; the agent key IS the gate, and each handler
opens its own tenant-routed session via ``get_tenant_session``.

Endpoints:
  POST /api/v1/offline/ping         — auth + spool-depth check for the agent's --test
  POST /api/v1/offline/masters      — full masters snapshot (no 200/500 cap)
  POST /api/v1/offline/replay-one   — apply ONE captured intent, idempotently

The heavy lifting (``_apply_intent`` / ``_build_masters``) is split out as core
functions that take a ``db`` session, so they are testable against a plain
single-tenant dev DB without the agent-auth wrapper — exactly the router/core
split used by ``tally.py`` ↔ ``integrations.tally.relay_queue``.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.config import get_settings
from app.database import Base, get_tenant_session
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/offline", tags=["Offline Edge Sync"])


# ── auth (mirrors tally_connector._authed_tenant) ─────────────────────────────
async def _authed_tenant(payload: dict[str, Any]) -> str:
    if not get_settings().MULTI_TENANT:
        raise HTTPException(400, "The offline edge sync is only used in cloud (multi-tenant) mode.")
    tenant_slug = payload.get("tenant") or payload.get("tenant_slug")
    agent_key = payload.get("agent_key")
    if not tenant_slug or not agent_key:
        raise HTTPException(400, "tenant and agent_key are required")
    from app.multitenancy.registry import tenant_registry
    if not await tenant_registry.validate_agent_key(tenant_slug, agent_key):
        raise HTTPException(403, "Invalid agent key for tenant")
    return tenant_slug


# ── masters snapshot (core) ───────────────────────────────────────────────────
# FK-safe order: a parent table is always emitted before any child that
# references it, so the edge can apply the snapshot with foreign_keys=ON.
MASTER_TABLES: tuple[str, ...] = (
    "companies",
    "product_categories",
    "products",
    "product_unit_rates",
    "financial_years",
    "parties",
    "party_rates",
    "vehicles",
    "drivers",
    "transporters",
    "custom_field_definitions",
)


def _ser(v: Any) -> Any:
    """Serialise a Postgres value into a SQLite-storable primitive.

    Datetimes are rendered in SQLite's own ``YYYY-MM-DD HH:MM:SS`` format (no
    'T', no tz) so SQLAlchemy's DateTime result processor parses them back when
    the edge later loads the row through the ORM; UUID→str, Decimal→str,
    date→ISO, bool→0/1, dict/list→JSON text.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, uuid.UUID):
        # MUST match SQLAlchemy's SQLite storage for Uuid columns: 32-char hex,
        # NO dashes (value.hex). If we stored the dashed 36-char form, an
        # ORM-written FK (e.g. tokens.party_id, 32-hex) would not string-match
        # the mirrored parties.id and SQLite's foreign_keys=ON would reject it.
        return v.hex
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return v


async def _build_masters(db: AsyncSession) -> dict[str, Any]:
    """Full masters snapshot for the tenant DB (single-company per tenant, so no
    company filter is needed — and no page cap, closing the 200/500 truncation)."""
    entities = []
    total = 0
    for name in MASTER_TABLES:
        tbl = Base.metadata.tables.get(name)
        if tbl is None:
            continue
        try:
            rows = (await db.execute(select(tbl))).mappings().all()
        except Exception as e:
            # A brand-new feature table may not exist yet on a tenant DB whose
            # DDL hasn't run — skip it rather than failing the whole mirror.
            logger.warning("offline masters: skipping table %s — %s", name, e)
            await db.rollback()
            continue
        ser_rows = [{k: _ser(v) for k, v in r.items()} for r in rows]
        entities.append({"table": name, "rows": ser_rows})
        total += len(ser_rows)
    return {"entities": entities, "row_count": total,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}


# ── replay one intent (core) ──────────────────────────────────────────────────
def _edge_request(op_id: Optional[str]) -> Request:
    """A synthetic request carrying the idempotency headers the cloud token
    handlers read (they dedupe on X-Client-Op-Id; X-Op-Origin stamps 'edge')."""
    headers = []
    if op_id:
        headers = [(b"x-client-op-id", str(op_id).encode()), (b"x-op-origin", b"edge")]
    return Request({"type": "http", "headers": headers})


async def _system_user(db: AsyncSession) -> User:
    """A stable author for replayed records (created_by / audit). Prefers an
    active admin; the token stays marked origin='edge' for provenance."""
    uid = (await db.execute(text(
        "SELECT id FROM users WHERE is_active = TRUE "
        "ORDER BY (role = 'admin') DESC LIMIT 1"
    ))).scalar_one_or_none()
    if uid is None:
        raise HTTPException(503, "No active user to attribute the replayed record to")
    u = User()
    u.id = uid
    return u


# Roles allowed to approve an invoice — MUST mirror the require_role on the cloud
# approve endpoint. This is the governance backstop for the offline path: the
# frontend hides the button from non-managers and the edge fails fast, but the
# authoritative check is HERE, at sync, against the real user record.
APPROVE_ROLES = ("admin", "accountant", "store_manager")


async def _resolve_approver(db: AsyncSession, approver_id) -> User:
    """The real user who approved a bill offline. Verifies they exist, are active
    and hold a manager role — so an operator's offline approval can NEVER apply as
    a manager at sync (it parks for review instead). approved_by is then this real
    user, never a generic 'system' admin.

    A MISSING approver is rejected (parked), NOT applied as system — closing the
    bypass where a hand-crafted null-approver approval (a curl to the loopback edge
    route) would slip past the role check. The frontend always sends the approver;
    there are no legacy no-approver intents in production to protect."""
    if not approver_id:
        raise HTTPException(422, "offline approval carries no approver — parked for a manager")
    try:
        aid = uuid.UUID(str(approver_id))
    except (ValueError, AttributeError):
        raise HTTPException(422, "approval intent carries an invalid approver id — parked for review")
    from sqlalchemy import select as _select
    u = (await db.execute(_select(User).where(User.id == aid))).scalar_one_or_none()
    if u is None or not getattr(u, "is_active", True):
        raise HTTPException(422, "offline approval by an unknown/inactive user — parked for a manager")
    if u.role not in APPROVE_ROLES:
        raise HTTPException(422, f"role '{u.role}' cannot approve invoices — parked for a manager")
    return u


async def _apply_intent(db: AsyncSession, op_type: str, entity_id: Optional[str],
                        payload: dict[str, Any]) -> dict[str, Any]:
    """Apply ONE captured intent by re-dispatching to the REAL cloud handler.

    Reusing create_token / record_first_weight / record_second_weight verbatim
    means the replayed token gets the server's own validation, numbering,
    auto-invoice and accounting — and the idempotency ledger inside each makes a
    re-push a no-op. Business errors (409/422/…) propagate as HTTPException so
    the edge parks the intent for review; the same error never silently drops it.
    """
    from app.routers.tokens import create_token, record_first_weight, record_second_weight
    from app.schemas.token import TokenCreate, TokenFirstWeight, TokenSecondWeight

    body = {k: v for k, v in (payload or {}).items() if k != "client_op_id"}
    op_id = (payload or {}).get("client_op_id")
    req = _edge_request(op_id)
    user = await _system_user(db)

    if op_type == "token.create":
        tok = await create_token(TokenCreate(**body), req, db, user, None)
    elif op_type == "token.first_weight":
        tok = await record_first_weight(uuid.UUID(entity_id), TokenFirstWeight(**body),
                                        req, BackgroundTasks(), db, user)
    elif op_type == "token.second_weight":
        tok = await record_second_weight(uuid.UUID(entity_id), TokenSecondWeight(**body),
                                         req, BackgroundTasks(), db, user)
    elif op_type == "invoice.approve":
        # #175: keyed by token_id (the edge invoice id != the cloud one). Reuse the
        # same token-keyed approve the cloud endpoint serves — it finds the draft
        # the second-weight replay auto-created and approve+finalises it, so the
        # SERVER assigns the legal GST number at sync.
        from app.routers.invoices import approve_token_invoice
        approver = await _resolve_approver(db, (payload or {}).get("approver_user_id"))
        res = await approve_token_invoice(uuid.UUID(entity_id), BackgroundTasks(), db, approver)
        return {"invoice_id": str(res.id), "invoice_no": res.invoice_no, "status": res.status}
    else:
        raise HTTPException(422, f"unknown op_type '{op_type}'")

    return {"id": str(tok.id), "token_no": tok.token_no,
            "gate_pass_no": tok.gate_pass_no, "status": tok.status}


# ── endpoints ─────────────────────────────────────────────────────────────────
@router.post("/ping")
async def offline_ping(payload: dict[str, Any]):
    tenant = await _authed_tenant(payload)
    async with await get_tenant_session(tenant) as db:
        n_parties = (await db.execute(text("SELECT count(*) FROM parties"))).scalar()
        n_products = (await db.execute(text("SELECT count(*) FROM products"))).scalar()
    return {"ok": True, "tenant": tenant,
            "parties": int(n_parties or 0), "products": int(n_products or 0)}


@router.post("/masters")
async def offline_masters(payload: dict[str, Any]):
    tenant = await _authed_tenant(payload)
    from app.multitenancy.context import current_tenant_slug
    ctok = current_tenant_slug.set(tenant)
    try:
        async with await get_tenant_session(tenant) as db:
            return await _build_masters(db)
    finally:
        current_tenant_slug.reset(ctok)


@router.post("/replay-one")
async def offline_replay_one(payload: dict[str, Any]):
    tenant = await _authed_tenant(payload)
    op_type = payload.get("op_type")
    entity_id = payload.get("entity_id")
    body = payload.get("payload") or {}
    from app.multitenancy.context import current_tenant_slug
    ctok = current_tenant_slug.set(tenant)
    try:
        async with await get_tenant_session(tenant) as db:
            assigned = await _apply_intent(db, op_type, entity_id, body)
        return {"ok": True, "assigned": assigned}
    finally:
        current_tenant_slug.reset(ctok)

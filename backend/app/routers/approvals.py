"""
Maker-checker (4-eyes) approval queue — router.

When a tenant turns the ``maker_checker`` control ON (Settings → Approvals),
sensitive money actions (single write-off, bulk write-off, invoice cancel,
day-book opening-balance change) are PARKED as a pending ``approval_requests``
row by the protected endpoints (see ``services/approvals.py``). This router
lets a second admin — the *checker*, who must differ from the *maker* — review
the queue and **approve** (the real action then runs) or **reject** it.

Toggle config lives in ``app_settings.maker_checker`` ({"enabled": bool}).
- GET /config  → any authed user (the frontend needs to know whether to show the
  "submitted for approval" UX and the queue nav item).
- PUT /config  → admin only.
- GET /        → admin + accountant (see the queue). Filters: status.
- GET /pending-count → admin + accountant (nav badge).
- POST /{id}/approve, /{id}/reject → admin only; checker MUST differ from maker.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.approval import ApprovalRequest
from app.models.user import User
from app.services.approvals import (
    MAKER_CHECKER_KEY, ACTION_LABELS, apply_approved,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/approvals", tags=["Approvals"])


def _serialize(ar: ApprovalRequest) -> dict:
    return {
        "id": str(ar.id),
        "action_type": ar.action_type,
        "action_label": ACTION_LABELS.get(ar.action_type, ar.action_type),
        "title": ar.title,
        "amount": float(ar.amount) if ar.amount is not None else None,
        "status": ar.status,
        "requested_by": str(ar.requested_by) if ar.requested_by else None,
        "requested_by_name": ar.requested_by_name,
        "requested_at": ar.requested_at.isoformat() if ar.requested_at else None,
        "decided_by": str(ar.decided_by) if ar.decided_by else None,
        "decided_by_name": ar.decided_by_name,
        "decided_at": ar.decided_at.isoformat() if ar.decided_at else None,
        "decision_note": ar.decision_note,
        "result": ar.result,
        "payload": ar.payload,
    }


# ── Config toggle ─────────────────────────────────────────────────────────────

@router.get("/config")
async def get_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the maker-checker toggle state (any authed user)."""
    out = {"enabled": False}
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key=:k"),
            {"k": MAKER_CHECKER_KEY})).fetchone()
        if row and row[0] is not None:
            cfg = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            if isinstance(cfg, dict):
                out.update(cfg)
    except Exception as exc:
        log.warning("approvals config read failed: %s", exc)
    return out


@router.put("/config")
async def put_config(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Enable/disable maker-checker for this tenant (admin only). Audit-logged."""
    enabled = bool(payload.get("enabled"))
    clean = {"enabled": enabled}
    await db.execute(
        text("""INSERT INTO app_settings (key, value, updated_at)
                VALUES (:k, :v, NOW())
                ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()"""),
        {"k": MAKER_CHECKER_KEY, "v": json.dumps(clean)})
    try:
        from app.routers.audit import log_action
        await log_action(
            db, current_user.company_id, current_user.id,
            "update", "maker_checker_config", entity_id=None,
            details={"enabled": enabled,
                     "by": getattr(current_user, "username", None) or getattr(current_user, "full_name", None)},
            ip_address=(request.client.host if request and request.client else None),
        )
    except Exception as exc:
        log.warning("approvals config audit failed: %s", exc)
    await db.commit()
    return {"ok": True, **clean}


# ── Queue ─────────────────────────────────────────────────────────────────────

@router.get("")
async def list_requests(
    status: str | None = Query(None),
    limit: int = Query(200, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "accountant")),
):
    """List approval requests for this company (newest first)."""
    q = select(ApprovalRequest).where(ApprovalRequest.company_id == current_user.company_id)
    if status:
        q = q.where(ApprovalRequest.status == status)
    q = q.order_by(ApprovalRequest.requested_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return {"items": [_serialize(r) for r in rows]}


@router.get("/pending-count")
async def pending_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "accountant")),
):
    """Small nav-badge count of pending requests."""
    n = (await db.execute(
        select(func.count()).select_from(ApprovalRequest).where(
            ApprovalRequest.company_id == current_user.company_id,
            ApprovalRequest.status == "pending",
        ))).scalar() or 0
    return {"pending": int(n)}


async def _load_pending(db: AsyncSession, req_id: uuid.UUID, company_id: uuid.UUID) -> ApprovalRequest:
    ar = (await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == req_id,
            ApprovalRequest.company_id == company_id,
        ))).scalar_one_or_none()
    if ar is None:
        raise HTTPException(404, "Approval request not found")
    if ar.status != "pending":
        raise HTTPException(400, f"Request is already {ar.status}; only pending requests can be actioned.")
    return ar


@router.post("/{req_id}/approve")
async def approve_request(
    req_id: uuid.UUID,
    request: Request,
    payload: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Approve a pending request → execute the real action (4-eyes enforced).

    The checker MUST be a different admin from the maker who submitted it.
    """
    ar = await _load_pending(db, req_id, current_user.company_id)

    # ── True 4-eyes: the checker cannot be the person who requested it ──────────
    if ar.requested_by and ar.requested_by == current_user.id:
        raise HTTPException(
            403,
            "You submitted this request — a different admin must approve it (4-eyes control).",
        )

    # Execute the real action as the original maker. Re-validation happens inside;
    # a now-invalid action raises and the request stays pending.
    result = await apply_approved(db, ar, current_user, request)

    ar.status = "approved"
    ar.decided_by = current_user.id
    ar.decided_by_name = (getattr(current_user, "full_name", None) or getattr(current_user, "username", None) or "")
    ar.decided_at = datetime.now(timezone.utc)
    ar.decision_note = str((payload or {}).get("note") or "")[:500] or None
    ar.result = result

    try:
        from app.routers.audit import log_action
        await log_action(
            db, current_user.company_id, current_user.id, "approval_approve", "approval",
            entity_id=str(ar.id),
            details={"action_type": ar.action_type, "title": ar.title,
                     "maker": ar.requested_by_name, "result": result},
        )
    except Exception as exc:
        log.warning("approve audit failed: %s", exc)
    await db.commit()

    # Notify the maker their request was approved (best-effort).
    _notify_maker(current_user.company_id, ar, "approved")
    return {"ok": True, "status": "approved", "result": result}


@router.post("/{req_id}/reject")
async def reject_request(
    req_id: uuid.UUID,
    request: Request,
    payload: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Reject a pending request (nothing executes). The checker may be anyone;
    even the maker can withdraw their own request via reject."""
    ar = await _load_pending(db, req_id, current_user.company_id)
    ar.status = "rejected"
    ar.decided_by = current_user.id
    ar.decided_by_name = (getattr(current_user, "full_name", None) or getattr(current_user, "username", None) or "")
    ar.decided_at = datetime.now(timezone.utc)
    ar.decision_note = str((payload or {}).get("note") or "")[:500] or None

    try:
        from app.routers.audit import log_action
        await log_action(
            db, current_user.company_id, current_user.id, "approval_reject", "approval",
            entity_id=str(ar.id),
            details={"action_type": ar.action_type, "title": ar.title,
                     "maker": ar.requested_by_name, "note": ar.decision_note},
        )
    except Exception as exc:
        log.warning("reject audit failed: %s", exc)
    await db.commit()

    _notify_maker(current_user.company_id, ar, "rejected")
    return {"ok": True, "status": "rejected"}


def _notify_maker(company_id: uuid.UUID, ar: ApprovalRequest, decision: str) -> None:
    from app.services.approvals import _fire_notification, _tenant_slug
    _fire_notification(
        company_id, "approval_decided",
        {
            "action": ACTION_LABELS.get(ar.action_type, ar.action_type),
            "title": ar.title,
            "decision": decision.upper(),
            "decided_by": ar.decided_by_name or "",
        },
        _tenant_slug(),
    )

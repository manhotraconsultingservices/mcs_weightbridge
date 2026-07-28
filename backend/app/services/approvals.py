"""
Maker-checker (4-eyes) approval engine.

When a tenant turns the ``maker_checker`` control ON (Settings → Approvals),
sensitive money actions are PARKED as a pending ``approval_requests`` row instead
of executing. A second admin — the *checker*, who must differ from the *maker*
who submitted — approves (the real action then runs, replayed from the stored
``payload``) or rejects (discarded). Every submit/approve/reject is audit-logged.

Design:
- ``maker_checker_enabled(db)`` reads the per-tenant ``app_settings.maker_checker``
  toggle (default OFF → the whole feature is inert; endpoints behave exactly as
  before).
- Each protected endpoint runs its normal validation first, then — right before
  the first mutation — calls ``submit_approval(...)`` when the toggle is ON and
  the call is NOT itself an approval replay. ``submit_approval`` returns a 202
  ``JSONResponse`` which the endpoint returns instead of mutating. Because it is
  a ``Response`` instance, FastAPI skips ``response_model`` validation.
- ``apply_approved(...)`` re-invokes the same endpoint function with
  ``_bypass_approval=True``, acting as the ORIGINAL maker (so the financial
  mutation is attributed to who initiated it), and records the checker on the
  approval row.
- Re-validation happens on apply (state may have changed since submit), so a
  now-invalid action fails cleanly at approval time rather than parking a doomed
  request.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)

MAKER_CHECKER_KEY = "maker_checker"

# action_type → human label (used in the approval title + queue)
ACTION_LABELS = {
    "write_off": "Write off invoice",
    "write_off_bulk": "Bulk write-off",
    "invoice_cancel": "Cancel invoice",
    "day_book_opening": "Change Day Book opening balance",
}
PROTECTED_ACTIONS = set(ACTION_LABELS.keys())

# Keep strong refs to fire-and-forget notification tasks so they aren't GC'd.
_bg_refs: set = set()


async def maker_checker_enabled(db: AsyncSession) -> bool:
    """True when the tenant's maker_checker control is switched ON."""
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key = :k"),
            {"k": MAKER_CHECKER_KEY},
        )).fetchone()
        if not row or row[0] is None:
            return False
        raw = row[0]
        cfg = json.loads(raw) if isinstance(raw, str) else raw
        return bool(cfg.get("enabled")) if isinstance(cfg, dict) else False
    except Exception as exc:  # never let a config read break a real action
        _log.warning("maker_checker_enabled read failed: %s", exc)
        return False


async def get_maker_checker_config(db: AsyncSession) -> dict:
    """Return the raw config dict (defaults applied)."""
    out = {"enabled": False}
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key = :k"),
            {"k": MAKER_CHECKER_KEY},
        )).fetchone()
        if row and row[0] is not None:
            raw = row[0]
            cfg = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(cfg, dict):
                out.update(cfg)
    except Exception as exc:
        _log.warning("get_maker_checker_config read failed: %s", exc)
    return out


def _fire_notification(company_id: uuid.UUID, event_type: str, context: dict,
                       tenant_slug: str | None) -> None:
    """Best-effort fire-and-forget owner/checker notification (never blocks)."""
    import asyncio

    async def _run():
        try:
            from app.database import get_tenant_session
            from app.integrations.notifications.service import send_notification
            async with await get_tenant_session(tenant_slug) as ndb:
                await send_notification(ndb, company_id, event_type, context, "approval", None)
        except Exception as exc:
            _log.warning("approval notification failed [%s]: %s", event_type, exc)

    try:
        task = asyncio.create_task(_run())
        _bg_refs.add(task)
        task.add_done_callback(_bg_refs.discard)
    except RuntimeError:
        # No running loop (e.g. called from a script) — skip silently.
        pass


def _tenant_slug() -> str | None:
    try:
        from app.multitenancy.context import current_tenant_slug
        return current_tenant_slug.get()
    except Exception:
        return None


async def submit_approval(
    db: AsyncSession,
    company_id: uuid.UUID,
    user,
    action_type: str,
    title: str,
    payload: dict,
    amount=None,
) -> JSONResponse:
    """Park a pending approval request and return a 202 JSONResponse.

    Commits the row (so it survives even though the endpoint won't mutate),
    writes an audit entry, and fires a best-effort checker notification.
    """
    from app.models.approval import ApprovalRequest

    ar = ApprovalRequest(
        company_id=company_id,
        action_type=action_type,
        title=title[:300],
        amount=amount,
        payload=payload or {},
        status="pending",
        requested_by=getattr(user, "id", None),
        requested_by_name=(getattr(user, "full_name", None) or getattr(user, "username", None) or ""),
        requested_at=datetime.now(timezone.utc),
    )
    db.add(ar)
    await db.flush()

    try:
        from app.routers.audit import log_action
        await log_action(
            db, company_id, getattr(user, "id", None), "approval_submit", "approval",
            entity_id=str(ar.id),
            details={"action_type": action_type, "title": title, "amount": str(amount) if amount is not None else None},
        )
    except Exception as exc:
        _log.warning("approval submit audit failed: %s", exc)

    await db.commit()

    _fire_notification(
        company_id, "approval_requested",
        {
            "action": ACTION_LABELS.get(action_type, action_type),
            "title": title,
            "amount": f"{float(amount):.2f}" if amount is not None else "",
            "requested_by": ar.requested_by_name or "",
        },
        _tenant_slug(),
    )

    return JSONResponse(
        status_code=202,
        content={
            "status": "pending_approval",
            "approval_id": str(ar.id),
            "action_type": action_type,
            "title": title,
            "message": "Submitted for approval — a second admin must approve before it takes effect.",
        },
    )


async def apply_approved(db: AsyncSession, ar, checker, request) -> dict:
    """Execute the real action for an approved request, as the original maker.

    Raises HTTPException on any re-validation failure (surfaced to the checker);
    the request stays pending in that case so it can be retried or rejected.
    Returns a light result summary stored on the approval row by the caller.
    """
    from app.models.user import User
    from starlette.background import BackgroundTasks as _BT

    maker = None
    if ar.requested_by:
        maker = (await db.execute(select(User).where(User.id == ar.requested_by))).scalar_one_or_none()
    if maker is None:
        maker = checker  # fall back — attribute to the checker if the maker is gone

    payload = ar.payload or {}
    bt = _BT()

    from app.routers import invoices as _inv

    result_summary: dict = {"action_type": ar.action_type}

    if ar.action_type == "write_off":
        body = _inv.WriteOffRequest(**(payload.get("body") or {}))
        inv = await _inv.write_off_invoice(
            uuid.UUID(payload["invoice_id"]), body, bt, db, maker, request=request,
            _bypass_approval=True,
        )
        result_summary.update({"invoice_no": getattr(inv, "invoice_no", None)})

    elif ar.action_type == "write_off_bulk":
        body = _inv._BulkWriteOffRequest(**(payload.get("body") or {}))
        res = await _inv.write_off_bulk(body, bt, db, maker, request=request, _bypass_approval=True)
        result_summary.update(res if isinstance(res, dict) else {})

    elif ar.action_type == "invoice_cancel":
        inv = await _inv.cancel_invoice(
            uuid.UUID(payload["invoice_id"]), db, maker, request=request, _bypass_approval=True,
        )
        result_summary.update({"invoice_no": getattr(inv, "invoice_no", None)})

    elif ar.action_type == "day_book_opening":
        from app.routers import reports as _rep
        body = dict(payload.get("body") or {})  # this endpoint takes a plain dict
        res = await _rep.put_day_book_opening(body, request, db, maker, _bypass_approval=True)
        result_summary.update(res if isinstance(res, dict) else {})

    else:
        raise HTTPException(400, f"Unknown approval action_type '{ar.action_type}'")

    # Run any notifications the applied endpoint queued (write-off etc.).
    try:
        await bt()
    except Exception as exc:
        _log.warning("post-apply background tasks failed: %s", exc)

    return result_summary

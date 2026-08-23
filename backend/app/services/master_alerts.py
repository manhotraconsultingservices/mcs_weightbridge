"""Telegram alerts for master-data changes (items, parties, pricing).

Rates and master records drive every invoice, so a quiet edit is exactly the kind
of change an owner wants to hear about. The audit trail already records these; this
pushes the same facts — what changed, from what to what, by whom, when — to the
people who asked to be told.

Deliberately non-blocking and never fatal: an alert must not be able to fail a save.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.timefmt import fmt_ist

logger = logging.getLogger(__name__)

SETTING_KEY = "master_change_alert.enabled"


def _fmt(v: Any) -> str:
    """A value as a person reads it. Blank/None shows as an em dash."""
    if v is None or v == "":
        return "—"
    if isinstance(v, Decimal):
        return f"{v:,.2f}".rstrip("0").rstrip(".") if v % 1 else f"{v:,.0f}"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


def diff_fields(before: dict, after: dict, labels: dict[str, str]) -> list[dict]:
    """Changed fields only, as [{field, from, to}] — the shape the template renders.

    `labels` both names the field for a human AND decides what is worth reporting:
    anything not listed is ignored, so internal bookkeeping columns never surface.
    """
    out: list[dict] = []
    for key, label in labels.items():
        old, new = before.get(key), after.get(key)
        # compare as text so Decimal('5.00') and 5.0 do not read as a change
        if _fmt(old) == _fmt(new):
            continue
        out.append({"field": label, "from": _fmt(old), "to": _fmt(new)})
    return out


async def _alerts_enabled(db: AsyncSession) -> bool:
    """On unless a tenant has explicitly turned it off."""
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key = :k"), {"k": SETTING_KEY}
        )).fetchone()
    except Exception:
        return True
    if not row or row[0] is None:
        return True
    return str(row[0]).strip().lower() not in ("false", "0", "no", "off")


async def notify_master_change(
    db: AsyncSession,
    company_id,
    *,
    entity: str,                  # "Item" | "Customer" | "Supplier" | "Pricing"
    name: str,
    action: str,                  # "created" | "updated"
    changes: Iterable[dict] | None = None,
    user=None,
) -> None:
    """Fire the master-data alert. Swallows everything — a notification must never
    be able to fail the save it is reporting on."""
    try:
        if not await _alerts_enabled(db):
            return
        rows = list(changes or [])
        # An "updated" with nothing actually different is noise, not news.
        if action == "updated" and not rows:
            return

        lines = [
            f"• {c.get('field')}: <b>{c.get('from')}</b> → <b>{c.get('to')}</b>"
            for c in rows
        ]
        who = ""
        if user is not None:
            who = (getattr(user, "full_name", "") or "").strip() or getattr(user, "username", "") or ""

        company_name = ""
        try:
            company_name = (await db.execute(
                text("SELECT name FROM companies WHERE id = :c"), {"c": str(company_id)}
            )).scalar() or ""
        except Exception:
            pass

        from datetime import datetime, timezone as _tz
        ctx = {
            "entity": entity,
            "name": name or "—",
            "action": action,
            "changes": "\n".join(lines),
            "change_count": len(rows),
            "updated_by": who,
            "updated_at": fmt_ist(datetime.now(_tz.utc)),
            "company_name": company_name,
        }
        from app.integrations.notifications.service import send_notification
        await send_notification(db, company_id, "master_data_updated", ctx,
                                entity_type="master", entity_id=None)
    except Exception as e:  # noqa: BLE001
        logger.warning("master_data_updated alert skipped: %s", str(e)[:160])

"""Telegram alerts for master-data changes (items, parties, pricing).

Rates and master records drive every invoice, so a quiet edit is exactly the kind
of change an owner wants to hear about. The audit trail already records these; this
pushes the same facts — what changed, from what to what, by whom, when — to the
people who asked to be told.

Deliberately non-blocking and never fatal: an alert must not be able to fail a save.
"""
from __future__ import annotations

import html
import logging
from decimal import Decimal
from typing import Any, Iterable

from markupsafe import Markup
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


def _esc(v) -> str:
    """Neutralise anything in a product or party name that would break the markup."""
    return html.escape(str(v if v is not None else "—"), quote=False)


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
    lines: list[str] | None = None,
    user=None,
) -> None:
    """Fire the master-data alert. Swallows everything — a notification must never
    be able to fail the save it is reporting on.

    Pass `changes` for the usual field/from/to rows, or `lines` when the caller has
    already formatted them (a roll-up across several items).
    """
    try:
        if not await _alerts_enabled(db):
            return
        rows = list(changes or [])
        # An "updated" with nothing actually different is noise, not news.
        if action == "updated" and not rows and not lines:
            return

        # These lines carry deliberate <b> markup, but the renderer autoescapes
        # string templates — so the values are escaped here and the whole block is
        # handed over as Markup. Without this the owner sees a literal "&lt;b&gt;".
        lines = lines or [
            f"• {_esc(c.get('field'))}: "
            f"<b>{_esc(c.get('from'))}</b> → <b>{_esc(c.get('to'))}</b>"
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
            "changes": Markup("\n".join(lines)),
            "change_count": len(rows) or len(lines),
            "updated_by": who,
            "updated_at": fmt_ist(datetime.now(_tz.utc)),
            "company_name": company_name,
        }
        # Sending is deliberately NOT awaited here. Telegram allows 15s per
        # recipient, and a rate save must not sit waiting on it — an alert is
        # informational, the save is not. The task opens its own tenant-routed
        # session because this request's one is closed by the time it runs.
        _dispatch(company_id, ctx, _current_tenant())
    except Exception as e:  # noqa: BLE001
        logger.warning("master_data_updated alert skipped: %s", str(e)[:160])


def rate_label(unit: str | None) -> str:
    """A rate cell named the way the owner reads it on the Pricing screen."""
    u = (unit or "").strip()
    if not u:
        return "Rate"
    low = u.lower()
    if low.startswith("royalty/"):
        return f"Royalty (per {u.split('/', 1)[1].upper()})"
    if low == "default_rate":
        return "Rate"
    if low == "gst_rate":
        return "GST %"
    return f"Rate ({u.upper()})"


# Above this many items in one save, a per-item alert becomes spam — send one
# roll-up instead. Detail is kept: the roll-up still names each from -> to.
_MAX_INDIVIDUAL = 3
_MAX_ROLLUP_LINES = 12


async def notify_pricing_change(
    db: AsyncSession,
    company_id,
    *,
    entity: str,                       # "Pricing" | "Customer pricing" | ...
    groups: list[tuple[str, list[dict]]],   # [(item name, [{field, from, to}]), ...]
    user=None,
) -> None:
    """Alert on a rate save.

    A matrix save can touch dozens of cells across many products; one Telegram
    message per cell would be unusable. So: a few items get an alert each (the
    normal case — an owner correcting one rate), and a wide save collapses into a
    single roll-up that still names every from -> to it has room for.
    """
    groups = [(n, [c for c in ch if c]) for n, ch in groups if ch]
    if not groups:
        return
    if len(groups) <= _MAX_INDIVIDUAL:
        for name, changes in groups:
            await notify_master_change(db, company_id, entity=entity, name=name,
                                       action="updated", changes=changes, user=user)
        return

    flat: list[str] = []
    total = 0
    for name, changes in groups:
        for c in changes:
            total += 1
            if len(flat) < _MAX_ROLLUP_LINES:
                flat.append(f"• {_esc(name)} — {_esc(c.get('field'))}: "
                            f"<b>{_esc(c.get('from'))}</b> → <b>{_esc(c.get('to'))}</b>")
    if total > len(flat):
        flat.append(f"…and {total - len(flat)} more")
    await notify_master_change(
        db, company_id, entity=entity,
        name=f"{len(groups)} items updated",
        action="updated", lines=flat, user=user,
    )


def _current_tenant() -> str | None:
    """Which tenant this request belongs to, so the detached send targets its DB."""
    try:
        from app.multitenancy.context import current_tenant_slug
        return current_tenant_slug.get()
    except Exception:
        return None


# A task that nothing holds a reference to can be garbage-collected mid-flight.
_INFLIGHT: set = set()


def _dispatch(company_id, ctx: dict, tenant_slug: str | None) -> None:
    import asyncio

    async def _run() -> None:
        try:
            from app.database import get_tenant_session
            from app.integrations.notifications.service import send_notification
            async with await get_tenant_session(tenant_slug) as db:
                await send_notification(db, company_id, "master_data_updated", ctx,
                                        entity_type="master", entity_id=None)
        except Exception as e:  # noqa: BLE001
            logger.warning("master_data_updated send failed: %s", str(e)[:160])

    try:
        task = asyncio.create_task(_run())
        _INFLIGHT.add(task)
        task.add_done_callback(_INFLIGHT.discard)
    except RuntimeError:
        # No running loop (a script or a test) — nothing to send to.
        logger.debug("master_data_updated: no event loop, alert skipped")

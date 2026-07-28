"""
Financial sanity guards — stop physically-impossible / fat-finger invoices from
entering the books (audit findings #1 + #2).

The weighbridge audit surfaced FINAL invoices like a ₹236-crore Bill of Supply
(590 MT × ₹40,00,000/MT), 53,788-MT truck weights, and the KG-vs-MT 1000× trap
(Sand-60mm `unit=KG, rate=₹550` billed on a full-kg quantity → ₹1.32 crore).
The engine did the arithmetic faithfully; nothing sanity-checked the inputs.

This module normalises each line and rejects values outside a generous, tenant-
configurable band. Defaults are set so **no realistic stone-crusher / grain
invoice** hits them, while the garbage above is blocked:

    max_qty_mt        100     (no single truck weighs 100 MT)
    max_rate_per_unit 500000  (₹5 lakh/unit — catches ₹40-lakh/MT & the KG trap's ₹/MT)
    max_line_amount   10000000 (₹1 crore per line — catches ₹236cr & the 1000× amounts)

Applied as a HARD block at ``finalise_invoice`` (the single gate into the books /
GST). The physical weighment + the draft are preserved; the operator fixes the
rate/weight/unit and re-finalises. An admin can widen the band per tenant via
``app_settings.sanity_limits``.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)

SANITY_KEY = "sanity_limits"

DEFAULT_SANITY_LIMITS = {
    "enabled": True,
    "max_qty_mt": 100.0,
    "max_rate_per_unit": 500000.0,
    "max_line_amount": 10000000.0,
}

# weight-unit → tonnes-per-unit (for the physical-quantity guard)
_WEIGHT_TO_MT = {
    "MT": 1.0, "TON": 1.0, "TONNE": 1.0, "TONNES": 1.0,
    "QUINTAL": 0.1, "QTL": 0.1, "QUINTALS": 0.1,
    "KG": 0.001, "KGS": 0.001, "KILOGRAM": 0.001,
}


async def get_sanity_limits(db: AsyncSession) -> dict:
    """Read the per-tenant sanity band (app_settings), merged over defaults."""
    out = dict(DEFAULT_SANITY_LIMITS)
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key = :k"),
            {"k": SANITY_KEY},
        )).fetchone()
        if row and row[0] is not None:
            cfg = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            if isinstance(cfg, dict):
                out.update({k: cfg[k] for k in DEFAULT_SANITY_LIMITS if k in cfg})
    except Exception as exc:
        _log.warning("sanity limits read failed: %s", exc)
    return out


def check_line_sanity(items, net_weight_kg, cfg: dict) -> list[str]:
    """Return a list of human-readable problems (empty = clean).

    ``items`` is any iterable of objects/dicts exposing ``unit``, ``rate``,
    ``quantity`` and ``amount``. ``net_weight_kg`` is the invoice/token net
    weight in kg (0/None to skip that guard).
    """
    def _f(v):
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    def _get(it, name):
        return getattr(it, name, None) if not isinstance(it, dict) else it.get(name)

    max_qty_mt = _f(cfg.get("max_qty_mt")) or DEFAULT_SANITY_LIMITS["max_qty_mt"]
    max_rate = _f(cfg.get("max_rate_per_unit")) or DEFAULT_SANITY_LIMITS["max_rate_per_unit"]
    max_amt = _f(cfg.get("max_line_amount")) or DEFAULT_SANITY_LIMITS["max_line_amount"]

    errs: list[str] = []
    for it in (items or []):
        unit = str(_get(it, "unit") or "").upper().strip()
        qty = _f(_get(it, "quantity"))
        rate = _f(_get(it, "rate"))
        amt = _f(_get(it, "amount"))
        label = unit or "unit"
        if rate > max_rate:
            errs.append(f"rate ₹{rate:,.0f}/{label} exceeds the ₹{max_rate:,.0f} limit — check the rate & unit")
        if amt > max_amt:
            errs.append(f"line amount ₹{amt:,.0f} exceeds the ₹{max_amt:,.0f} limit — check qty × rate & the unit")
        f = _WEIGHT_TO_MT.get(unit)
        if f is not None:
            qmt = qty * f
            if qmt > max_qty_mt:
                errs.append(f"quantity {qty:,.0f} {unit} = {qmt:,.1f} MT exceeds the {max_qty_mt:.0f} MT limit — check the weight & unit")

    nw = _f(net_weight_kg)
    if nw and (nw / 1000.0) > max_qty_mt:
        errs.append(f"net weight {nw/1000.0:,.1f} MT exceeds the {max_qty_mt:.0f} MT physical limit — check the scale/entry")
    return errs

"""Unit-aware rate resolution + token→invoice quantity conversion.

Single source of truth for "what rate applies" and "how much quantity" — replaces
the five duplicated `party_rate → product.default_rate → 0` ladders and the
hard-coded kg `_div` maps that used to live in tokens.py / invoices.py.

Units are classified as WEIGHT (billed off the token's net_weight in kg) or
VOLUME (billed off the token's measured volume_cft). Cross-billing a weighed
truck in a volume unit is BLOCKED at token creation (validate_billing_unit) —
no kg↔volume density conversion happens at billing time.
"""
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.party import PartyRate
from app.models.product import Product
from app.models.product_unit_rate import ProductUnitRate

# 1 m³ = 35.3147 CFT · 1 Brass = 100 CFT (Indian aggregate trade)
CFT_PER_M3 = Decimal("35.3147")
CFT_PER_BRASS = Decimal("100")

WEIGHT_UNITS = {"MT", "QUINTAL", "KG"}
VOLUME_UNITS = {"CFT", "CBM", "CUM", "BRASS"}


def norm_unit(u) -> str:
    return (u or "").strip().upper()


def validate_billing_unit(unit, weight_method, product_name: str = "product") -> None:
    """Reject a volume billing unit on a weighed (non-volume) token — raises 400.

    Called at token creation so the operator fixes it immediately, rather than
    failing later during auto-invoicing.
    """
    u = norm_unit(unit)
    if u in VOLUME_UNITS and (weight_method or "").lower() != "volume":
        raise HTTPException(
            400,
            f"Billing unit {u} needs a volume-measured token — '{product_name}' is being "
            f"weighed on the bridge. Pick a weight unit (MT / QUINTAL / KG), or create a "
            f"Volume token to bill by {u}.",
        )


async def resolve_rate(db: AsyncSession, party_id, product_id, unit) -> Decimal:
    """Return the applicable rate for (party, product, unit). Priority:

      1. customer rate for this exact unit
      2. customer legacy rate (unit IS NULL) — only for the product's base unit
      3. product default rate for this unit (product_unit_rates)
      4. product.default_rate — only for the product's base unit
      5. 0
    """
    u = norm_unit(unit)
    prod = None
    if product_id:
        prod = (await db.execute(select(Product).where(Product.id == product_id))).scalar_one_or_none()
    base_unit = norm_unit(prod.unit) if prod else ""
    if not u:                          # no unit given → resolve for the product's base unit (legacy)
        u = base_unit

    if party_id and product_id:
        rows = (await db.execute(
            select(PartyRate).where(
                PartyRate.party_id == party_id,
                PartyRate.product_id == product_id,
                PartyRate.effective_from <= date.today(),
            ).order_by(PartyRate.effective_from.desc())
        )).scalars().all()
        for pr in rows:                                    # 1) explicit unit match
            if norm_unit(pr.unit) == u:
                return pr.rate
        if u == base_unit:                                 # 2) legacy NULL rate = base unit
            for pr in rows:
                if pr.unit is None:
                    return pr.rate

    if product_id:                                         # 3) product per-unit default
        pur = (await db.execute(
            select(ProductUnitRate).where(
                ProductUnitRate.product_id == product_id,
                func.upper(ProductUnitRate.unit) == u,
            )
        )).scalar_one_or_none()
        if pur:
            return pur.rate

    if prod and u == base_unit and prod.default_rate:      # 4) legacy single default
        return prod.default_rate
    return Decimal("0")                                    # 5


def token_quantity(token, unit, product=None) -> Decimal:
    """Billable quantity for a token in the given unit (3 dp).

    VOLUME unit → derived from token.volume_cft (CFT as-is · CBM=÷35.3147 · Brass=÷100).
    WEIGHT unit → derived from token.net_weight kg (MT ÷1000 · QUINTAL ÷100 · KG/other as-is).
    Defensive: a volume unit without volume_cft falls back to weight (creation-time
    validation already prevents that combo).
    """
    u = norm_unit(unit)
    vol = getattr(token, "volume_cft", None)
    if u in VOLUME_UNITS and vol and Decimal(str(vol)) > 0:
        vol = Decimal(str(vol))
        if u == "CFT":
            q = vol
        elif u in ("CBM", "CUM"):
            q = vol / CFT_PER_M3
        else:  # BRASS
            q = vol / CFT_PER_BRASS
        return q.quantize(Decimal("0.001"))

    net = Decimal(str(getattr(token, "net_weight", None) or 0))
    if u == "MT":
        q = net / Decimal("1000")
    elif u == "QUINTAL":
        q = net / Decimal("100")
    else:  # KG or any other → raw kg (legacy behaviour)
        q = net
    return q.quantize(Decimal("0.001"))


# ── Per-item royalty (govt mineral charge, ₹ per MT or per CUM) ────────────────

def _to_cft(qty: Decimal, u: str) -> Decimal | None:
    """A volume quantity → cubic FEET, or None if `u` is not a volume unit."""
    if u == "CFT":
        return qty
    if u in ("CBM", "CUM"):
        return qty * CFT_PER_M3
    if u == "BRASS":
        return qty * CFT_PER_BRASS
    return None


def _to_kg(qty: Decimal, u: str) -> Decimal | None:
    """A weight quantity → kilograms, or None if `u` is not a weight unit."""
    if u == "MT":
        return qty * Decimal("1000")
    if u == "QUINTAL":
        return qty * Decimal("100")
    if u == "KG":
        return qty
    return None


def royalty_quantity(quantity, line_unit, royalty_unit, product=None) -> Decimal:
    """Convert a line's billed quantity into the ROYALTY unit (MT or CUM), 3 dp.

    Royalty is levied per metric tonne (``mt``) or per cubic metre (``cum``).
    - Same dimension (weight↔weight / volume↔volume) → exact unit conversion.
    - Cross dimension (a weight-billed line charged royalty/CUM, or a
      volume-billed line charged royalty/MT) → converted via the product's
      ``bulk_density`` (kg per CFT). Returns 0 when that bridge is needed but the
      product has no bulk_density (can't derive — the UI flags it), so a wrong
      number is never invented.
    """
    q = Decimal(str(quantity or 0))
    lu = norm_unit(line_unit)
    ru = norm_unit(royalty_unit)
    if q <= 0 or ru not in ("MT", "CUM"):
        return Decimal("0")

    density = None  # kg per CFT
    bd = getattr(product, "bulk_density", None) if product is not None else None
    if bd:
        try:
            density = Decimal(str(bd))
        except Exception:
            density = None

    if ru == "MT":
        kg = _to_kg(q, lu)
        if kg is None:                       # line is a volume → bridge via density
            cft = _to_cft(q, lu)
            if cft is None or not density or density <= 0:
                return Decimal("0")
            kg = cft * density
        return (kg / Decimal("1000")).quantize(Decimal("0.001"))

    # ru == "CUM" → cubic metres
    cft = _to_cft(q, lu)
    if cft is None:                          # line is a weight → bridge via density
        kg = _to_kg(q, lu)
        if kg is None or not density or density <= 0:
            return Decimal("0")
        cft = kg / density
    return (cft / CFT_PER_M3).quantize(Decimal("0.001"))


def line_royalty(quantity, line_unit, royalty_unit, royalty_rate, product=None) -> Decimal:
    """₹ royalty for one line = rate × quantity-in-royalty-unit (2 dp).

    Returns 0 when the rate is unset/≤0 or the royalty unit is blank (royalty not
    opted in for this line).
    """
    try:
        rate = Decimal(str(royalty_rate or 0))
    except Exception:
        return Decimal("0")
    if rate <= 0 or not (royalty_unit or "").strip():
        return Decimal("0")
    qty = royalty_quantity(quantity, line_unit, royalty_unit, product)
    return (rate * qty).quantize(Decimal("0.01"))


def line_vehicle_fare(quantity, line_unit, fare_unit, fare_rate, km, product=None) -> Decimal:
    """₹ vehicle fare (transport/hire) for one line, 2 dp:

        fare = (₹/km/MT or ₹/km/CUM) × total_km × quantity-in-fare-unit

    where total_km is the sum of the line's trip distances and quantity-in-unit is
    converted the same way as royalty (MT/CUM, density-aware). Returns 0 when the
    rate, km, or unit is unset (fare not opted in for this line).
    """
    try:
        rate = Decimal(str(fare_rate or 0))
        km_d = Decimal(str(km or 0))
    except Exception:
        return Decimal("0")
    if rate <= 0 or km_d <= 0 or not (fare_unit or "").strip():
        return Decimal("0")
    qty = royalty_quantity(quantity, line_unit, fare_unit, product)
    return (rate * km_d * qty).quantize(Decimal("0.01"))

"""Units for Tally: one base unit + ONE alternate unit per Stock Item.

Tally allows a stock item exactly one alternate unit, tied to the base by a
fixed conversion. The app bills the same product under several labels of one
dimension (CBM / CUM / CFT / BRASS are all volume; MT / QUINTAL / KG all
weight) and sometimes in the *other* dimension (a weight-based item sold by
volume). Live data (Sept 2026): sss bills MT items as CBM and CUM, manhotra as
CBM and CFT, megna bills QUINTAL items in MT. So for Tally:

* base unit   = ``product.unit``, exactly as the Stock Item master already says;
* alternate   = ONE canonical unit of the OTHER dimension — the tenant's volume
  unit (default CUM) for a weight-based item, MT for a volume-based item — and
  it exists only when the product has a ``bulk_density`` (kg per CFT), because
  that is the only bridge between the two dimensions;
* a voucher line is converted EXACTLY into whichever of those two units shares
  its dimension (10 CBM → 10 CUM · 5 BRASS → 14.158 CUM · 45 MT → 450 QUINTAL).
  The amount is never touched; the rate scales inversely so qty × rate holds.

Nothing here talks to a database — pure arithmetic on plain attributes.
"""
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace

from app.services.pricing import (
    WEIGHT_UNITS, VOLUME_UNITS, CFT_PER_M3, CFT_PER_BRASS, norm_unit,
)

DEFAULT_VOLUME_UNIT = "CUM"
WEIGHT_ALT_UNIT = "MT"
_Q3 = Decimal("0.001")
_Q2 = Decimal("0.01")
_Q4 = Decimal("0.0001")


def canonical_volume_unit(cfg) -> str:
    """The tenant's chosen volume unit for Tally (``tally_config.volume_unit``)."""
    u = norm_unit(getattr(cfg, "volume_unit", None)) if cfg is not None else ""
    return u if u in VOLUME_UNITS else DEFAULT_VOLUME_UNIT


def dimension(unit) -> str | None:
    u = norm_unit(unit)
    if u in WEIGHT_UNITS:
        return "weight"
    if u in VOLUME_UNITS:
        return "volume"
    return None


def _cft_per(unit) -> Decimal | None:
    """How many cubic FEET make one <volume unit>."""
    u = norm_unit(unit)
    if u == "CFT":
        return Decimal("1")
    if u in ("CBM", "CUM"):
        return CFT_PER_M3
    if u == "BRASS":
        return CFT_PER_BRASS
    return None


def _kg_per(unit) -> Decimal | None:
    """How many kilograms make one <weight unit>."""
    u = norm_unit(unit)
    if u == "MT":
        return Decimal("1000")
    if u == "QUINTAL":
        return Decimal("100")
    if u == "KG":
        return Decimal("1")
    return None


def _per(unit) -> Decimal | None:
    return _cft_per(unit) if dimension(unit) == "volume" else _kg_per(unit)


def _density(product) -> Decimal | None:
    bd = getattr(product, "bulk_density", None)
    if bd is None:
        return None
    try:
        d = Decimal(str(bd))
    except Exception:
        return None
    return d if d > 0 else None


def alternate_unit(product, volume_unit: str = DEFAULT_VOLUME_UNIT):
    """``(alt_symbol, conversion)`` where 1 alt = ``conversion`` base units, or
    ``None`` when the item can't have one: its unit is neither weight nor volume
    (NOS, PCS, L…), or it has no bulk density to bridge the two dimensions."""
    base = norm_unit(getattr(product, "unit", None))
    density = _density(product)          # kg per CFT
    if density is None:
        return None
    if base in WEIGHT_UNITS:
        alt = norm_unit(volume_unit)
        if alt not in VOLUME_UNITS:
            alt = DEFAULT_VOLUME_UNIT
        kg_per_alt = _cft_per(alt) * density         # 1 alt volume → kg
        return alt, kg_per_alt / _kg_per(base)       # → base weight units
    if base in VOLUME_UNITS:
        cft_per_mt = Decimal("1000") / density       # 1 MT → CFT
        return WEIGHT_ALT_UNIT, cft_per_mt / _cft_per(base)
    return None


def format_conversion(conv: Decimal) -> str:
    """Tally's CONVERSION field: up to 4 decimals, trailing zeros dropped."""
    s = f"{conv.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP):f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def convert_line(quantity, rate, line_unit, product,
                 volume_unit: str = DEFAULT_VOLUME_UNIT, amount=None):
    """Express one invoice line in a unit the Tally Stock Item knows.

    Returns ``(qty, rate, unit, note)``:
      * line unit is the base (any case)        → unchanged, base spelled as the master;
      * same dimension as the base              → exact conversion to the base;
      * same dimension as the item's alternate  → exact conversion to the alternate;
      * anything else                           → unchanged, with a ``note`` saying
        why Tally will reject it (missing bulk density, or a unit of no known
        dimension). A wrong number is never invented.

    The AMOUNT is the authority: it is what the invoice, the GST return and the
    voucher's own ledger entries say. The quantity has to be rounded to the 3
    decimals Tally takes, so scaling the rate independently would leave
    ``qty x rate`` up to a rupee away from it (a BRASS→CUM line drifts ₹0.55 on
    ₹20,000). Pass ``amount`` and the rate is derived from the ROUNDED quantity
    instead, so the two agree and Tally cannot recompute a different figure.
    """
    base_raw = (getattr(product, "unit", None) or "").strip()
    base = norm_unit(base_raw)
    lu = norm_unit(line_unit)
    q = Decimal(str(quantity or 0))
    r = Decimal(str(rate or 0))
    if not lu or lu == base:
        return q, r, (base_raw or line_unit or "Nos"), None

    ld, bd = dimension(lu), dimension(base)
    target = None
    if ld is not None and ld == bd:
        target = base_raw                               # exact, same dimension
    else:
        alt = alternate_unit(product, volume_unit)
        if alt is not None and dimension(alt[0]) == ld:
            target = alt[0]
    if target is None:
        if ld is None:
            note = f"unit '{line_unit}' has no known dimension — Tally cannot take it"
        elif bd is None:
            note = f"item is in '{base_raw}' (no weight/volume) but the line is in '{line_unit}'"
        else:
            note = (f"line is billed in '{line_unit}' but the product has no bulk density, "
                    f"so it cannot be converted to the item's '{base_raw}' — set the density")
        return q, r, (line_unit or "Nos"), note

    factor = _per(lu) / _per(target)                    # line units → target units
    q2 = (q * factor).quantize(_Q3, rounding=ROUND_HALF_UP)
    if amount is not None and q2 > 0:
        # 4 dp, not 2: at 2 the rate's own rounding still moves a ₹20,000 line by
        # 1.5 paise against the amount. Tally takes fractional rates.
        r2 = (Decimal(str(amount)) / q2).quantize(_Q4, rounding=ROUND_HALF_UP)
    else:
        r2 = (r / factor).quantize(_Q2, rounding=ROUND_HALF_UP) if factor else r
    return q2, r2, target, None


def line_product(unit, bulk_density=None):
    """Plain product stand-in for ``convert_line`` / ``alternate_unit``."""
    return SimpleNamespace(unit=unit, bulk_density=bulk_density)

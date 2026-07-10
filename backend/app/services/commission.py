"""Agent commission calculation.

compute_commission(agent, invoice) returns the commission (2dp Decimal) an
agent earns on ONE invoice, per the agent's configured basis. Called at
finalise time to SNAPSHOT the amount onto invoices.commission_amount so the
report card is a simple SUM and later rate changes don't rewrite history.
"""
from decimal import Decimal, ROUND_HALF_UP


def compute_commission(agent, invoice) -> Decimal:
    if agent is None or invoice is None:
        return Decimal("0")
    rate = Decimal(str(getattr(agent, "commission_rate", 0) or 0))
    if rate <= 0:
        return Decimal("0")
    ctype = getattr(agent, "commission_type", None) or "pct_of_taxable"

    if ctype == "per_mt":
        # net_weight is stored in kg → MT
        mt = Decimal(str(invoice.net_weight or 0)) / Decimal("1000")
        amt = mt * rate
    elif ctype == "pct_of_taxable":
        amt = Decimal(str(invoice.taxable_amount or 0)) * rate / Decimal("100")
    elif ctype == "pct_of_grand_total":
        amt = Decimal(str(invoice.grand_total or 0)) * rate / Decimal("100")
    elif ctype == "flat_per_invoice":
        amt = rate
    else:
        amt = Decimal("0")

    return amt.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


COMMISSION_TYPES = ("per_mt", "pct_of_taxable", "pct_of_grand_total", "flat_per_invoice")

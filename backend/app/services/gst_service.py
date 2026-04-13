"""
GST calculation service for Indian GST (CGST/SGST vs IGST).

Rules:
- Intra-state (supplier state == buyer state): CGST + SGST (each = gst_rate / 2)
- Inter-state (different states): IGST (= gst_rate)
- Company state code is compared to party billing state code.
- Non-GST invoices: no tax applied.
"""
from decimal import Decimal, ROUND_HALF_UP


def _round2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def is_intra_state(company_state_code: str | None, party_state_code: str | None) -> bool:
    if not company_state_code or not party_state_code:
        return True  # default to intra-state when unknown
    return company_state_code.strip() == party_state_code.strip()


def calculate_item_gst(
    amount: Decimal,
    gst_rate: Decimal,
    intra_state: bool,
) -> dict[str, Decimal]:
    """
    Returns cgst, sgst, igst amounts for a line item.
    amount = taxable base (after any item-level discount)
    gst_rate = e.g. Decimal("5") for 5%
    """
    if gst_rate <= 0:
        return {"cgst": Decimal("0"), "sgst": Decimal("0"), "igst": Decimal("0")}

    total_tax = _round2(amount * gst_rate / 100)

    if intra_state:
        half = _round2(total_tax / 2)
        # Distribute rounding difference to CGST
        other_half = total_tax - half
        return {"cgst": other_half, "sgst": half, "igst": Decimal("0")}
    else:
        return {"cgst": Decimal("0"), "sgst": Decimal("0"), "igst": total_tax}


def calculate_invoice_totals(
    items: list[dict],          # each: {quantity, rate, gst_rate, ...}
    discount_type: str | None,  # "percentage" | "flat" | None
    discount_value: Decimal,
    freight: Decimal,
    tcs_rate: Decimal,
    intra_state: bool,
    tax_type: str = "gst",      # "gst" | "non_gst"
) -> dict:
    """
    Compute full invoice totals.
    Returns a dict with all monetary fields ready to persist.
    """
    # 1. Line subtotal
    subtotal = sum(
        _round2(Decimal(str(item["quantity"])) * Decimal(str(item["rate"])))
        for item in items
    )

    # 2. Discount
    if discount_type == "percentage":
        discount_amount = _round2(subtotal * discount_value / 100)
    elif discount_type == "flat":
        discount_amount = _round2(min(discount_value, subtotal))
    else:
        discount_amount = Decimal("0")

    taxable_amount = _round2(subtotal - discount_amount)

    # 3. GST per item (GST is on post-discount taxable amount per GST rules:
    #    invoice-level discounts reflected in the invoice reduce taxable value)
    total_cgst = Decimal("0")
    total_sgst = Decimal("0")
    total_igst = Decimal("0")

    computed_items = []
    for item in items:
        qty = Decimal(str(item["quantity"]))
        rate = Decimal(str(item["rate"]))
        gst_rate = Decimal(str(item.get("gst_rate", 0)))
        line_amount = _round2(qty * rate)

        # Apportion invoice-level discount proportionally across items
        # GST must be on taxable base (post-discount) per Indian GST law
        if discount_amount > 0 and subtotal > 0:
            item_discount = _round2(line_amount * discount_amount / subtotal)
        else:
            item_discount = Decimal("0")
        taxable_line_amount = line_amount - item_discount

        if tax_type == "gst":
            gst = calculate_item_gst(taxable_line_amount, gst_rate, intra_state)
        else:
            gst = {"cgst": Decimal("0"), "sgst": Decimal("0"), "igst": Decimal("0")}

        total_cgst += gst["cgst"]
        total_sgst += gst["sgst"]
        total_igst += gst["igst"]

        computed_items.append({
            **item,
            "amount": line_amount,               # line subtotal before discount (for display)
            "cgst_amount": gst["cgst"],
            "sgst_amount": gst["sgst"],
            "igst_amount": gst["igst"],
            "total_amount": taxable_line_amount + gst["cgst"] + gst["sgst"] + gst["igst"],
        })

    total_cgst = _round2(total_cgst)
    total_sgst = _round2(total_sgst)
    total_igst = _round2(total_igst)

    total_tax = total_cgst + total_sgst + total_igst
    total_amount = taxable_amount + total_tax + _round2(freight)

    # 4. TCS (Tax Collected at Source) — on invoice value
    tcs_amount = _round2(total_amount * tcs_rate / 100) if tcs_rate > 0 else Decimal("0")

    pre_round = total_amount + tcs_amount
    grand_total = _round2(pre_round)
    round_off = grand_total - pre_round

    return {
        "subtotal": subtotal,
        "discount_amount": discount_amount,
        "taxable_amount": taxable_amount,
        "cgst_amount": total_cgst,
        "sgst_amount": total_sgst,
        "igst_amount": total_igst,
        "freight": _round2(freight),
        "tcs_amount": tcs_amount,
        "total_amount": total_amount,
        "round_off": round_off,
        "grand_total": grand_total,
        "amount_due": grand_total,
        "computed_items": computed_items,
    }

"""
NIC eInvoice JSON payload builder (schema v1.1).

Maps internal Invoice + Company + Party models to the JSON structure
required by the NIC eInvoice API for IRN generation.

Reference: https://einvoice1.gst.gov.in/Others/VSignedInvoice
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any


# ── Unit mapping ─────────────────────────────────────────────────────────────

_UNIT_MAP: dict[str, str] = {
    "kg": "KGS",
    "kgs": "KGS",
    "mt": "MTS",
    "mts": "MTS",
    "ton": "MTS",
    "tonne": "MTS",
    "quintal": "QTL",
    "qtl": "QTL",
    "ltr": "LTR",
    "litre": "LTR",
    "nos": "NOS",
    "pcs": "PCS",
    "bags": "BAG",
    "bag": "BAG",
    "cft": "CFT",
    "cbm": "CBM",
    "sqm": "SQM",
    "sqf": "SQF",
    "gms": "GMS",
    "oth": "OTH",
}


def _nic_unit(unit: str | None) -> str:
    """Convert app unit to NIC-recognised unit code."""
    if not unit:
        return "OTH"
    return _UNIT_MAP.get(unit.lower().strip(), "OTH")


def _nic_date(d: date | datetime | None) -> str:
    """Format date as DD/MM/YYYY (NIC requirement)."""
    if d is None:
        d = date.today()
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%d/%m/%Y")


def _dec(v: Any) -> float:
    """Convert Decimal / None to float for JSON."""
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _round2(v: float) -> float:
    return round(v, 2)


# ── Main builder ─────────────────────────────────────────────────────────────

def build_einvoice_payload(
    invoice: Any,
    company: Any,
    party: Any,
    *,
    supply_type: str = "B2B",
) -> dict:
    """
    Build the NIC eInvoice JSON payload from internal models.

    Parameters
    ----------
    invoice : Invoice ORM object (with .items relationship loaded)
    company : Company ORM object
    party   : Party ORM object (buyer for sales, supplier for purchase)
    supply_type : "B2B" (default) — only B2B invoices generate IRN

    Returns
    -------
    dict — ready to POST to NIC /eicore/v1.03/Invoice
    """

    items_payload = []
    total_assessable = 0.0
    total_cgst = 0.0
    total_sgst = 0.0
    total_igst = 0.0
    total_item_val = 0.0

    for idx, item in enumerate(invoice.items, start=1):
        qty = _dec(item.quantity)
        rate = _dec(item.rate)
        amt = _round2(qty * rate)
        gst_rate = _dec(item.gst_rate)

        # Determine inter/intra state from GST
        cgst = _dec(item.cgst_amount)
        sgst = _dec(item.sgst_amount)
        igst = _dec(item.igst_amount)
        item_total = _round2(amt + cgst + sgst + igst)

        total_assessable += amt
        total_cgst += cgst
        total_sgst += sgst
        total_igst += igst
        total_item_val += item_total

        items_payload.append({
            "SlNo": str(idx),
            "PrdDesc": item.description or "Goods",
            "IsServc": "N",
            "HsnCd": item.hsn_code or "25169090",  # default HSN for stone/aggregate
            "Qty": qty,
            "FreeQty": 0,
            "Unit": _nic_unit(item.unit),
            "UnitPrice": rate,
            "TotAmt": _round2(amt),
            "Discount": 0,
            "PreTaxVal": _round2(amt),
            "AssAmt": _round2(amt),
            "GstRt": gst_rate,
            "IgstAmt": _round2(igst),
            "CgstAmt": _round2(cgst),
            "SgstAmt": _round2(sgst),
            "CesRt": 0,
            "CesAmt": 0,
            "CesNonAdvlAmt": 0,
            "StateCesRt": 0,
            "StateCesAmt": 0,
            "StateCesNonAdvlAmt": 0,
            "OthChrg": 0,
            "TotItemVal": _round2(item_total),
        })

    # ── Discount handling ────────────────────────────────────────────────────
    discount_amt = _dec(invoice.discount_amount)

    # ── Document type ────────────────────────────────────────────────────────
    inv_type = invoice.invoice_type  # sale / purchase
    doc_type = "INV"  # Regular invoice
    if inv_type == "purchase":
        doc_type = "INV"  # Purchase bill — still INV for NIC

    # ── Determine if inter-state (IGST) or intra-state (CGST+SGST) ─────────
    is_igst = total_igst > 0

    # ── Seller & Buyer details ───────────────────────────────────────────────
    seller = {
        "Gstin": getattr(company, "gstin", "") or "",
        "LglNm": getattr(company, "legal_name", None) or getattr(company, "name", ""),
        "TrdNm": getattr(company, "name", ""),
        "Addr1": (getattr(company, "address_line1", "") or "")[:100] or "Office",
        "Addr2": (getattr(company, "city", "") or "")[:100],
        "Loc": getattr(company, "city", "") or "",
        "Pin": int(getattr(company, "pincode", "000000") or "000000"),
        "Stcd": getattr(company, "state_code", "") or "",
        "Ph": (getattr(company, "phone", "") or "")[:12],
        "Em": (getattr(company, "email", "") or "")[:100],
    }

    buyer = {
        "Gstin": getattr(party, "gstin", "") or "",
        "LglNm": getattr(party, "legal_name", None) or getattr(party, "name", ""),
        "TrdNm": getattr(party, "name", ""),
        "Pos": getattr(party, "billing_state_code", "") or seller["Stcd"],
        "Addr1": (getattr(party, "billing_address_line1", "") or getattr(party, "address_line1", "") or "")[:100] or "Address",
        "Addr2": (getattr(party, "billing_city", "") or "")[:100],
        "Loc": getattr(party, "billing_city", "") or "",
        "Pin": int(getattr(party, "billing_pincode", None) or getattr(party, "pincode", "000000") or "000000"),
        "Stcd": getattr(party, "billing_state_code", "") or "",
        "Ph": (getattr(party, "phone", "") or "")[:12],
        "Em": (getattr(party, "email", "") or "")[:100],
    }

    # ── E-Way Bill details (optional) ────────────────────────────────────────
    ewb_dtls = {}
    if invoice.eway_bill_no:
        ewb_dtls["TransId"] = ""
        ewb_dtls["TransName"] = invoice.transporter_name or ""
        ewb_dtls["Distance"] = 0
        ewb_dtls["TransDocNo"] = ""
        ewb_dtls["TransDocDt"] = ""
        ewb_dtls["VehNo"] = (invoice.vehicle_no or "").replace(" ", "")
        ewb_dtls["VehType"] = "R"  # Regular
        ewb_dtls["TransMode"] = "1"  # Road

    # ── Value details ────────────────────────────────────────────────────────
    freight = _dec(invoice.freight)
    round_off = _dec(invoice.round_off)
    tcs = _dec(invoice.tcs_amount)
    grand_total = _dec(invoice.grand_total)

    val_dtls = {
        "AssVal": _round2(total_assessable),
        "CgstVal": _round2(total_cgst),
        "SgstVal": _round2(total_sgst),
        "IgstVal": _round2(total_igst),
        "CesVal": 0,
        "StCesVal": 0,
        "Discount": _round2(discount_amt),
        "OthChrg": _round2(freight + tcs),
        "RndOffAmt": _round2(round_off),
        "TotInvVal": _round2(grand_total),
    }

    # ── Assemble full payload ────────────────────────────────────────────────
    payload = {
        "Version": "1.1",
        "TranDtls": {
            "TaxSch": "GST",
            "SupTyp": supply_type,
            "RegRev": "N",
            "EcmGstin": None,
            "IgstOnIntra": "N",
        },
        "DocDtls": {
            "Typ": doc_type,
            "No": invoice.invoice_no or "",
            "Dt": _nic_date(invoice.invoice_date),
        },
        "SellerDtls": seller,
        "BuyerDtls": buyer,
        "ItemList": items_payload,
        "ValDtls": val_dtls,
    }

    if ewb_dtls:
        payload["EwbDtls"] = ewb_dtls

    return payload

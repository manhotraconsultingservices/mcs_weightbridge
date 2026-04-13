"""
Invoice diff utility.

Computes a structured diff between two invoice snapshots (dicts) so that
business owners can see exactly what changed between revisions.

Diff structure
--------------
{
  "header": [
    {"field": "party_name", "label": "Party", "old": "ABC Ltd", "new": "XYZ Ltd"},
    ...
  ],
  "amounts": [
    {"field": "grand_total", "label": "Grand Total", "old": 10000.0, "new": 11500.0},
    ...
  ],
  "items": {
    "added": [{"product_id": "...", "description": "...", "quantity": 5, "rate": 200, ...}],
    "removed": [...],
    "modified": [
      {
        "product_id": "...",
        "description": "...",
        "changes": [{"field": "quantity", "old": 10, "new": 12}, ...]
      }
    ]
  },
  "einvoice": [
    {"field": "einvoice_status", "label": "eInvoice Status", "old": "none", "new": "success"},
    ...
  ]
}
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


# ── Label maps ────────────────────────────────────────────────────────────────

HEADER_FIELDS = {
    "party_name":          "Party",
    "customer_name":       "Customer Name",
    "invoice_date":        "Invoice Date",
    "due_date":            "Due Date",
    "tax_type":            "Tax Type",
    "vehicle_no":          "Vehicle No",
    "transporter_name":    "Transporter",
    "eway_bill_no":        "E-Way Bill No",
    "gross_weight":        "Gross Weight (kg)",
    "tare_weight":         "Tare Weight (kg)",
    "net_weight":          "Net Weight (kg)",
    "payment_mode":        "Payment Mode",
    "notes":               "Notes",
}

AMOUNT_FIELDS = {
    "subtotal":        "Subtotal",
    "discount_amount": "Discount",
    "taxable_amount":  "Taxable Amount",
    "cgst_amount":     "CGST",
    "sgst_amount":     "SGST",
    "igst_amount":     "IGST",
    "tcs_amount":      "TCS",
    "freight":         "Freight",
    "round_off":       "Round Off",
    "grand_total":     "Grand Total",
}

ITEM_FIELDS = {
    "quantity":    "Quantity",
    "rate":        "Rate",
    "gst_rate":    "GST Rate (%)",
    "unit":        "Unit",
    "hsn_code":    "HSN Code",
    "description": "Description",
}

EINVOICE_FIELDS = {
    "irn":             "IRN",
    "irn_ack_no":      "Ack No",
    "einvoice_status": "eInvoice Status",
    "irn_cancelled_at":"IRN Cancelled At",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _coerce(v: Any) -> Any:
    """Normalise types for comparison (Decimal → float, None → None)."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


def _changed(a: Any, b: Any) -> bool:
    """True when two values differ after normalisation."""
    a2 = _coerce(a)
    b2 = _coerce(b)
    if isinstance(a2, float) and isinstance(b2, float):
        return abs(a2 - b2) > 0.001
    return a2 != b2


def _str(v: Any) -> str | None:
    """Human-readable string representation of a value."""
    if v is None:
        return None
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


# ── Main diff function ─────────────────────────────────────────────────────────

def compute_invoice_diff(old: dict, new: dict) -> dict:
    """
    Compute a structured diff between two invoice snapshot dicts.

    Parameters
    ----------
    old : dict — snapshot of the previous version
    new : dict — snapshot of the new (revised) version

    Returns
    -------
    dict with keys: header, amounts, items, einvoice, summary_text
    """

    header_changes = []
    amount_changes = []
    einvoice_changes = []

    # ── Header diffs ──────────────────────────────────────────────────────────
    for field, label in HEADER_FIELDS.items():
        # party_name is special — extract from nested party dict
        if field == "party_name":
            old_val = (old.get("party") or {}).get("name") or old.get("customer_name")
            new_val = (new.get("party") or {}).get("name") or new.get("customer_name")
        else:
            old_val = old.get(field)
            new_val = new.get(field)

        if _changed(old_val, new_val):
            header_changes.append({
                "field": field, "label": label,
                "old": _str(old_val), "new": _str(new_val),
            })

    # ── Amount diffs ─────────────────────────────────────────────────────────
    for field, label in AMOUNT_FIELDS.items():
        old_val = old.get(field)
        new_val = new.get(field)
        if _changed(old_val, new_val):
            amount_changes.append({
                "field": field, "label": label,
                "old": _coerce(old_val), "new": _coerce(new_val),
                "old_str": _str(old_val), "new_str": _str(new_val),
            })

    # ── Items diffs ───────────────────────────────────────────────────────────
    old_items = {str(i.get("product_id")): i for i in (old.get("items") or [])}
    new_items = {str(i.get("product_id")): i for i in (new.get("items") or [])}

    added = []
    removed = []
    modified = []

    for pid, item in new_items.items():
        if pid not in old_items:
            added.append({
                "product_id": pid,
                "description": item.get("description") or item.get("product_id", ""),
                "hsn_code": item.get("hsn_code"),
                "quantity": _coerce(item.get("quantity")),
                "unit": item.get("unit"),
                "rate": _coerce(item.get("rate")),
                "gst_rate": _coerce(item.get("gst_rate")),
                "total_amount": _coerce(item.get("total_amount")),
            })

    for pid, item in old_items.items():
        if pid not in new_items:
            removed.append({
                "product_id": pid,
                "description": item.get("description") or item.get("product_id", ""),
                "hsn_code": item.get("hsn_code"),
                "quantity": _coerce(item.get("quantity")),
                "unit": item.get("unit"),
                "rate": _coerce(item.get("rate")),
                "gst_rate": _coerce(item.get("gst_rate")),
                "total_amount": _coerce(item.get("total_amount")),
            })

    for pid in set(old_items) & set(new_items):
        item_changes = []
        for field, label in ITEM_FIELDS.items():
            ov = old_items[pid].get(field)
            nv = new_items[pid].get(field)
            if _changed(ov, nv):
                item_changes.append({
                    "field": field, "label": label,
                    "old": _coerce(ov), "new": _coerce(nv),
                    "old_str": _str(ov), "new_str": _str(nv),
                })
        if item_changes:
            modified.append({
                "product_id": pid,
                "description": new_items[pid].get("description") or pid,
                "changes": item_changes,
            })

    # ── eInvoice diffs ────────────────────────────────────────────────────────
    for field, label in EINVOICE_FIELDS.items():
        old_val = old.get(field)
        new_val = new.get(field)
        if _changed(old_val, new_val):
            einvoice_changes.append({
                "field": field, "label": label,
                "old": _str(old_val), "new": _str(new_val),
            })

    # ── Human-readable summary ────────────────────────────────────────────────
    parts = []
    if header_changes:
        labels = [c["label"] for c in header_changes]
        parts.append(f"Header: {', '.join(labels)} changed")
    if amount_changes:
        gt_change = next((c for c in amount_changes if c["field"] == "grand_total"), None)
        if gt_change:
            parts.append(f"Grand total: ₹{gt_change['old_str']} → ₹{gt_change['new_str']}")
        else:
            parts.append(f"{len(amount_changes)} amount(s) changed")
    if added:
        parts.append(f"{len(added)} item(s) added")
    if removed:
        parts.append(f"{len(removed)} item(s) removed")
    if modified:
        parts.append(f"{len(modified)} item(s) modified")
    if einvoice_changes:
        parts.append("eInvoice fields updated")

    summary = "; ".join(parts) if parts else "No changes detected"

    return {
        "header": header_changes,
        "amounts": amount_changes,
        "items": {
            "added": added,
            "removed": removed,
            "modified": modified,
        },
        "einvoice": einvoice_changes,
        "summary_text": summary,
        "has_changes": bool(header_changes or amount_changes or added or removed or modified or einvoice_changes),
    }


def invoice_to_snapshot(inv: Any) -> dict:
    """
    Serialize an Invoice ORM object to a JSON-serialisable dict for storage.
    Called just before a new revision is created.
    """
    from decimal import Decimal
    from datetime import date, datetime

    def _serial(v: Any) -> Any:
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        if hasattr(v, "__dict__"):
            return None  # don't recurse into ORM objects
        return v

    def _item_to_dict(item: Any) -> dict:
        return {
            "product_id": str(item.product_id),
            "description": item.description,
            "hsn_code": item.hsn_code,
            "quantity": float(item.quantity or 0),
            "unit": item.unit,
            "rate": float(item.rate or 0),
            "amount": float(item.amount or 0),
            "gst_rate": float(item.gst_rate or 0),
            "cgst_amount": float(item.cgst_amount or 0),
            "sgst_amount": float(item.sgst_amount or 0),
            "igst_amount": float(item.igst_amount or 0),
            "total_amount": float(item.total_amount or 0),
        }

    party = inv.party
    return {
        "id": str(inv.id),
        "invoice_no": inv.invoice_no,
        "invoice_type": inv.invoice_type,
        "tax_type": inv.tax_type,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "party": {"id": str(party.id), "name": party.name, "gstin": party.gstin} if party else None,
        "customer_name": inv.customer_name,
        "vehicle_no": inv.vehicle_no,
        "transporter_name": inv.transporter_name,
        "eway_bill_no": inv.eway_bill_no,
        "gross_weight": float(inv.gross_weight or 0) if inv.gross_weight else None,
        "tare_weight": float(inv.tare_weight or 0) if inv.tare_weight else None,
        "net_weight": float(inv.net_weight or 0) if inv.net_weight else None,
        "subtotal": float(inv.subtotal or 0),
        "discount_amount": float(inv.discount_amount or 0),
        "taxable_amount": float(inv.taxable_amount or 0),
        "cgst_amount": float(inv.cgst_amount or 0),
        "sgst_amount": float(inv.sgst_amount or 0),
        "igst_amount": float(inv.igst_amount or 0),
        "tcs_amount": float(inv.tcs_amount or 0),
        "freight": float(inv.freight or 0),
        "round_off": float(inv.round_off or 0),
        "grand_total": float(inv.grand_total or 0),
        "payment_mode": inv.payment_mode,
        "notes": inv.notes,
        "irn": inv.irn,
        "irn_ack_no": inv.irn_ack_no,
        "einvoice_status": inv.einvoice_status,
        "irn_cancelled_at": inv.irn_cancelled_at.isoformat() if inv.irn_cancelled_at else None,
        "revision_no": inv.revision_no,
        "items": [_item_to_dict(i) for i in (inv.items or [])],
    }

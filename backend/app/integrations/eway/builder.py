"""Build the NIC E-Way Bill JSON payload.

Works from a plain field dict so both invoices and delivery challans can use it.
Outward supply only (stone-crusher dispatch). Road transport. URP for unregistered
consignees. Distance 0 lets NIC auto-compute by PIN-to-PIN.
"""
from __future__ import annotations

from datetime import date


def _fmt_date(d) -> str:
    if isinstance(d, (date,)):
        return d.strftime("%d/%m/%Y")
    return str(d or "")


def build_eway_payload(
    *,
    company,
    party,
    doc_no: str,
    doc_date,
    doc_type: str = "INV",            # INV | CHL (challan) | BIL (bill of supply)
    sub_supply_type: str = "1",       # 1 = Supply
    vehicle_no: str | None = None,
    transporter_id: str | None = None,
    transporter_name: str | None = None,
    distance_km: int = 0,
    taxable: float = 0.0,
    cgst: float = 0.0,
    sgst: float = 0.0,
    igst: float = 0.0,
    total: float = 0.0,
    items: list[dict] | None = None,
) -> dict:
    """Return a NIC-format E-Way Bill request body."""
    comp_state = int(company.state_code) if getattr(company, "state_code", None) and str(company.state_code).isdigit() else 0
    party_gstin = (getattr(party, "gstin", None) or "URP") if party else "URP"
    party_state = comp_state
    if party and getattr(party, "billing_state_code", None) and str(party.billing_state_code).isdigit():
        party_state = int(party.billing_state_code)

    item_list = []
    for it in (items or []):
        item_list.append({
            "productName": it.get("name") or it.get("description") or "Material",
            "hsnCode": int(it["hsn_code"]) if str(it.get("hsn_code") or "").isdigit() else (it.get("hsn_code") or 0),
            "quantity": float(it.get("quantity") or 0),
            "qtyUnit": (it.get("unit") or "MTS")[:3].upper(),
            "taxableAmount": float(it.get("amount") or 0),
            "cgstRate": float(it.get("cgst_rate") or 0),
            "sgstRate": float(it.get("sgst_rate") or 0),
            "igstRate": float(it.get("igst_rate") or 0),
        })

    payload = {
        "supplyType": "O",                    # Outward
        "subSupplyType": sub_supply_type,
        "docType": doc_type,
        "docNo": doc_no,
        "docDate": _fmt_date(doc_date),
        "fromGstin": getattr(company, "gstin", "") or "",
        "fromTrdName": getattr(company, "name", "") or "",
        "fromAddr1": (getattr(company, "address_line1", "") or "")[:120],
        "fromPlace": (getattr(company, "city", "") or "")[:50],
        "fromPincode": int(company.pincode) if str(getattr(company, "pincode", "") or "").isdigit() else 0,
        "fromStateCode": comp_state,
        "actFromStateCode": comp_state,
        "toGstin": party_gstin,
        "toTrdName": (getattr(party, "name", "") if party else "") or "",
        "toAddr1": (getattr(party, "billing_address", "") if party else "" or "")[:120] if party else "",
        "toPlace": (getattr(party, "billing_city", "") if party else "") or "",
        "toPincode": int(party.billing_pincode) if party and str(getattr(party, "billing_pincode", "") or "").isdigit() else 0,
        "toStateCode": party_state,
        "actToStateCode": party_state,
        "transactionType": 1,
        "totalValue": round(float(taxable), 2),
        "cgstValue": round(float(cgst), 2),
        "sgstValue": round(float(sgst), 2),
        "igstValue": round(float(igst), 2),
        "cessValue": 0,
        "totInvValue": round(float(total), 2),
        "transMode": "1",                     # Road
        "transDistance": str(int(distance_km or 0)),
        "transporterId": transporter_id or "",
        "transporterName": transporter_name or "",
        "vehicleNo": (vehicle_no or "").replace(" ", "").upper(),
        "vehicleType": "R",                   # Regular
        "itemList": item_list,
    }
    return payload

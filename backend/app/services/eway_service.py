"""E-Way Bill service — config loading + generate/cancel helpers.

Keeps the invoice and delivery-challan routers thin: they call generate_for_*
which builds the NIC payload (with product names + per-item GST rates), invokes
the client, and stamps ewb_* fields on the object. The caller commits.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.eway import EWayClient, EWayConfig, build_eway_payload
from app.models.party import Party
from app.models.product import Product


async def load_eway_config(db: AsyncSession) -> EWayConfig | None:
    row = (await db.execute(
        text("SELECT value FROM app_settings WHERE key = 'eway_config'")
    )).fetchone()
    if not row:
        return None
    try:
        return EWayConfig.from_dict(json.loads(row[0]))
    except Exception:
        return None


async def _product_names(db: AsyncSession, product_ids) -> dict:
    ids = [p for p in set(product_ids) if p]
    if not ids:
        return {}
    rows = (await db.execute(select(Product.id, Product.name).where(Product.id.in_(ids)))).all()
    return {r[0]: r[1] for r in rows}


def _item_payload(it, name: str | None, *, intra: bool) -> dict:
    gst = float(getattr(it, "gst_rate", 0) or 0)
    return {
        "name": name or getattr(it, "description", None) or "Material",
        "hsn_code": getattr(it, "hsn_code", None),
        "quantity": float(getattr(it, "quantity", 0) or 0),
        "unit": getattr(it, "unit", "MT") or "MT",
        "amount": float(getattr(it, "amount", 0) or 0),
        "cgst_rate": gst / 2 if intra else 0,
        "sgst_rate": gst / 2 if intra else 0,
        "igst_rate": 0 if intra else gst,
    }


def _stamp(obj, result) -> None:
    if result.success:
        obj.eway_bill_no = result.ewb_no
        obj.ewb_date = result.ewb_date or datetime.now(timezone.utc)
        obj.ewb_valid_till = result.valid_until
        obj.ewb_status = "generated"
        obj.ewb_error = None
    else:
        obj.ewb_status = "failed"
        obj.ewb_error = (result.error_message or "EWB generation failed")[:1000]


async def generate_for_invoice(db, inv, company, cfg: EWayConfig, *,
                               distance_km: int = 0, vehicle_no: str | None = None):
    names = await _product_names(db, [it.product_id for it in inv.items])
    intra = float(inv.igst_amount or 0) == 0
    items = [_item_payload(it, names.get(it.product_id), intra=intra) for it in inv.items]
    body = build_eway_payload(
        company=company, party=inv.party,
        doc_no=inv.invoice_no or "DRAFT",
        doc_date=inv.invoice_date,
        doc_type="INV" if inv.tax_type == "gst" else "BIL",
        vehicle_no=vehicle_no or inv.vehicle_no,
        transporter_name=inv.transporter_name,
        distance_km=distance_km or (inv.ewb_distance_km or 0) or cfg.default_distance_km,
        taxable=float(inv.taxable_amount or 0),
        cgst=float(inv.cgst_amount or 0), sgst=float(inv.sgst_amount or 0),
        igst=float(inv.igst_amount or 0), total=float(inv.grand_total or 0),
        items=items,
    )
    result = await EWayClient(cfg).generate_ewb(body)
    if distance_km:
        inv.ewb_distance_km = distance_km
    _stamp(inv, result)
    return result


async def generate_for_challan(db, ch, company, cfg: EWayConfig, *,
                               distance_km: int = 0, vehicle_no: str | None = None):
    # ch.party is lazy='noload' → fetch explicitly so the consignee isn't URP
    party = await db.get(Party, ch.party_id) if ch.party_id else None
    names = await _product_names(db, [it.product_id for it in ch.items])
    # Challan carries value only (tax applied at invoice) → taxable = total, tax = 0
    items = [_item_payload(it, names.get(it.product_id), intra=True) for it in ch.items]
    for itp in items:  # challan value-only: zero the rates
        itp["cgst_rate"] = itp["sgst_rate"] = itp["igst_rate"] = 0
    body = build_eway_payload(
        company=company, party=party,
        doc_no=ch.challan_no or "DRAFT",
        doc_date=ch.challan_date,
        doc_type="CHL",
        vehicle_no=vehicle_no or ch.vehicle_no,
        transporter_name=ch.transporter_name,
        distance_km=distance_km or (ch.distance_km or 0) or cfg.default_distance_km,
        taxable=float(ch.total_amount or 0), cgst=0, sgst=0, igst=0,
        total=float(ch.total_amount or 0),
        items=items,
    )
    result = await EWayClient(cfg).generate_ewb(body)
    _stamp(ch, result)
    return result


async def cancel_ewb(cfg: EWayConfig, ewb_no: str, reason: str = "2", remark: str = ""):
    return await EWayClient(cfg).cancel_ewb(ewb_no, reason=reason, remark=remark)

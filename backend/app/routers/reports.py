"""
Reports router — sales register, weight register, GSTR-1 summary + JSON export,
GSTR-3B, Profit & Loss, Stock Summary.
"""
import io
import json
import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

logger = logging.getLogger("reports")

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.company import Company
from app.models.invoice import Invoice, InvoiceItem
from app.models.token import Token
from app.models.party import Party
from app.models.product import Product
from app.models.payment import PaymentReceipt, PaymentVoucher, InvoicePayment
from app.models.user import User

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])


# ── helpers ─────────────────────────────────────────────────────────────────

def _f(v) -> float:
    return float(v or 0)

def _r2(v) -> float:
    return round(float(v or 0), 2)


# ── Party Balances (customer + supplier, advance-aware) ───────────────────────

@router.get("/party-balances")
async def party_balances(
    party_type: str = Query("all"),   # all | customer | supplier
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Current balance by party — bills outstanding, advance on account, and net.

    Computed independently from source (same formula as recompute_party_balance),
    so it is correct even if a party's denormalised current_balance is stale.
    Signed net: POSITIVE = party owes us (Dr) · NEGATIVE = we owe them (Cr).
    """
    cid = current_user.company_id

    pq = select(Party).where(Party.company_id == cid, Party.is_active == True)
    if party_type == "customer":
        pq = pq.where(Party.party_type.in_(["customer", "both"]))
    elif party_type == "supplier":
        pq = pq.where(Party.party_type.in_(["supplier", "both"]))
    parties = (await db.execute(pq)).scalars().all()

    # Invoice net (sale/purchase) + note totals, grouped by (party, type)
    inv_map: dict = {}
    for r in (await db.execute(
        select(Invoice.party_id, Invoice.invoice_type, func.coalesce(func.sum(
            func.coalesce(Invoice.grand_total, 0) - func.coalesce(Invoice.amount_paid, 0)
            - func.coalesce(Invoice.write_off_amount, 0)), 0))
        .where(Invoice.company_id == cid, Invoice.status == "final",
               Invoice.invoice_type.in_(("sale", "purchase")))
        .group_by(Invoice.party_id, Invoice.invoice_type)
    )).all():
        inv_map[(r[0], r[1])] = Decimal(str(r[2] or 0))
    note_map: dict = {}
    for r in (await db.execute(
        select(Invoice.party_id, Invoice.invoice_type,
               func.coalesce(func.sum(func.coalesce(Invoice.grand_total, 0)), 0))
        .where(Invoice.company_id == cid, Invoice.status == "final",
               Invoice.invoice_type.in_(("credit_note", "debit_note")))
        .group_by(Invoice.party_id, Invoice.invoice_type)
    )).all():
        note_map[(r[0], r[1])] = Decimal(str(r[2] or 0))

    async def _sum_map(stmt):
        return {r[0]: Decimal(str(r[1] or 0)) for r in (await db.execute(stmt)).all()}

    rec_total = await _sum_map(select(PaymentReceipt.party_id, func.coalesce(func.sum(PaymentReceipt.amount), 0))
                               .where(PaymentReceipt.company_id == cid).group_by(PaymentReceipt.party_id))
    rec_alloc = await _sum_map(select(PaymentReceipt.party_id, func.coalesce(func.sum(InvoicePayment.amount), 0))
                               .join(PaymentReceipt, InvoicePayment.receipt_id == PaymentReceipt.id)
                               .where(PaymentReceipt.company_id == cid).group_by(PaymentReceipt.party_id))
    # Exclude direct-expense vouchers (overheads) — they are not supplier prepayments.
    vou_total = await _sum_map(select(PaymentVoucher.party_id, func.coalesce(func.sum(PaymentVoucher.amount), 0))
                               .where(PaymentVoucher.company_id == cid,
                                      PaymentVoucher.expense_category.is_(None)).group_by(PaymentVoucher.party_id))
    vou_alloc = await _sum_map(select(PaymentVoucher.party_id, func.coalesce(func.sum(InvoicePayment.amount), 0))
                               .join(PaymentVoucher, InvoicePayment.voucher_id == PaymentVoucher.id)
                               .where(PaymentVoucher.company_id == cid,
                                      PaymentVoucher.expense_category.is_(None)).group_by(PaymentVoucher.party_id))

    Z = Decimal("0")
    rows = []
    tot_bills = tot_adv = tot_net = Z
    for p in parties:
        sale_net = inv_map.get((p.id, "sale"), Z)
        pur_net = inv_map.get((p.id, "purchase"), Z)
        deb = note_map.get((p.id, "debit_note"), Z)
        cred = note_map.get((p.id, "credit_note"), Z)
        receipt_adv = max(Z, rec_total.get(p.id, Z) - rec_alloc.get(p.id, Z))
        voucher_adv = max(Z, vou_total.get(p.id, Z) - vou_alloc.get(p.id, Z))
        opening = Decimal(str(p.opening_balance or 0))

        bills = opening + sale_net - pur_net + deb - cred        # invoice/notes component (signed)
        if p.party_type == "supplier":
            advance = voucher_adv
        elif p.party_type == "both":
            advance = receipt_adv + voucher_adv
        else:
            advance = receipt_adv
        net = bills - receipt_adv + voucher_adv                  # = current_balance

        if bills == 0 and advance == 0 and net == 0:
            continue
        rows.append({
            "id": str(p.id),
            "name": p.name,
            "party_type": p.party_type,
            "phone": p.phone,
            "city": p.billing_city,
            "bills_balance": _r2(bills),
            "advance": _r2(advance),
            "net_balance": _r2(net),
        })
        tot_bills += bills
        tot_adv += advance
        tot_net += net

    rows.sort(key=lambda r: abs(r["net_balance"]), reverse=True)
    return {
        "rows": rows,
        "count": len(rows),
        "totals": {
            "bills_balance": _r2(tot_bills),
            "advance": _r2(tot_adv),
            "net_balance": _r2(tot_net),
        },
    }


# ── Sales Register ───────────────────────────────────────────────────────────

@router.get("/sales-register")
async def sales_register(
    from_date: date = Query(...),
    to_date: date = Query(...),
    party_id: Optional[str] = Query(None),
    invoice_type: str = Query("sale"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = (
        select(Invoice, Party)
        .join(Party, Invoice.party_id == Party.id)
        .where(
            Invoice.invoice_type == invoice_type,
            Invoice.status == "final",
            Invoice.company_id == current_user.company_id,
            Invoice.invoice_date >= from_date,
            Invoice.invoice_date <= to_date,
        )
        .order_by(Invoice.invoice_date, Invoice.invoice_no)
    )
    if party_id:
        q = q.where(Invoice.party_id == party_id)

    result = await db.execute(q)
    rows = result.all()

    items = []
    totals = {k: Decimal(0) for k in ["taxable_amount", "cgst", "sgst", "igst", "grand_total"]}
    for inv, party in rows:
        items.append({
            "id": str(inv.id),
            "invoice_no": inv.invoice_no,
            "invoice_date": inv.invoice_date.isoformat(),
            "party_name": party.name,
            "gstin": party.gstin,
            "vehicle_no": inv.vehicle_no,
            "net_weight": _f(inv.net_weight) if inv.net_weight else None,
            "taxable_amount": _f(inv.taxable_amount),
            "cgst_amount": _f(inv.cgst_amount),
            "sgst_amount": _f(inv.sgst_amount),
            "igst_amount": _f(inv.igst_amount),
            "grand_total": _f(inv.grand_total),
            "payment_status": inv.payment_status,
        })
        totals["taxable_amount"] += inv.taxable_amount
        totals["cgst"] += inv.cgst_amount
        totals["sgst"] += inv.sgst_amount
        totals["igst"] += inv.igst_amount
        totals["grand_total"] += inv.grand_total

    return {"items": items, "totals": {k: _f(v) for k, v in totals.items()}, "count": len(items)}


# ── Weight Register ──────────────────────────────────────────────────────────

@router.get("/weight-register")
async def weight_register(
    from_date: date = Query(...),
    to_date: date = Query(...),
    party_id: Optional[str] = Query(None),
    token_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = (
        select(Token, Party, Product)
        .outerjoin(Party, Token.party_id == Party.id)
        .outerjoin(Product, Token.product_id == Product.id)
        .where(Token.token_date >= from_date, Token.token_date <= to_date, Token.status == "COMPLETED",
               Token.company_id == current_user.company_id)
        .order_by(Token.token_date, Token.token_no)
    )
    if party_id:
        q = q.where(Token.party_id == party_id)
    if token_type:
        q = q.where(Token.token_type == token_type)

    result = await db.execute(q)
    rows = result.all()

    items = []
    total_net = Decimal(0)
    for token, party, product in rows:
        items.append({
            "id": str(token.id),
            "token_no": token.token_no,
            "token_date": token.token_date.isoformat(),
            "token_type": token.token_type,
            "vehicle_no": token.vehicle_no,
            "party_name": party.name if party else None,
            "product_name": product.name if product else None,
            "gross_weight": _f(token.gross_weight) if token.gross_weight else None,
            "tare_weight": _f(token.tare_weight) if token.tare_weight else None,
            "net_weight": _f(token.net_weight) if token.net_weight else None,
            "is_manual_weight": token.is_manual_weight,
        })
        if token.net_weight:
            total_net += token.net_weight

    return {"items": items, "total_net_weight": _f(total_net), "count": len(items)}


# ── GSTR-1 Summary ───────────────────────────────────────────────────────────

@router.get("/gstr1")
async def gstr1_summary(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """GSTR-1 summary: B2B, B2C, HSN."""
    result = await db.execute(
        select(Invoice, Party)
        .join(Party, Invoice.party_id == Party.id)
        .where(Invoice.invoice_type == "sale", Invoice.status == "final",
               Invoice.tax_type == "gst",   # exclude non-GST Bill-of-Supply from GSTR-1
               Invoice.company_id == current_user.company_id,
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
        .order_by(Invoice.invoice_date)
    )
    rows = result.all()

    b2b, b2c = [], []
    b2b_totals = {k: Decimal(0) for k in ["taxable", "cgst", "sgst", "igst", "total"]}
    b2c_totals = {k: Decimal(0) for k in ["taxable", "cgst", "sgst", "igst", "total"]}

    for inv, party in rows:
        row = {
            "invoice_no": inv.invoice_no, "invoice_date": inv.invoice_date.isoformat(),
            "party_name": party.name, "gstin": party.gstin,
            "taxable_amount": _f(inv.taxable_amount), "cgst_amount": _f(inv.cgst_amount),
            "sgst_amount": _f(inv.sgst_amount), "igst_amount": _f(inv.igst_amount),
            "grand_total": _f(inv.grand_total),
        }
        if party.gstin:
            b2b.append(row)
            b2b_totals["taxable"] += inv.taxable_amount; b2b_totals["cgst"] += inv.cgst_amount
            b2b_totals["sgst"] += inv.sgst_amount; b2b_totals["igst"] += inv.igst_amount
            b2b_totals["total"] += inv.grand_total
        else:
            b2c.append(row)
            b2c_totals["taxable"] += inv.taxable_amount; b2c_totals["cgst"] += inv.cgst_amount
            b2c_totals["sgst"] += inv.sgst_amount; b2c_totals["igst"] += inv.igst_amount
            b2c_totals["total"] += inv.grand_total

    hsn_result = await db.execute(
        select(InvoiceItem.hsn_code, InvoiceItem.unit,
               func.sum(InvoiceItem.quantity).label("qty"),
               func.sum(InvoiceItem.amount).label("taxable"),
               func.sum(InvoiceItem.cgst_amount).label("cgst"),
               func.sum(InvoiceItem.sgst_amount).label("sgst"),
               func.sum(InvoiceItem.igst_amount).label("igst"))
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .where(Invoice.invoice_type == "sale", Invoice.status == "final",
               Invoice.tax_type == "gst",   # exclude non-GST Bill-of-Supply from GSTR-1 HSN
               Invoice.company_id == current_user.company_id,
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
        .group_by(InvoiceItem.hsn_code, InvoiceItem.unit)
        .order_by(InvoiceItem.hsn_code)
    )
    hsn_summary = [
        {"hsn_code": r.hsn_code or "—", "unit": r.unit, "quantity": _f(r.qty),
         "taxable_amount": _f(r.taxable), "cgst_amount": _f(r.cgst),
         "sgst_amount": _f(r.sgst), "igst_amount": _f(r.igst)}
        for r in hsn_result.all()
    ]

    # ── CDNR: Credit / Debit Notes (registered) ──────────────────────────────
    from sqlalchemy.orm import aliased
    RefInv = aliased(Invoice)
    cdn_result = await db.execute(
        select(Invoice, Party, RefInv.invoice_no)
        .join(Party, Invoice.party_id == Party.id)
        .outerjoin(RefInv, Invoice.reference_invoice_id == RefInv.id)
        .where(Invoice.invoice_type.in_(("credit_note", "debit_note")),
               Invoice.status == "final",
               Invoice.tax_type == "gst",
               Invoice.company_id == current_user.company_id,
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
        .order_by(Invoice.invoice_date)
    )
    cdnr = []
    cdnr_totals = {k: Decimal(0) for k in ["taxable", "cgst", "sgst", "igst", "total"]}
    for note, party, ref_no in cdn_result.all():
        cdnr.append({
            "note_no": note.invoice_no, "note_date": note.invoice_date.isoformat(),
            "note_type": "C" if note.invoice_type == "credit_note" else "D",
            "party_name": party.name, "gstin": party.gstin,
            "original_invoice_no": ref_no, "reason": note.note_reason,
            "taxable_amount": _f(note.taxable_amount), "cgst_amount": _f(note.cgst_amount),
            "sgst_amount": _f(note.sgst_amount), "igst_amount": _f(note.igst_amount),
            "grand_total": _f(note.grand_total),
        })
        cdnr_totals["taxable"] += note.taxable_amount; cdnr_totals["cgst"] += note.cgst_amount
        cdnr_totals["sgst"] += note.sgst_amount; cdnr_totals["igst"] += note.igst_amount
        cdnr_totals["total"] += note.grand_total

    return {
        "b2b": b2b, "b2b_totals": {k: _f(v) for k, v in b2b_totals.items()},
        "b2c": b2c, "b2c_totals": {k: _f(v) for k, v in b2c_totals.items()},
        "hsn_summary": hsn_summary,
        "cdnr": cdnr, "cdnr_totals": {k: _f(v) for k, v in cdnr_totals.items()},
    }


# ── GSTR-1 JSON Export (GSTN portal format) ─────────────────────────────────

@router.get("/gstr1-json")
async def gstr1_json_export(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download GSTR-1 in GSTN JSON format ready for portal upload."""
    company = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    company_gstin = company.gstin if company else ""
    company_state_code = company.state_code if company and hasattr(company, "state_code") else (company_gstin[:2] if company_gstin else "00")

    # Filing period: use to_date's month
    fp = to_date.strftime("%m%Y")

    # Fetch invoices with items
    inv_result = await db.execute(
        select(Invoice, Party)
        .join(Party, Invoice.party_id == Party.id)
        .where(Invoice.invoice_type == "sale", Invoice.status == "final",
               Invoice.tax_type == "gst",   # exclude non-GST Bill-of-Supply from GSTR-1 JSON
               Invoice.company_id == current_user.company_id,
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
        .order_by(Invoice.invoice_date)
    )
    inv_rows = inv_result.all()

    # Fetch all items for these invoices
    invoice_ids = [str(inv.id) for inv, _ in inv_rows]
    items_map: dict[str, list] = {}
    if invoice_ids:
        from sqlalchemy import text
        items_result = await db.execute(
            select(InvoiceItem)
            .where(InvoiceItem.invoice_id.in_([inv.id for inv, _ in inv_rows]))
        )
        for item in items_result.scalars():
            key = str(item.invoice_id)
            items_map.setdefault(key, []).append(item)

    # Build B2B section — grouped by receiver GSTIN
    b2b_map: dict[str, list] = {}
    b2cs_map: dict[str, dict] = {}  # key: f"{rate}_{pos}_{supply_type}"
    total_turnover = Decimal(0)

    for inv, party in inv_rows:
        total_turnover += inv.taxable_amount   # portal gt = aggregate taxable turnover, not tax-inclusive grand_total
        inv_items = items_map.get(str(inv.id), [])

        # Build itms list from invoice items
        itms = []
        for idx, item in enumerate(inv_items, 1):
            gst_rate = float(item.gst_rate or 0)
            itm = {
                "num": idx,
                "itm_det": {
                    "txval": _r2(item.amount),
                    "rt": gst_rate,
                    "camt": _r2(item.cgst_amount),
                    "samt": _r2(item.sgst_amount),
                    "iamt": _r2(item.igst_amount),
                    "csamt": 0,
                }
            }
            itms.append(itm)

        # If no items, use invoice-level aggregates
        if not itms:
            # Determine predominant GST rate from invoice totals
            gst_total = _r2(inv.cgst_amount + inv.sgst_amount + inv.igst_amount)
            taxable = _r2(inv.taxable_amount)
            rate = round((gst_total / taxable * 100) if taxable > 0 else 0)
            itms = [{
                "num": 1,
                "itm_det": {
                    "txval": _r2(inv.taxable_amount),
                    "rt": rate,
                    "camt": _r2(inv.cgst_amount),
                    "samt": _r2(inv.sgst_amount),
                    "iamt": _r2(inv.igst_amount),
                    "csamt": 0,
                }
            }]

        inv_entry = {
            "inum": inv.invoice_no,
            "idt": inv.invoice_date.strftime("%d-%m-%Y"),
            "val": _r2(inv.grand_total),  # NIC portal requires grand_total (inclusive of tax) for val
            "pos": party.billing_state_code or company_state_code if hasattr(party, "billing_state_code") else company_state_code,
            "rchrg": "N",
            "inv_typ": "R",
            "itms": itms,
        }

        if party.gstin:
            b2b_map.setdefault(party.gstin, []).append(inv_entry)
        else:
            # B2CS — aggregate by rate + state
            # Determine supply type: prefer party billing_state_code comparison over
            # igst_amount==0 heuristic, which fails for zero-rate inter-state supplies.
            _party_state = getattr(party, "billing_state_code", None) if party else None
            if _party_state:
                _b2cs_supply_type = "INTRA" if _party_state == company_state_code else "INTER"
            else:
                _b2cs_supply_type = "INTRA" if _f(inv.igst_amount) == 0.0 else "INTER"
            for item in inv_items:
                rate = float(item.gst_rate or 0)
                pos = company_state_code
                supply_type = _b2cs_supply_type
                key = f"{rate}_{pos}_{supply_type}"
                if key not in b2cs_map:
                    b2cs_map[key] = {"sply_tp": supply_type, "pos": pos, "rt": rate, "txval": 0.0, "camt": 0.0, "samt": 0.0, "iamt": 0.0, "csamt": 0}
                b2cs_map[key]["txval"] = _r2(b2cs_map[key]["txval"] + _f(item.amount))
                b2cs_map[key]["camt"] = _r2(b2cs_map[key]["camt"] + _f(item.cgst_amount))
                b2cs_map[key]["samt"] = _r2(b2cs_map[key]["samt"] + _f(item.sgst_amount))
                b2cs_map[key]["iamt"] = _r2(b2cs_map[key]["iamt"] + _f(item.igst_amount))
            if not inv_items:
                rate = 0
                pos = company_state_code
                supply_type = _b2cs_supply_type
                key = f"{rate}_{pos}_{supply_type}"
                if key not in b2cs_map:
                    b2cs_map[key] = {"sply_tp": supply_type, "pos": pos, "rt": rate, "txval": 0.0, "camt": 0.0, "samt": 0.0, "iamt": 0.0, "csamt": 0}
                b2cs_map[key]["txval"] = _r2(b2cs_map[key]["txval"] + _f(inv.taxable_amount))
                b2cs_map[key]["camt"] = _r2(b2cs_map[key]["camt"] + _f(inv.cgst_amount))
                b2cs_map[key]["samt"] = _r2(b2cs_map[key]["samt"] + _f(inv.sgst_amount))
                b2cs_map[key]["iamt"] = _r2(b2cs_map[key]["iamt"] + _f(inv.igst_amount))

    # Build HSN section
    hsn_result = await db.execute(
        select(InvoiceItem.hsn_code, InvoiceItem.unit, Product.name,
               func.sum(InvoiceItem.quantity).label("qty"),
               func.sum(InvoiceItem.amount).label("taxable"),
               func.sum(InvoiceItem.cgst_amount).label("cgst"),
               func.sum(InvoiceItem.sgst_amount).label("sgst"),
               func.sum(InvoiceItem.igst_amount).label("igst"),
               func.sum(InvoiceItem.total_amount).label("val"))
        .outerjoin(Product, InvoiceItem.product_id == Product.id)
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .where(Invoice.invoice_type == "sale", Invoice.status == "final",
               Invoice.tax_type == "gst",   # exclude non-GST Bill-of-Supply from GSTR-1 JSON HSN
               Invoice.company_id == current_user.company_id,
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
        .group_by(InvoiceItem.hsn_code, InvoiceItem.unit, Product.name)
        .order_by(InvoiceItem.hsn_code)
    )
    hsn_data = [
        {
            "num": idx,
            "hsn_sc": r.hsn_code or "",
            "desc": r.name or "",
            "uqc": r.unit or "OTH",
            "qty": _r2(r.qty),
            "val": _r2(r.val),
            "txval": _r2(r.taxable),
            "iamt": _r2(r.igst),
            "camt": _r2(r.cgst),
            "samt": _r2(r.sgst),
            "csamt": 0,
        }
        for idx, r in enumerate(hsn_result.all(), 1)
    ]

    # ── CDNR: Credit/Debit notes issued to REGISTERED persons ─────────────────
    # (Was missing from the portal JSON → credit notes that should reduce the
    # liability never reached GSTN.) CDNUR — notes to unregistered persons — is
    # out of scope for v1; only registered-recipient notes are emitted.
    cdn_rows = (await db.execute(
        select(Invoice, Party)
        .join(Party, Invoice.party_id == Party.id)
        .where(Invoice.invoice_type.in_(("credit_note", "debit_note")),
               Invoice.status == "final", Invoice.tax_type == "gst",
               Invoice.company_id == current_user.company_id,
               Party.gstin.isnot(None),
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
        .order_by(Invoice.invoice_date)
    )).all()
    cdn_items_map: dict[str, list] = {}
    if cdn_rows:
        cdn_item_rows = (await db.execute(
            select(InvoiceItem).where(InvoiceItem.invoice_id.in_([n.id for n, _ in cdn_rows]))
        )).scalars().all()
        for it in cdn_item_rows:
            cdn_items_map.setdefault(str(it.invoice_id), []).append(it)

    cdnr_map: dict[str, list] = {}
    for note, party in cdn_rows:
        note_items = cdn_items_map.get(str(note.id), [])
        itms = [
            {
                "num": idx,
                "itm_det": {
                    "txval": _r2(item.amount),
                    "rt": float(item.gst_rate or 0),
                    "camt": _r2(item.cgst_amount),
                    "samt": _r2(item.sgst_amount),
                    "iamt": _r2(item.igst_amount),
                    "csamt": 0,
                },
            }
            for idx, item in enumerate(note_items, 1)
        ]
        if not itms:
            gst_total = _f(note.cgst_amount) + _f(note.sgst_amount) + _f(note.igst_amount)
            taxable = _f(note.taxable_amount)
            rate = round((gst_total / taxable * 100) if taxable > 0 else 0)
            itms = [{"num": 1, "itm_det": {
                "txval": _r2(note.taxable_amount), "rt": rate,
                "camt": _r2(note.cgst_amount), "samt": _r2(note.sgst_amount),
                "iamt": _r2(note.igst_amount), "csamt": 0}}]
        cdnr_map.setdefault(party.gstin, []).append({
            "ntty": "C" if note.invoice_type == "credit_note" else "D",
            "nt_num": note.invoice_no,
            "nt_dt": note.invoice_date.strftime("%d-%m-%Y"),
            "val": _r2(note.grand_total),
            "pos": party.billing_state_code or company_state_code,
            "rchrg": "N",
            "inv_typ": "R",
            "itms": itms,
        })

    payload = {
        "gstin": company_gstin,
        "fp": fp,
        "gt": _r2(total_turnover),
        "cur_gt": _r2(total_turnover),
        "b2b": [{"ctin": gstin, "inv": invs} for gstin, invs in b2b_map.items()],
        "b2cs": list(b2cs_map.values()),
        "cdnr": [{"ctin": g, "nt": nts} for g, nts in cdnr_map.items()],
        "hsn": {"data": hsn_data},
    }

    filename = f"GSTR1_{company_gstin}_{fp}.json"
    content = json.dumps(payload, indent=2, ensure_ascii=False)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ── GSTR-3B ─────────────────────────────────────────────────────────────────

@router.get("/gstr3b")
async def gstr3b(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GSTR-3B monthly summary:
    - 3.1: Outward supplies (taxable, nil-rated, non-GST)
    - 4: Eligible ITC from purchase invoices
    - Net tax payable
    """
    company = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    company_gstin = company.gstin if company else ""

    # 3.1(a) — Taxable outward supplies from finalized sale invoices
    sale_result = await db.execute(
        select(
            func.count(Invoice.id).label("count"),
            func.sum(Invoice.taxable_amount).label("taxable"),
            func.sum(Invoice.cgst_amount).label("cgst"),
            func.sum(Invoice.sgst_amount).label("sgst"),
            func.sum(Invoice.igst_amount).label("igst"),
            func.sum(Invoice.grand_total).label("total"),
        )
        .where(Invoice.invoice_type == "sale", Invoice.status == "final",
               Invoice.tax_type == "gst",
               Invoice.company_id == current_user.company_id,
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
    )
    sale_row = sale_result.one()

    # 3.1(e) — Non-GST outward supplies
    non_gst_result = await db.execute(
        select(
            func.count(Invoice.id).label("count"),
            func.sum(Invoice.grand_total).label("total"),
        )
        .where(Invoice.invoice_type == "sale", Invoice.status == "final",
               Invoice.tax_type == "non_gst",
               Invoice.company_id == current_user.company_id,
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
    )
    non_gst_row = non_gst_result.one()

    # 4(A)(5) — ITC from purchase invoices
    purchase_result = await db.execute(
        select(
            func.count(Invoice.id).label("count"),
            func.sum(Invoice.taxable_amount).label("taxable"),
            func.sum(Invoice.cgst_amount).label("cgst"),
            func.sum(Invoice.sgst_amount).label("sgst"),
            func.sum(Invoice.igst_amount).label("igst"),
            func.sum(Invoice.grand_total).label("total"),
        )
        .where(Invoice.invoice_type == "purchase", Invoice.status == "final",
               Invoice.tax_type == "gst",
               Invoice.company_id == current_user.company_id,
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
    )
    purch_row = purchase_result.one()

    # Credit/Debit notes — classify by source invoice type via reference_invoice_id.
    # Sale-side notes (CDN against a sale) adjust outward tax liability (3.1a).
    # Purchase-side notes (CDN against a purchase) adjust ITC (4A5).
    # Unlinked notes (no reference_invoice_id) default to sale-side (over-reports
    # liability — safer than under-reporting).
    from sqlalchemy.orm import aliased as _aliased
    _OrigInv = _aliased(Invoice)
    note_result = await db.execute(
        select(
            _OrigInv.invoice_type.label("orig_type"),
            Invoice.invoice_type.label("note_type"),
            func.sum(Invoice.taxable_amount).label("taxable"),
            func.sum(Invoice.cgst_amount).label("cgst"),
            func.sum(Invoice.sgst_amount).label("sgst"),
            func.sum(Invoice.igst_amount).label("igst"),
        )
        .outerjoin(_OrigInv, Invoice.reference_invoice_id == _OrigInv.id)
        .where(Invoice.invoice_type.in_(("credit_note", "debit_note")),
               Invoice.status == "final", Invoice.tax_type == "gst",
               Invoice.company_id == current_user.company_id,
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
        .group_by(_OrigInv.invoice_type, Invoice.invoice_type)
    )
    # sale-side CDN → adjusts 3.1(a); purchase-side CDN → adjusts 4(A)(5) ITC
    sale_note_taxable = sale_note_cgst = sale_note_sgst = sale_note_igst = 0.0
    purch_note_taxable = purch_note_cgst = purch_note_sgst = purch_note_igst = 0.0
    for r in note_result.all():
        sign = 1.0 if r.note_type == "debit_note" else -1.0
        orig = r.orig_type or "sale"  # unlinked notes default to sale-side
        if orig == "sale":
            sale_note_taxable += sign * _f(r.taxable)
            sale_note_cgst += sign * _f(r.cgst)
            sale_note_sgst += sign * _f(r.sgst)
            sale_note_igst += sign * _f(r.igst)
        else:  # purchase-side: credit note REDUCES ITC, debit note INCREASES ITC
            purch_note_taxable += sign * _f(r.taxable)
            purch_note_cgst += sign * _f(r.cgst)
            purch_note_sgst += sign * _f(r.sgst)
            purch_note_igst += sign * _f(r.igst)

    outward_taxable = _r2(_f(sale_row.taxable) + sale_note_taxable)
    outward_cgst = _r2(_f(sale_row.cgst) + sale_note_cgst)
    outward_sgst = _r2(_f(sale_row.sgst) + sale_note_sgst)
    outward_igst = _r2(_f(sale_row.igst) + sale_note_igst)
    outward_tax = _r2(outward_cgst + outward_sgst + outward_igst)

    itc_cgst = _r2(_f(purch_row.cgst) + purch_note_cgst)
    itc_sgst = _r2(_f(purch_row.sgst) + purch_note_sgst)
    itc_igst = _r2(_f(purch_row.igst) + purch_note_igst)
    itc_total = itc_cgst + itc_sgst + itc_igst

    net_cgst = _r2(outward_cgst - itc_cgst)
    net_sgst = _r2(outward_sgst - itc_sgst)
    net_igst = _r2(outward_igst - itc_igst)

    return {
        "gstin": company_gstin,
        "period": f"{from_date.strftime('%b %Y')} – {to_date.strftime('%b %Y')}",
        "section_3_1": {
            "a_taxable_outward": {
                "description": "Outward taxable supplies (other than zero rated, nil and exempted) — net of credit/debit notes",
                "invoice_count": int(sale_row.count or 0),
                "taxable_value": outward_taxable,
                "igst": outward_igst,
                "cgst": outward_cgst,
                "sgst": outward_sgst,
                "cess": 0.0,
                "total_tax": outward_tax,
                "credit_debit_note_adjustment": {
                    "taxable": _r2(sale_note_taxable),
                    "cgst": _r2(sale_note_cgst),
                    "sgst": _r2(sale_note_sgst),
                    "igst": _r2(sale_note_igst),
                },
            },
            "b_zero_rated": {
                "description": "Outward taxable supplies (zero rated)",
                "taxable_value": 0.0, "igst": 0.0, "cess": 0.0,
            },
            "c_nil_exempt": {
                "description": "Other outward supplies (nil rated, exempted)",
                "inter_state": 0.0, "intra_state": 0.0,
            },
            "d_reverse_charge_inward": {
                "description": "Inward supplies (liable to reverse charge)",
                "taxable_value": 0.0, "igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0,
            },
            "e_non_gst": {
                "description": "Non-GST outward supplies",
                "invoice_count": int(non_gst_row.count or 0),
                "total_value": _r2(non_gst_row.total),
                "inter_state": 0.0, "intra_state": _r2(non_gst_row.total),
            },
        },
        "section_4": {
            "a_itc_available": {
                "all_other_itc": {
                    "description": "All other ITC — purchases from GST-registered suppliers (net of purchase credit/debit notes)",
                    "invoice_count": int(purch_row.count or 0),
                    "taxable_value": _r2(_f(purch_row.taxable) + purch_note_taxable),
                    "igst": itc_igst,
                    "cgst": itc_cgst,
                    "sgst": itc_sgst,
                    "cess": 0.0,
                    "total_itc": itc_total,
                }
            },
            "b_itc_reversed": {
                "description": "ITC reversed / ineligible",
                "igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0,
            },
            "net_itc": {"igst": itc_igst, "cgst": itc_cgst, "sgst": itc_sgst, "cess": 0.0, "total": itc_total},
        },
        "net_tax_payable": {
            "igst": net_igst,
            "cgst": net_cgst,
            "sgst": net_sgst,
            "cess": 0.0,
            "total": _r2(net_igst + net_cgst + net_sgst),
        },
    }


# ── Profit & Loss ────────────────────────────────────────────────────────────

@router.get("/profit-loss")
async def profit_loss(
    from_date: date = Query(...),
    to_date: date = Query(...),
    opening_stock: float | None = Query(None),
    closing_stock: float | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full P&L by month:
        Revenue (sales, net of credit/debit notes)
      − COGS (purchase invoices, optionally stock-adjusted)
      = Gross profit
      − Operating expenses: Labour · Store inventory (at purchase) · Fuel · Commission · Overhead
      − Bad-debt write-offs
      = Net profit
    Operating-expense lines come from optional feature modules and degrade to zero
    (never error) on a tenant that doesn't have them.

    F3 (manual stock-adjusted COGS): when `opening_stock` / `closing_stock` VALUES
    (₹, entered by the accountant from the CA's figures) are supplied, COGS is
    adjusted at the period level to the goods ACTUALLY sold:
        COGS = opening stock + purchases − closing stock
    i.e. a stock-adjustment of (opening − closing) is added to raw purchases. When
    both are omitted, COGS = purchases-in-period (unchanged, non-breaking).
    The stock tables carry quantity only (no cost basis), so valuation is a manual
    input by design — see the `notes` in the response. (Costing decision: 2026-07-26.)

    F6 (pass-through charges): freight, vehicle rent and royalty are billed at cost
    and deliberately excluded from BOTH revenue and expense (net-zero) — surfaced
    as a caveat in `notes`, not a calc change. (Policy decision: 2026-07-26.)
    """
    yr = func.extract("year", Invoice.invoice_date)
    mo = func.extract("month", Invoice.invoice_date)

    # Monthly revenue from finalized sale invoices
    rev_result = await db.execute(
        select(
            yr.label("yr"),
            mo.label("mo"),
            func.sum(Invoice.taxable_amount).label("taxable"),
            func.sum(Invoice.grand_total).label("total"),
            func.count(Invoice.id).label("count"),
        )
        .where(Invoice.invoice_type == "sale", Invoice.status == "final",
               Invoice.company_id == current_user.company_id,
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
        .group_by(yr, mo)
        .order_by(yr, mo)
    )

    # Monthly COGS from finalized purchase invoices
    cogs_result = await db.execute(
        select(
            yr.label("yr"),
            mo.label("mo"),
            func.sum(Invoice.taxable_amount).label("taxable"),
            func.sum(Invoice.grand_total).label("total"),
            func.count(Invoice.id).label("count"),
        )
        .where(Invoice.invoice_type == "purchase", Invoice.status == "final",
               Invoice.company_id == current_user.company_id,
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
        .group_by(yr, mo)
        .order_by(yr, mo)
    )

    # Monthly bad-debt write-offs (group by write_off_at month, not invoice month —
    # writes-offs are recorded when the decision is made, not when the invoice was raised)
    wo_yr = func.extract("year", Invoice.write_off_at)
    wo_mo = func.extract("month", Invoice.write_off_at)
    wo_result = await db.execute(
        select(
            wo_yr.label("yr"),
            wo_mo.label("mo"),
            func.sum(Invoice.write_off_amount).label("total"),
            func.count(Invoice.id).label("count"),
        )
        .where(
            Invoice.invoice_type == "sale",
            Invoice.write_off_amount > 0,
            Invoice.write_off_at.isnot(None),
            Invoice.company_id == current_user.company_id,
            func.date(Invoice.write_off_at) >= from_date,
            func.date(Invoice.write_off_at) <= to_date,
        )
        .group_by(wo_yr, wo_mo)
    )

    # Credit/Debit notes against SALES — net them from revenue.
    #   credit_note REDUCES revenue (sales return / rate allowance)
    #   debit_note  INCREASES revenue (under-billing correction)
    # Netted on the same TAXABLE (ex-GST) basis as revenue above.
    note_yr = func.extract("year", Invoice.invoice_date)
    note_mo = func.extract("month", Invoice.invoice_date)
    # Guard (F7): only SALE-side notes net against revenue. A note raised against a
    # PURCHASE would belong against COGS, not revenue — exclude it here so a future
    # purchase-side note can't silently mis-hit revenue. A note with no reference is
    # treated as sale-side (today's only path). `_ref` = the referenced invoice.
    from sqlalchemy import exists
    from sqlalchemy.orm import aliased
    _ref = aliased(Invoice)
    note_result = await db.execute(
        select(
            note_yr.label("yr"), note_mo.label("mo"),
            Invoice.invoice_type.label("itype"),
            func.sum(Invoice.taxable_amount).label("taxable"),
        )
        .where(
            Invoice.invoice_type.in_(("credit_note", "debit_note")),
            Invoice.status == "final",
            Invoice.tax_type == "gst",   # exclude non-GST Bill of Supply returns — consistent with GSTR-1 treatment
            Invoice.company_id == current_user.company_id,
            Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date,
            ~exists().where(_ref.id == Invoice.reference_invoice_id,
                            _ref.invoice_type == "purchase"),
        )
        .group_by(note_yr, note_mo, Invoice.invoice_type)
    )

    import calendar

    def _month_label(yr_val, mo_val) -> tuple[str, str]:
        y, m = int(yr_val), int(mo_val)
        return f"{y}-{m:02d}", f"{calendar.month_abbr[m]} {y}"

    # ── Operating expenses (FULL P&L) ────────────────────────────────────────
    # A trading account is only Sales − Purchases. A real P&L also subtracts
    # operating costs. These come from OPTIONAL feature modules (workforce /
    # inventory / fuel / agents) whose tables may not exist on a given tenant, so
    # each aggregation runs in its OWN SAVEPOINT — a missing table degrades that
    # line to zero instead of aborting the whole P&L transaction.
    exp_params = {"cid": str(current_user.company_id), "fd": from_date, "td": to_date}

    async def _expense_by_month(sql: str) -> dict[str, float]:
        out: dict[str, float] = {}
        try:
            async with db.begin_nested():
                rows = (await db.execute(text(sql), exp_params)).all()
            for row in rows:
                if row.yr is None or row.mo is None:
                    continue
                k, _ = _month_label(row.yr, row.mo)
                out[k] = _r2(out.get(k, 0.0) + float(row.total or 0))
        except Exception as e:  # noqa: BLE001 — missing feature-module table, etc.
            logger.warning("P&L expense line skipped: %s", str(e)[:140])
        return out

    # LABOUR: wages + salary + bonus, less deductions. ADVANCES are EXCLUDED — a
    # worker advance is a loan recovered from later wages, so counting it as an
    # expense as well would double-count labour.
    labour_by_month = await _expense_by_month(
        "SELECT EXTRACT(year FROM pay_date) AS yr, EXTRACT(month FROM pay_date) AS mo, "
        "SUM(CASE WHEN payment_type='deduction' THEN -amount ELSE amount END) AS total "
        "FROM worker_payments WHERE company_id = :cid "
        "AND payment_type IN ('wage','salary','bonus','deduction') "
        "AND pay_date >= :fd AND pay_date <= :td GROUP BY 1, 2")

    # STORE INVENTORY: recognised WHEN PURCHASED (received), valued at the PO unit
    # price. A receipt transaction references its PO; join the PO item for price.
    store_by_month = await _expense_by_month(
        "SELECT EXTRACT(year FROM t.created_at) AS yr, EXTRACT(month FROM t.created_at) AS mo, "
        "SUM(t.quantity * COALESCE(pi.unit_price, 0)) AS total "
        "FROM inventory_transactions t "
        "JOIN inventory_po_items pi ON pi.po_id = t.reference_id AND pi.item_id = t.item_id "
        "WHERE t.company_id = :cid AND t.transaction_type = 'receipt' "
        # CAST(created_at AS date) — comparing the date part avoids a ':param::type'
        # cast, which SQLAlchemy's text() parser rejects as a syntax error, and
        # covers the whole final day without timestamp-boundary arithmetic.
        "AND CAST(t.created_at AS date) >= :fd AND CAST(t.created_at AS date) <= :td GROUP BY 1, 2")

    # FUEL: exclude plant_tank fills — that diesel was already expensed when it was
    # purchased into the store inventory above (prevents double-counting).
    fuel_by_month = await _expense_by_month(
        "SELECT EXTRACT(year FROM entry_date) AS yr, EXTRACT(month FROM entry_date) AS mo, "
        "SUM(amount) AS total FROM vehicle_fuel_entries WHERE company_id = :cid "
        "AND COALESCE(fuel_source,'') <> 'plant_tank' "
        "AND entry_date >= :fd AND entry_date <= :td GROUP BY 1, 2")

    # COMMISSION: agent/broker commission snapshotted on finalised sale invoices.
    commission_by_month = await _expense_by_month(
        "SELECT EXTRACT(year FROM invoice_date) AS yr, EXTRACT(month FROM invoice_date) AS mo, "
        "SUM(COALESCE(commission_amount,0)) AS total FROM invoices WHERE company_id = :cid "
        "AND invoice_type='sale' AND status='final' AND COALESCE(commission_amount,0) > 0 "
        "AND invoice_date >= :fd AND invoice_date <= :td GROUP BY 1, 2")

    # OVERHEAD EXPENSES: direct-expense vouchers (electricity, rent, repairs…) —
    # a voucher tagged with an expense_category. Recognised on the voucher date.
    overhead_by_month = await _expense_by_month(
        "SELECT EXTRACT(year FROM voucher_date) AS yr, EXTRACT(month FROM voucher_date) AS mo, "
        "SUM(amount) AS total FROM payment_vouchers WHERE company_id = :cid "
        "AND expense_category IS NOT NULL "
        "AND voucher_date >= :fd AND voucher_date <= :td GROUP BY 1, 2")

    rev_by_month: dict[str, dict] = {}
    for r in rev_result.all():
        key, label = _month_label(r.yr, r.mo)
        # Revenue is the TAXABLE (ex-GST) value — output GST collected is a
        # liability to the government, NOT income. (Bill-of-Supply cash sales
        # have taxable == grand_total, so they're unaffected.)
        rev_by_month[key] = {"month": key, "label": label, "revenue": _r2(r.taxable), "revenue_with_tax": _r2(r.total), "sale_count": int(r.count)}

    cogs_by_month: dict[str, dict] = {}
    for r in cogs_result.all():
        key, label = _month_label(r.yr, r.mo)
        # COGS is the TAXABLE (ex-GST) value — input GST paid is recoverable
        # ITC, not a cost.
        cogs_by_month[key] = {"month": key, "label": label, "cogs": _r2(r.taxable), "cogs_with_tax": _r2(r.total), "purchase_count": int(r.count)}

    wo_by_month: dict[str, dict] = {}
    for r in wo_result.all():
        if r.yr is None or r.mo is None:
            continue
        key, label = _month_label(r.yr, r.mo)
        wo_by_month[key] = {"month": key, "label": label, "write_off": _r2(r.total or 0), "write_off_count": int(r.count or 0)}

    # Net credit (−) / debit (+) notes per month, on the taxable basis
    note_net_by_month: dict[str, float] = {}
    for r in note_result.all():
        if r.yr is None or r.mo is None:
            continue
        key, _lbl = _month_label(r.yr, r.mo)
        signed = _r2(r.taxable or 0) if r.itype == "debit_note" else -_r2(r.taxable or 0)
        note_net_by_month[key] = _r2(note_net_by_month.get(key, 0.0) + signed)

    # Merge by month
    all_months = sorted(set(
        list(rev_by_month) + list(cogs_by_month) + list(wo_by_month)
        + list(note_net_by_month) + list(labour_by_month) + list(store_by_month)
        + list(fuel_by_month) + list(commission_by_month) + list(overhead_by_month)))
    monthly = []
    total_revenue = total_cogs = total_write_off = 0.0
    total_labour = total_store = total_fuel = total_commission = total_overhead = 0.0
    for key in all_months:
        rev = rev_by_month.get(key, {})
        cogs = cogs_by_month.get(key, {})
        wo = wo_by_month.get(key, {})
        label = rev.get("label") or cogs.get("label") or wo.get("label") or key
        note_net = note_net_by_month.get(key, 0.0)
        # Revenue net of credit/debit notes (sales returns reduce revenue)
        revenue = _r2(rev.get("revenue", 0.0) + note_net)
        cost = cogs.get("cogs", 0.0)
        write_off = wo.get("write_off", 0.0)
        labour = labour_by_month.get(key, 0.0)
        store = store_by_month.get(key, 0.0)
        fuel = fuel_by_month.get(key, 0.0)
        commission = commission_by_month.get(key, 0.0)
        overhead = overhead_by_month.get(key, 0.0)
        gross_profit = _r2(revenue - cost)
        operating_expenses = _r2(labour + store + fuel + commission + overhead)
        total_expenses = _r2(operating_expenses + write_off)
        net_profit = _r2(gross_profit - total_expenses)
        margin = _r2((net_profit / revenue * 100) if revenue > 0 else 0)
        total_revenue += revenue
        total_cogs += cost
        total_write_off += write_off
        total_labour += labour
        total_store += store
        total_fuel += fuel
        total_commission += commission
        total_overhead += overhead
        monthly.append({
            "month": key, "label": label,
            "revenue": revenue, "cogs": cost,
            "credit_debit_note_net": note_net,
            "gross_profit": gross_profit,
            # operating-expense breakdown (the full-P&L additions)
            "labour": labour,
            "store_inventory": store,
            "fuel": fuel,
            "commission": commission,
            "overhead": overhead,
            "write_off": write_off,
            "operating_expenses": operating_expenses,
            "total_expenses": total_expenses,
            "net_profit": net_profit,
            "margin_pct": margin,
            "sale_count": rev.get("sale_count", 0),
            "purchase_count": cogs.get("purchase_count", 0),
            "write_off_count": wo.get("write_off_count", 0),
        })

    purchases_in_period = _r2(total_cogs)
    # F3 — manual stock-adjusted COGS at the period level.
    # COGS = opening stock + purchases − closing stock. Applied only when the
    # accountant supplies opening/closing VALUES (₹); otherwise COGS = purchases.
    stock_adjusted = opening_stock is not None or closing_stock is not None
    op_stock = _r2(opening_stock or 0)
    cl_stock = _r2(closing_stock or 0)
    stock_adjustment = _r2(op_stock - cl_stock)   # +adds to COGS when opening > closing
    effective_cogs = _r2(purchases_in_period + stock_adjustment) if stock_adjusted else purchases_in_period

    total_gross = _r2(total_revenue - effective_cogs)
    total_opex = _r2(total_labour + total_store + total_fuel + total_commission + total_overhead)
    total_expenses_all = _r2(total_opex + total_write_off)
    total_net = _r2(total_gross - total_expenses_all)

    notes = [
        ("Stock-adjusted COGS = opening stock + purchases − closing stock (manual figures you entered)."
         if stock_adjusted else
         "COGS = purchase invoices booked in this period (no opening/closing-stock adjustment). "
         "Enter opening & closing stock values above for a goods-sold basis — your CA's figures."),
        "Pass-through charges (freight, vehicle rent, royalty) are billed at cost and excluded from "
        "both revenue and expense (net-zero) — they do not affect this P&L.",
    ]
    return {
        "period": f"{from_date.isoformat()} to {to_date.isoformat()}",
        "summary": {
            "total_revenue": _r2(total_revenue),
            "total_cogs": effective_cogs,
            "purchases": purchases_in_period,
            "opening_stock": op_stock if stock_adjusted else None,
            "closing_stock": cl_stock if stock_adjusted else None,
            "stock_adjustment": stock_adjustment if stock_adjusted else 0.0,
            "stock_adjusted": stock_adjusted,
            "gross_profit": total_gross,
            "labour": _r2(total_labour),
            "store_inventory": _r2(total_store),
            "fuel": _r2(total_fuel),
            "commission": _r2(total_commission),
            "overhead": _r2(total_overhead),
            "total_write_off": _r2(total_write_off),
            "operating_expenses": total_opex,
            "total_expenses": total_expenses_all,
            "net_profit": total_net,
            "margin_pct": _r2((total_net / total_revenue * 100) if total_revenue > 0 else 0),
        },
        "monthly": monthly,
        "notes": notes,
    }


# ── Stock valuation (manual opening/closing stock values for stock-adjusted COGS, F3) ──
_STOCK_VAL_KEY = "stock_valuation"


@router.get("/stock-valuation")
async def get_stock_valuation(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the last-saved manual opening/closing stock values (₹) for P&L.

    {"opening": <float|None>, "closing": <float|None>, "note": <str>}. Empty
    defaults when never set. Read by the P&L tab to pre-fill the F3 inputs.
    """
    default = {"opening": None, "closing": None, "note": ""}
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key = :k"),
            {"k": _STOCK_VAL_KEY},
        )).fetchone()
        if row:
            cfg = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return {**default, **(cfg or {})}
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
    return default


@router.put("/stock-valuation")
async def put_stock_valuation(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "accountant")),
):
    """Persist manual opening/closing stock values (₹) — accountant/admin only.

    Body: {"opening": <number|null>, "closing": <number|null>, "note": <str>}.
    """
    def _num(v):
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    clean = {
        "opening": _num(payload.get("opening")),
        "closing": _num(payload.get("closing")),
        "note": str(payload.get("note") or "")[:500],
    }
    await db.execute(
        text("""
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (:k, :v, NOW())
            ON CONFLICT (key) DO UPDATE
              SET value = EXCLUDED.value, updated_at = NOW()
        """),
        {"k": _STOCK_VAL_KEY, "v": json.dumps(clean)},
    )
    await db.commit()
    return {"ok": True, **clean}


# ── Traditional Day Book (classic cash book: opening B/F → receipts / payments
#    across Cash · Bank · CC columns → closing C/F) ─────────────────────────────
# Reconstructs the hand-written daily cash book from existing transactions:
#   RECEIPTS (money in)  = payment_receipts
#   PAYMENTS (money out) = payment_vouchers (supplier + direct expense) · worker
#                          payments (excl. deduction) · diesel fills (non plant_tank)
#                          · agent commission payouts
# Each line is placed in ONE money column by its payment mode:
#   cash → Cash · cc/od → CC · everything else (upi/bank/cheque/card…) → Bank.
# Opening B/F is rolled forward from a one-time admin-set opening
# (app_settings.day_book_opening {as_of_date, cash, bank, cc}); closing C/F =
# opening + Σreceipts − Σpayments per column. Every source is savepoint-guarded
# so a tenant missing a feature-module table degrades that line to nothing.
_DAY_BOOK_OPENING_KEY = "day_book_opening"


def _daybook_col(mode) -> str:
    m = (mode or "cash").strip().lower()
    if m == "cash":
        return "cash"
    if m in ("cc", "od", "cc_account", "overdraft", "cash_credit"):
        return "cc"
    return "bank"   # upi, bank, bank_transfer, cheque, card, neft, rtgs, online, …


async def _daybook_savepoint_rows(db: AsyncSession, sql: str, params: dict) -> list:
    """Run one source query inside its own SAVEPOINT; [] if the table is absent."""
    try:
        async with db.begin_nested():
            return list((await db.execute(text(sql), params)).mappings().all())
    except Exception as e:  # noqa: BLE001 — missing feature-module table, etc.
        logger.warning("Day Book source skipped: %s", str(e)[:140])
        return []


def _blank_cols() -> dict:
    return {"cash": 0.0, "bank": 0.0, "cc": 0.0}


async def _daybook_lines(db: AsyncSession, cid, day: date) -> tuple[list, list]:
    """Return (receipts[], payments[]) line items for a single day."""
    p = {"cid": str(cid), "d": day}
    receipts, payments = [], []

    # RECEIPTS — collections
    for r in await _daybook_savepoint_rows(db,
        "SELECT r.amount AS amount, r.payment_mode AS mode, r.receipt_no AS ref, "
        "COALESCE(pt.name,'Cash sale') AS party "
        "FROM payment_receipts r LEFT JOIN parties pt ON pt.id=r.party_id "
        "WHERE r.company_id=:cid AND r.receipt_date=:d ORDER BY r.created_at", p):
        line = {"particulars": r["party"], "ref": r["ref"], **_blank_cols()}
        line[_daybook_col(r["mode"])] = _r2(r["amount"])
        receipts.append(line)

    # PAYMENTS — supplier payments + direct expenses (vouchers)
    for v in await _daybook_savepoint_rows(db,
        "SELECT v.amount AS amount, v.payment_mode AS mode, v.voucher_no AS ref, "
        "v.expense_category AS cat, pt.name AS party "
        "FROM payment_vouchers v LEFT JOIN parties pt ON pt.id=v.party_id "
        "WHERE v.company_id=:cid AND v.voucher_date=:d ORDER BY v.created_at", p):
        who = v["cat"] or v["party"] or "Payment"
        line = {"particulars": who, "ref": v["ref"], **_blank_cols()}
        line[_daybook_col(v["mode"])] = _r2(v["amount"])
        payments.append(line)

    # PAYMENTS — worker wages/salary/advance/bonus (deductions are not cash out)
    for w in await _daybook_savepoint_rows(db,
        "SELECT wp.amount AS amount, wp.mode AS mode, wp.reference AS ref, "
        "wp.payment_type AS ptype, wk.name AS worker "
        "FROM worker_payments wp LEFT JOIN workers wk ON wk.id=wp.worker_id "
        "WHERE wp.company_id=:cid AND wp.pay_date=:d AND wp.payment_type<>'deduction' "
        "ORDER BY wp.created_at", p):
        label = f"{w['worker'] or 'Worker'} ({(w['ptype'] or '').replace('_',' ')})".strip()
        line = {"particulars": label, "ref": w["ref"], **_blank_cols()}
        line[_daybook_col(w["mode"])] = _r2(w["amount"])
        payments.append(line)

    # PAYMENTS — diesel fills (outside purchases; plant-tank issues are internal stock, not cash)
    for f in await _daybook_savepoint_rows(db,
        "SELECT f.amount AS amount, f.litres AS litres, ve.registration_no AS veh "
        "FROM vehicle_fuel_entries f LEFT JOIN vehicles ve ON ve.id=f.vehicle_id "
        "WHERE f.company_id=:cid AND f.entry_date=:d AND COALESCE(f.fuel_source,'')<>'plant_tank' "
        "ORDER BY f.created_at", p):
        label = f"Diesel {f['veh'] or ''} {_r2(f['litres'])}L".strip()
        line = {"particulars": label, "ref": "", **_blank_cols()}
        line["cash"] = _r2(f["amount"])   # fuel fills carry no mode → treated as cash
        payments.append(line)

    # PAYMENTS — agent commission payouts
    for a in await _daybook_savepoint_rows(db,
        "SELECT ap.amount AS amount, ap.payment_mode AS mode, ap.reference_no AS ref, ag.name AS agent "
        "FROM agent_commission_payments ap LEFT JOIN agents ag ON ag.id=ap.agent_id "
        "WHERE ap.company_id=:cid AND ap.paid_on=:d ORDER BY ap.created_at", p):
        line = {"particulars": f"Commission — {a['agent'] or ''}".strip(), "ref": a["ref"], **_blank_cols()}
        line[_daybook_col(a["mode"])] = _r2(a["amount"])
        payments.append(line)

    return receipts, payments


async def _daybook_range_net(db: AsyncSession, cid, d_from: date, d_to: date) -> dict:
    """Net movement per column (in − out) over [d_from, d_to] — for the opening roll-forward."""
    net = _blank_cols()
    if d_from > d_to:
        return net
    p = {"cid": str(cid), "fd": d_from, "td": d_to}

    def _fold(rows, sign):
        for row in rows:
            net[_daybook_col(row["mode"])] += sign * float(row["total"] or 0)

    _fold(await _daybook_savepoint_rows(db,
        "SELECT LOWER(COALESCE(payment_mode,'cash')) AS mode, SUM(amount) AS total "
        "FROM payment_receipts WHERE company_id=:cid AND receipt_date>=:fd AND receipt_date<=:td "
        "GROUP BY 1", p), +1)
    _fold(await _daybook_savepoint_rows(db,
        "SELECT LOWER(COALESCE(payment_mode,'cash')) AS mode, SUM(amount) AS total "
        "FROM payment_vouchers WHERE company_id=:cid AND voucher_date>=:fd AND voucher_date<=:td "
        "GROUP BY 1", p), -1)
    _fold(await _daybook_savepoint_rows(db,
        "SELECT LOWER(COALESCE(mode,'cash')) AS mode, SUM(amount) AS total "
        "FROM worker_payments WHERE company_id=:cid AND payment_type<>'deduction' "
        "AND pay_date>=:fd AND pay_date<=:td GROUP BY 1", p), -1)
    _fold(await _daybook_savepoint_rows(db,
        "SELECT 'cash' AS mode, SUM(amount) AS total FROM vehicle_fuel_entries "
        "WHERE company_id=:cid AND COALESCE(fuel_source,'')<>'plant_tank' "
        "AND entry_date>=:fd AND entry_date<=:td GROUP BY 1", p), -1)
    _fold(await _daybook_savepoint_rows(db,
        "SELECT LOWER(COALESCE(payment_mode,'cash')) AS mode, SUM(amount) AS total "
        "FROM agent_commission_payments WHERE company_id=:cid AND paid_on>=:fd AND paid_on<=:td "
        "GROUP BY 1", p), -1)
    return {k: _r2(v) for k, v in net.items()}


async def _daybook_opening(db: AsyncSession, cid, day: date) -> tuple[dict, dict | None]:
    """Opening balance B/F for `day` = configured opening (as-of a base date) rolled
    forward by the net movement between the base date and the day before `day`.
    Returns (opening_cols, config_or_None)."""
    cfg = None
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key=:k"),
            {"k": _DAY_BOOK_OPENING_KEY})).fetchone()
        if row:
            cfg = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    except Exception:
        try: await db.rollback()
        except Exception: pass
    if not cfg or not cfg.get("as_of_date"):
        return _blank_cols(), cfg
    try:
        as_of = date.fromisoformat(str(cfg["as_of_date"])[:10])
    except Exception:
        return _blank_cols(), cfg
    base = {"cash": _r2(cfg.get("cash") or 0), "bank": _r2(cfg.get("bank") or 0),
            "cc": _r2(cfg.get("cc") or 0)}
    if as_of > day:
        return _blank_cols(), cfg   # base is after the requested day — nothing to roll
    net = await _daybook_range_net(db, cid, as_of, day - timedelta(days=1))
    return ({k: _r2(base[k] + net[k]) for k in base}, cfg)


@router.get("/day-book")
async def day_book(
    date_: date = Query(None, alias="date"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Traditional daily cash book: opening B/F → receipts + payments (Cash/Bank/CC)
    → closing C/F, for a single day (defaults today)."""
    day = date_ or date.today()
    cid = current_user.company_id
    opening, _cfg = await _daybook_opening(db, cid, day)
    receipts, payments = await _daybook_lines(db, cid, day)

    tot_r = _blank_cols(); tot_p = _blank_cols()
    for ln in receipts:
        for k in tot_r: tot_r[k] = _r2(tot_r[k] + ln[k])
    for ln in payments:
        for k in tot_p: tot_p[k] = _r2(tot_p[k] + ln[k])
    closing = {k: _r2(opening[k] + tot_r[k] - tot_p[k]) for k in opening}
    return {
        "date": day.isoformat(),
        "opening": opening,
        "receipts": receipts,
        "payments": payments,
        "totals": {"receipts": tot_r, "payments": tot_p},
        "closing": closing,
        "notes": [
            "Cash / Bank columns are populated by each transaction's payment mode "
            "(cash → Cash; UPI/bank/cheque/card → Bank). The CC/OD column carries its "
            "opening balance forward — tag a payment mode to it to record CC movements.",
            "Payments = supplier & expense vouchers, worker wages/advances, diesel fills, "
            "commission payouts. Store-item purchases appear when paid via a voucher.",
        ],
    }


@router.get("/day-book-opening")
async def get_day_book_opening(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the configured opening balance base for the Day Book."""
    default = {"as_of_date": None, "cash": 0.0, "bank": 0.0, "cc": 0.0, "note": ""}
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key=:k"),
            {"k": _DAY_BOOK_OPENING_KEY})).fetchone()
        if row:
            cfg = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return {**default, **(cfg or {})}
    except Exception:
        try: await db.rollback()
        except Exception: pass
    return default


@router.put("/day-book-opening")
async def put_day_book_opening(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "accountant")),
):
    """Set the opening-balance base (a date + Cash/Bank/CC amounts) that the Day
    Book rolls forward. Admin/accountant only."""
    def _num(v):
        try: return float(v) if v not in (None, "") else 0.0
        except (TypeError, ValueError): return 0.0
    as_of = payload.get("as_of_date")
    if as_of:
        try: as_of = date.fromisoformat(str(as_of)[:10]).isoformat()
        except Exception: raise HTTPException(400, "as_of_date must be YYYY-MM-DD")
    clean = {"as_of_date": as_of or None, "cash": _num(payload.get("cash")),
             "bank": _num(payload.get("bank")), "cc": _num(payload.get("cc")),
             "note": str(payload.get("note") or "")[:500]}
    await db.execute(
        text("""INSERT INTO app_settings (key, value, updated_at)
                VALUES (:k, :v, NOW())
                ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()"""),
        {"k": _DAY_BOOK_OPENING_KEY, "v": json.dumps(clean)})
    await db.commit()
    return {"ok": True, **clean}


# ── EOD Daily Business Summary (cash-book view) ──────────────────────────────
# A CASH/END-OF-DAY lens, DISTINCT from the accrual P&L above:
#   • Sales split by how the money came in — CASH vs ELECTRONIC (bank/card/UPI),
#     read from the payment RECEIPTS (collections), per the owner's definition.
#   • Money OUT itemised: purchases · store inventory · diesel · salary · advance
#     · commission. Note ADVANCES ARE INCLUDED here (real cash out today) —
#     unlike the P&L, where an advance is a balance-sheet item, not an expense.
# Optional feature-module tables (worker_payments / inventory / fuel) each run in
# their own SAVEPOINT and degrade to zero on a tenant that doesn't have them.

async def compute_eod_summary(db: AsyncSession, company_id, from_date: date, to_date: date,
                              basis: str = "accrual") -> dict:
    """Per-day cash-in (cash vs electronic) + money-out breakdown, plus totals.
    Shared by the HTTP endpoint and the scheduled EOD notification.

    ``basis`` selects how money-OUT is measured:
      • 'accrual' (default, unchanged): purchases booked on the purchase-invoice
        date + accrued agent commission. This is what the Day Book has always shown.
      • 'cash': money actually paid — supplier payments (vouchers) on the payment
        date instead of purchase invoices, and accrued commission excluded (it's
        paid later). Store/diesel/salary/advance are already cash-when-recorded and
        are unchanged; overhead expense-vouchers appear in BOTH bases.
    Cash-IN (receipts) is identical in both bases — it is already a cash event.
    """
    basis = "cash" if str(basis).lower() == "cash" else "accrual"
    params = {"cid": str(company_id), "fd": from_date, "td": to_date}

    async def _daily(sql: str) -> dict[str, float]:
        out: dict[str, float] = {}
        try:
            async with db.begin_nested():
                rows = (await db.execute(text(sql), params)).all()
            for r in rows:
                if r.d is None:
                    continue
                k = r.d.isoformat() if hasattr(r.d, "isoformat") else str(r.d)
                out[k] = _r2(out.get(k, 0.0) + float(r.total or 0))
        except Exception as e:  # noqa: BLE001 — missing feature-module table, etc.
            logger.warning("EOD summary line skipped: %s", str(e)[:140])
        return out

    # SALES IN — collections split by payment mode. Cash = literally 'cash';
    # everything else (upi/bank_transfer/cheque/card…) = "electronic".
    cash = await _daily(
        "SELECT CAST(receipt_date AS date) AS d, SUM(amount) AS total FROM payment_receipts "
        "WHERE company_id=:cid AND LOWER(COALESCE(payment_mode,''))='cash' "
        "AND receipt_date>=:fd AND receipt_date<=:td GROUP BY 1")
    electronic = await _daily(
        "SELECT CAST(receipt_date AS date) AS d, SUM(amount) AS total FROM payment_receipts "
        "WHERE company_id=:cid AND LOWER(COALESCE(payment_mode,''))<>'cash' "
        "AND receipt_date>=:fd AND receipt_date<=:td GROUP BY 1")

    # MONEY OUT — expense categories (actual amounts incl. GST for a cash view).
    purchases = await _daily(
        "SELECT CAST(invoice_date AS date) AS d, SUM(grand_total) AS total FROM invoices "
        "WHERE company_id=:cid AND invoice_type='purchase' AND status='final' "
        "AND invoice_date>=:fd AND invoice_date<=:td GROUP BY 1")
    store = await _daily(
        "SELECT CAST(t.created_at AS date) AS d, SUM(t.quantity * COALESCE(pi.unit_price,0)) AS total "
        "FROM inventory_transactions t JOIN inventory_po_items pi "
        "ON pi.po_id=t.reference_id AND pi.item_id=t.item_id "
        "WHERE t.company_id=:cid AND t.transaction_type='receipt' "
        "AND CAST(t.created_at AS date)>=:fd AND CAST(t.created_at AS date)<=:td GROUP BY 1")
    diesel = await _daily(
        "SELECT CAST(entry_date AS date) AS d, SUM(amount) AS total FROM vehicle_fuel_entries "
        "WHERE company_id=:cid AND COALESCE(fuel_source,'')<>'plant_tank' "
        "AND entry_date>=:fd AND entry_date<=:td GROUP BY 1")
    salary = await _daily(
        "SELECT CAST(pay_date AS date) AS d, "
        "SUM(CASE WHEN payment_type='deduction' THEN -amount ELSE amount END) AS total "
        "FROM worker_payments WHERE company_id=:cid "
        "AND payment_type IN ('wage','salary','bonus','deduction') "
        "AND pay_date>=:fd AND pay_date<=:td GROUP BY 1")
    advance = await _daily(
        "SELECT CAST(pay_date AS date) AS d, SUM(amount) AS total FROM worker_payments "
        "WHERE company_id=:cid AND payment_type='advance' "
        "AND pay_date>=:fd AND pay_date<=:td GROUP BY 1")
    commission = await _daily(
        "SELECT CAST(invoice_date AS date) AS d, SUM(COALESCE(commission_amount,0)) AS total "
        "FROM invoices WHERE company_id=:cid AND invoice_type='sale' AND status='final' "
        "AND COALESCE(commission_amount,0)>0 "
        "AND invoice_date>=:fd AND invoice_date<=:td GROUP BY 1")
    # Overhead expenses (direct-expense vouchers) — real cash out, both bases.
    overhead = await _daily(
        "SELECT CAST(voucher_date AS date) AS d, SUM(amount) AS total FROM payment_vouchers "
        "WHERE company_id=:cid AND expense_category IS NOT NULL "
        "AND voucher_date>=:fd AND voucher_date<=:td GROUP BY 1")
    # Supplier payments (non-expense vouchers) — actual cash paid to suppliers; the
    # CASH-basis replacement for the accrual 'purchases' (invoice) line.
    supplier_pay = await _daily(
        "SELECT CAST(voucher_date AS date) AS d, SUM(amount) AS total FROM payment_vouchers "
        "WHERE company_id=:cid AND expense_category IS NULL "
        "AND voucher_date>=:fd AND voucher_date<=:td GROUP BY 1")

    all_days = sorted(set(
        list(cash) + list(electronic) + list(purchases) + list(store)
        + list(diesel) + list(salary) + list(advance) + list(commission)
        + list(overhead) + list(supplier_pay)))
    days = []
    tot = {k: 0.0 for k in ("cash_sales", "electronic_sales", "purchases", "supplier_payments",
                            "store_inventory", "diesel", "salary", "advance", "commission", "overhead")}
    for d in all_days:
        cs, es = cash.get(d, 0.0), electronic.get(d, 0.0)
        pu, st, di = purchases.get(d, 0.0), store.get(d, 0.0), diesel.get(d, 0.0)
        sa, ad, co = salary.get(d, 0.0), advance.get(d, 0.0), commission.get(d, 0.0)
        oh, sp = overhead.get(d, 0.0), supplier_pay.get(d, 0.0)
        total_sales = _r2(cs + es)
        # Money-out depends on the basis: accrual uses purchase invoices + accrued
        # commission; cash uses actual supplier payments (vouchers) and drops accrued
        # commission. store/diesel/salary/advance/overhead are common to both.
        common_out = st + di + sa + ad + oh
        total_exp = _r2(common_out + (sp if basis == "cash" else pu + co))
        days.append({
            "date": d, "cash_sales": cs, "electronic_sales": es, "total_sales": total_sales,
            "purchases": pu, "supplier_payments": sp, "store_inventory": st, "diesel": di,
            "salary": sa, "advance": ad, "commission": co, "overhead": oh,
            "total_expenses": total_exp, "net": _r2(total_sales - total_exp),
        })
        tot["cash_sales"] += cs; tot["electronic_sales"] += es
        tot["purchases"] += pu; tot["supplier_payments"] += sp
        tot["store_inventory"] += st; tot["diesel"] += di
        tot["salary"] += sa; tot["advance"] += ad; tot["commission"] += co; tot["overhead"] += oh
    summary = {k: _r2(v) for k, v in tot.items()}
    summary["total_sales"] = _r2(summary["cash_sales"] + summary["electronic_sales"])
    _common = (summary["store_inventory"] + summary["diesel"] + summary["salary"]
               + summary["advance"] + summary["overhead"])
    summary["total_expenses"] = _r2(_common + (
        summary["supplier_payments"] if basis == "cash"
        else summary["purchases"] + summary["commission"]))
    summary["net"] = _r2(summary["total_sales"] - summary["total_expenses"])
    return {"from_date": from_date.isoformat(), "to_date": to_date.isoformat(),
            "basis": basis, "days": days, "summary": summary}


async def build_eod_summary_context(db: AsyncSession, company_id, company_name: str, target_date: date) -> dict:
    """Notification context for the daily EOD summary (email + Telegram)."""
    data = await compute_eod_summary(db, company_id, target_date, target_date)
    s = data["summary"]
    money = lambda v: f"{float(v or 0):,.0f}"  # noqa: E731
    return {
        "company_name": company_name,
        "date": target_date.strftime("%d %b %Y"),
        "cash_sales": money(s["cash_sales"]),
        "electronic_sales": money(s["electronic_sales"]),
        "total_sales": money(s["total_sales"]),
        "purchases": money(s["purchases"]),
        "store_inventory": money(s["store_inventory"]),
        "diesel": money(s["diesel"]),
        "salary": money(s["salary"]),
        "advance": money(s["advance"]),
        "commission": money(s["commission"]),
        "total_expenses": money(s["total_expenses"]),
        "net": money(s["net"]),
        "net_emoji": "🟢" if s["net"] >= 0 else "🔴",
    }


async def compute_eod_detail(db: AsyncSession, company_id, target_date: date) -> dict:
    """Line-item breakup behind a single Day-Book day — every individual receipt,
    purchase, store issue, diesel fill, wage/advance and commission — so the owner
    can drill from a day's totals into the underlying transactions (and export)."""
    params = {"cid": str(company_id), "d": target_date}
    items: list[dict] = []

    async def _rows(sql: str):
        try:
            async with db.begin_nested():
                return (await db.execute(text(sql), params)).all()
        except Exception as e:  # noqa: BLE001 — missing feature-module table, etc.
            logger.warning("EOD detail line skipped: %s", str(e)[:140])
            return []

    # SALES IN — receipts split by payment mode
    for r in await _rows(
        "SELECT r.receipt_no AS ref, COALESCE(p.name,'') AS party, "
        "LOWER(COALESCE(r.payment_mode,'')) AS mode, r.amount AS amount "
        "FROM payment_receipts r LEFT JOIN parties p ON p.id=r.party_id "
        "WHERE r.company_id=:cid AND r.receipt_date=:d ORDER BY r.amount DESC"):
        is_cash = (r.mode == "cash")
        items.append({"category": "Cash Sale" if is_cash else "Credit Sale",
                      "ref": r.ref or "", "party": r.party or "",
                      "detail": (r.mode or "").upper(), "amount": _r2(r.amount), "direction": "in"})

    # MONEY OUT — purchases
    for r in await _rows(
        "SELECT i.invoice_no AS ref, COALESCE(p.name,'') AS party, i.grand_total AS amount "
        "FROM invoices i LEFT JOIN parties p ON p.id=i.party_id "
        "WHERE i.company_id=:cid AND i.invoice_type='purchase' AND i.status='final' "
        "AND i.invoice_date=:d ORDER BY i.grand_total DESC"):
        items.append({"category": "Purchase", "ref": r.ref or "", "party": r.party or "",
                      "detail": "", "amount": _r2(r.amount), "direction": "out"})

    # Store inventory receipts (at PO price)
    for r in await _rows(
        "SELECT COALESCE(po.po_no,'') AS ref, COALESCE(pi.item_name,'') AS item, "
        "t.quantity AS qty, COALESCE(pi.unit_price,0) AS price, "
        "(t.quantity*COALESCE(pi.unit_price,0)) AS amount "
        "FROM inventory_transactions t "
        "JOIN inventory_po_items pi ON pi.po_id=t.reference_id AND pi.item_id=t.item_id "
        "LEFT JOIN inventory_purchase_orders po ON po.id=t.reference_id "
        "WHERE t.company_id=:cid AND t.transaction_type='receipt' AND CAST(t.created_at AS date)=:d"):
        items.append({"category": "Store", "ref": r.ref or "", "party": r.item or "",
                      "detail": f"{float(r.qty or 0):g} @ {float(r.price or 0):g}",
                      "amount": _r2(r.amount), "direction": "out"})

    # Diesel (plant_tank excluded — already counted in store)
    for r in await _rows(
        "SELECT COALESCE(v.registration_no,'') AS party, f.litres AS litres, "
        "COALESCE(f.fuel_source,'') AS src, f.amount AS amount "
        "FROM vehicle_fuel_entries f LEFT JOIN vehicles v ON v.id=f.vehicle_id "
        "WHERE f.company_id=:cid AND COALESCE(f.fuel_source,'')<>'plant_tank' AND f.entry_date=:d"):
        items.append({"category": "Diesel", "ref": "", "party": r.party or "",
                      "detail": f"{float(r.litres or 0):g} L {r.src or ''}".strip(),
                      "amount": _r2(r.amount), "direction": "out"})

    # Salary / wages (deduction negative)
    for r in await _rows(
        "SELECT COALESCE(w.name,'') AS party, wp.payment_type AS mode, "
        "(CASE WHEN wp.payment_type='deduction' THEN -wp.amount ELSE wp.amount END) AS amount "
        "FROM worker_payments wp LEFT JOIN workers w ON w.id=wp.worker_id "
        "WHERE wp.company_id=:cid AND wp.payment_type IN ('wage','salary','bonus','deduction') "
        "AND wp.pay_date=:d"):
        items.append({"category": "Salary", "ref": "", "party": r.party or "",
                      "detail": r.mode or "", "amount": _r2(r.amount), "direction": "out"})

    # Advances
    for r in await _rows(
        "SELECT COALESCE(w.name,'') AS party, wp.amount AS amount "
        "FROM worker_payments wp LEFT JOIN workers w ON w.id=wp.worker_id "
        "WHERE wp.company_id=:cid AND wp.payment_type='advance' AND wp.pay_date=:d"):
        items.append({"category": "Advance", "ref": "", "party": r.party or "",
                      "detail": "advance", "amount": _r2(r.amount), "direction": "out"})

    # Agent commission
    for r in await _rows(
        "SELECT i.invoice_no AS ref, COALESCE(a.name,'') AS party, COALESCE(i.commission_amount,0) AS amount "
        "FROM invoices i LEFT JOIN agents a ON a.id=i.agent_id "
        "WHERE i.company_id=:cid AND i.invoice_type='sale' AND i.status='final' "
        "AND COALESCE(i.commission_amount,0)>0 AND i.invoice_date=:d"):
        items.append({"category": "Commission", "ref": r.ref or "", "party": r.party or "",
                      "detail": "", "amount": _r2(r.amount), "direction": "out"})

    # Overhead expenses (direct-expense vouchers)
    for r in await _rows(
        "SELECT v.voucher_no AS ref, COALESCE(p.name,'') AS party, v.expense_category AS cat, v.amount AS amount "
        "FROM payment_vouchers v LEFT JOIN parties p ON p.id=v.party_id "
        "WHERE v.company_id=:cid AND v.expense_category IS NOT NULL AND v.voucher_date=:d ORDER BY v.amount DESC"):
        items.append({"category": "Expense", "ref": r.ref or "", "party": r.party or "",
                      "detail": r.cat or "", "amount": _r2(r.amount), "direction": "out"})

    # Supplier payments (non-expense vouchers) — cash paid to suppliers
    for r in await _rows(
        "SELECT v.voucher_no AS ref, COALESCE(p.name,'') AS party, v.payment_mode AS mode, v.amount AS amount "
        "FROM payment_vouchers v LEFT JOIN parties p ON p.id=v.party_id "
        "WHERE v.company_id=:cid AND v.expense_category IS NULL AND v.voucher_date=:d ORDER BY v.amount DESC"):
        items.append({"category": "Supplier Payment", "ref": r.ref or "", "party": r.party or "",
                      "detail": (r.mode or "").upper(), "amount": _r2(r.amount), "direction": "out"})

    summ = await compute_eod_summary(db, company_id, target_date, target_date)
    return {"date": target_date.isoformat(), "items": items, "summary": summ["summary"]}


@router.get("/eod-summary")
async def eod_summary(
    from_date: date = Query(None),
    to_date: date = Query(None),
    basis: str = Query("accrual"),   # 'accrual' (default) | 'cash'
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """EOD Daily Business Summary — cash vs electronic sales + itemised expenses.
    Defaults to TODAY when no range is given (the daily EOD view); accepts a
    range for the report page + CSV. ``basis`` = 'accrual' (default) or 'cash'."""
    today = date.today()
    fd = from_date or today
    td = to_date or today
    if td < fd:
        fd, td = td, fd
    return await compute_eod_summary(db, current_user.company_id, fd, td, basis=basis)


@router.post("/eod-summary/send")
async def send_eod_summary(
    target_date: date = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fire the EOD day-book summary now (email + Telegram) to subscribed
    recipients — the same context the scheduled daily loop builds. Admin only."""
    if current_user.role != "admin":
        raise HTTPException(403, "Admin only")
    from app.models.company import Company
    from app.integrations.notifications.service import send_notification
    co = (await db.execute(
        select(Company).where(Company.id == current_user.company_id)
    )).scalar_one_or_none()
    if not co:
        raise HTTPException(404, "Company not found")
    d = target_date or date.today()
    ctx = await build_eod_summary_context(db, co.id, co.name, d)
    await send_notification(db, co.id, "eod_summary", ctx,
                            entity_type="company", entity_id=str(co.id))
    return {"ok": True, "date": d.isoformat()}


@router.get("/eod-summary/detail")
async def eod_summary_detail(
    on_date: date = Query(..., alias="date"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Drill-down: every individual transaction behind one Day-Book day, for the
    click-through breakup + Excel export."""
    return await compute_eod_detail(db, current_user.company_id, on_date)


@router.get("/operator-cash-eod")
async def operator_cash_eod(
    on_date: date = Query(None, alias="date"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """End-of-day cash-in-hand per operator: cash collected today (cash receipts
    they recorded) vs cash handed over + acknowledged, and the balance still to
    hand over. For handover / deposit to accounts and reconciliation."""
    d = on_date or date.today()
    cid = str(current_user.company_id)

    rows = (await db.execute(text(
        "SELECT r.created_by AS oid, COALESCE(u.full_name, u.username, 'Unknown') AS name, "
        "COUNT(*) AS receipts, SUM(r.amount) AS cash "
        "FROM payment_receipts r LEFT JOIN users u ON u.id = r.created_by "
        "WHERE r.company_id=:cid AND LOWER(COALESCE(r.payment_mode,''))='cash' "
        "AND r.receipt_date=:d GROUP BY r.created_by, u.full_name, u.username"
    ), {"cid": cid, "d": d})).all()
    collected = {(str(r.oid) if r.oid else "none"): {
        "name": r.name, "receipts": int(r.receipts or 0), "cash": _r2(r.cash)} for r in rows}

    handovers: dict[str, dict] = {}
    try:
        async with db.begin_nested():
            hrows = (await db.execute(text(
                "SELECT operator_id AS oid, MAX(operator_name) AS name, SUM(amount) AS amt "
                "FROM cash_handovers WHERE company_id=:cid AND handover_date=:d "
                "AND status='acknowledged' GROUP BY operator_id"
            ), {"cid": cid, "d": d})).all()
        for h in hrows:
            handovers[str(h.oid) if h.oid else "none"] = {"name": h.name, "amt": _r2(h.amt)}
    except Exception as e:  # noqa: BLE001 — table may not exist yet on a fresh tenant
        logger.warning("operator handover sum skipped: %s", str(e)[:120])

    operators = []
    for k in (set(collected) | set(handovers)):
        c = collected.get(k, {"name": None, "receipts": 0, "cash": 0.0})
        ho = handovers.get(k, {"name": None, "amt": 0.0})
        operators.append({
            "operator_id": None if k == "none" else k,
            "operator_name": c["name"] or ho["name"] or "Unknown",
            "receipts": c["receipts"],
            "cash_total": c["cash"],
            "handed_over": ho["amt"],
            "balance": _r2(c["cash"] - ho["amt"]),
        })
    operators.sort(key=lambda o: -o["cash_total"])
    return {
        "date": d.isoformat(),
        "operators": operators,
        "total_cash": _r2(sum(o["cash_total"] for o in operators)),
        "total_handed_over": _r2(sum(o["handed_over"] for o in operators)),
        "total_balance": _r2(sum(o["balance"] for o in operators)),
        "operator_count": len(operators),
    }


class CashHandoverIn(BaseModel):
    operator_id: Optional[str] = None
    operator_name: Optional[str] = None
    amount: float
    handover_date: Optional[date] = None
    notes: Optional[str] = None
    acknowledge: bool = False   # accountant/admin recording it = immediate acknowledgment


@router.post("/cash-handover", status_code=201)
async def create_cash_handover(
    payload: CashHandoverIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record an end-of-day cash handover from an operator to the accountant.
    When an accountant/admin records it (or acknowledge=True) it is stored as
    ACKNOWLEDGED (received_by = the accountant) — the acknowledgment audit trail;
    otherwise it is PENDING until an accountant acknowledges it."""
    if payload.amount is None or float(payload.amount) <= 0:
        raise HTTPException(400, "amount must be greater than zero")
    d = payload.handover_date or date.today()
    is_receiver = current_user.role in ("admin", "accountant", "store_manager")
    ack = payload.acknowledge or is_receiver
    hid = uuid.uuid4()
    uname = current_user.full_name or current_user.username
    await db.execute(text(
        "INSERT INTO cash_handovers (id, company_id, operator_id, operator_name, handover_date, "
        "amount, notes, status, received_by, received_by_name, acknowledged_at, created_by, created_at) "
        "VALUES (:id, :cid, :oid, :oname, :d, :amt, :notes, :status, :rby, :rname, :ackat, :cby, NOW())"
    ), {
        "id": hid, "cid": str(current_user.company_id),
        "oid": payload.operator_id, "oname": payload.operator_name,
        "d": d, "amt": payload.amount, "notes": payload.notes,
        "status": "acknowledged" if ack else "pending",
        "rby": str(current_user.id) if ack else None,
        "rname": uname if ack else None,
        "ackat": datetime.utcnow() if ack else None,
        "cby": str(current_user.id),
    })
    await db.commit()
    return {"id": str(hid), "status": "acknowledged" if ack else "pending", "date": d.isoformat()}


@router.post("/cash-handover/{handover_id}/acknowledge")
async def acknowledge_cash_handover(
    handover_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accountant/admin acknowledges receipt of a pending cash handover."""
    if current_user.role not in ("admin", "accountant", "store_manager"):
        raise HTTPException(403, "Only an accountant or admin can acknowledge a handover")
    res = await db.execute(text(
        "UPDATE cash_handovers SET status='acknowledged', received_by=:rby, "
        "received_by_name=:rname, acknowledged_at=NOW() "
        "WHERE id=:id AND company_id=:cid AND status<>'acknowledged'"
    ), {"rby": str(current_user.id), "rname": current_user.full_name or current_user.username,
        "id": handover_id, "cid": str(current_user.company_id)})
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "Handover not found or already acknowledged")
    return {"ok": True, "id": str(handover_id), "status": "acknowledged"}


@router.get("/cash-handover")
async def list_cash_handovers(
    on_date: date = Query(None, alias="date"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List cash handovers for a date (default today)."""
    d = on_date or date.today()
    rows = (await db.execute(text(
        "SELECT id, operator_name, amount, status, received_by_name, acknowledged_at, notes "
        "FROM cash_handovers WHERE company_id=:cid AND handover_date=:d ORDER BY created_at DESC"
    ), {"cid": str(current_user.company_id), "d": d})).all()
    return {"date": d.isoformat(), "handovers": [{
        "id": str(r.id), "operator_name": r.operator_name, "amount": _r2(r.amount),
        "status": r.status, "received_by_name": r.received_by_name,
        "acknowledged_at": r.acknowledged_at.isoformat() if r.acknowledged_at else None,
        "notes": r.notes,
    } for r in rows]}


# ── Stock Summary ────────────────────────────────────────────────────────────

@router.get("/stock-summary")
async def stock_summary(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Product-wise stock summary: purchases in vs sales out → closing stock."""
    # Qty & value purchased per product
    purch_result = await db.execute(
        select(
            Product.id, Product.name, Product.hsn_code, Product.unit, Product.default_rate,
            func.sum(InvoiceItem.quantity).label("qty"),
            func.sum(InvoiceItem.amount).label("value"),
        )
        .join(Product, InvoiceItem.product_id == Product.id)
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .where(Invoice.invoice_type == "purchase", Invoice.status == "final",
               Invoice.company_id == current_user.company_id,
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
        .group_by(Product.id, Product.name, Product.hsn_code, Product.unit, Product.default_rate)
    )

    # Qty & value sold per product
    sale_result = await db.execute(
        select(
            Product.id, Product.name, Product.hsn_code, Product.unit, Product.default_rate,
            func.sum(InvoiceItem.quantity).label("qty"),
            func.sum(InvoiceItem.amount).label("value"),
        )
        .join(Product, InvoiceItem.product_id == Product.id)
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .where(Invoice.invoice_type == "sale", Invoice.status == "final",
               Invoice.company_id == current_user.company_id,
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
        .group_by(Product.id, Product.name, Product.hsn_code, Product.unit, Product.default_rate)
    )

    purch_map: dict[str, dict] = {}
    for r in purch_result.all():
        purch_map[str(r.id)] = {
            "name": r.name, "hsn_code": r.hsn_code or "—", "unit": r.unit,
            "default_rate": _f(r.default_rate),
            "qty_purchased": _f(r.qty), "value_purchased": _r2(r.value),
        }

    sale_map: dict[str, dict] = {}
    for r in sale_result.all():
        sale_map[str(r.id)] = {
            "name": r.name, "hsn_code": r.hsn_code or "—", "unit": r.unit,
            "default_rate": _f(r.default_rate),
            "qty_sold": _f(r.qty), "value_sold": _r2(r.value),
        }

    all_ids = sorted(set(list(purch_map.keys()) + list(sale_map.keys())))
    items = []
    total_value_purchased = total_value_sold = total_closing_value = 0.0
    qty_purchased_by_unit: dict[str, float] = {}
    qty_sold_by_unit: dict[str, float] = {}
    for pid in all_ids:
        p = purch_map.get(pid, {})
        s = sale_map.get(pid, {})
        name = p.get("name") or s.get("name") or "Unknown"
        hsn = p.get("hsn_code") or s.get("hsn_code") or "—"
        unit = p.get("unit") or s.get("unit") or ""
        qty_in = p.get("qty_purchased", 0.0)
        val_in = p.get("value_purchased", 0.0)
        # Use weighted-average purchase cost when available; fall back to default_rate.
        wac = _r2(val_in / qty_in) if qty_in > 0 else (
            p.get("default_rate") or s.get("default_rate") or 0.0
        )
        qty_out = s.get("qty_sold", 0.0)
        closing_qty = _r2(qty_in - qty_out)
        closing_value = _r2(closing_qty * wac)
        u = unit or "—"
        qty_purchased_by_unit[u] = _r2(qty_purchased_by_unit.get(u, 0.0) + qty_in)
        qty_sold_by_unit[u] = _r2(qty_sold_by_unit.get(u, 0.0) + qty_out)
        total_value_purchased += val_in
        total_value_sold += s.get("value_sold", 0.0)
        total_closing_value += closing_value
        items.append({
            "product_name": name, "hsn_code": hsn, "unit": unit, "rate": wac,
            "qty_purchased": qty_in, "value_purchased": val_in,
            "qty_sold": qty_out, "value_sold": s.get("value_sold", 0.0),
            "closing_qty": closing_qty, "closing_value": closing_value,
        })

    # Sort by name
    items.sort(key=lambda x: x["product_name"])

    return {
        "period": f"{from_date.isoformat()} to {to_date.isoformat()}",
        "items": items,
        "totals": {
            # Quantities are summed PER UNIT — MT / CFT / bag are not addable
            # into a single scalar. Value (₹) is unit-agnostic and summable.
            "qty_purchased_by_unit": qty_purchased_by_unit,
            "qty_sold_by_unit": qty_sold_by_unit,
            "value_purchased": _r2(total_value_purchased),
            "value_sold": _r2(total_value_sold),
            "closing_value": _r2(total_closing_value),
        },
    }


# ── Write-off report ───────────────────────────────────────────────────────

@router.get("/write-offs")
async def write_off_report(
    from_date: date = Query(...),
    to_date: date = Query(...),
    party_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """All write-offs in the period, with per-row + per-customer + totals.

    Filter by date range (write_off_at) and optionally by party_id.
    """
    filters = [
        Invoice.invoice_type == "sale",      # write-offs are a bad-debt concept — exclude purchase invoices
        Invoice.write_off_amount > 0,
        Invoice.write_off_at.isnot(None),
        Invoice.company_id == current_user.company_id,
        func.date(Invoice.write_off_at) >= from_date,
        func.date(Invoice.write_off_at) <= to_date,
    ]
    if party_id:
        filters.append(Invoice.party_id == party_id)

    rows = (await db.execute(
        select(
            Invoice.id,
            Invoice.invoice_no,
            Invoice.invoice_date,
            Invoice.invoice_type,
            Invoice.party_id,
            Party.name.label("party_name"),
            Party.phone.label("party_phone"),
            Invoice.grand_total,
            Invoice.write_off_amount,
            Invoice.write_off_reason,
            Invoice.write_off_at,
            User.full_name.label("written_off_by_name"),
            User.username.label("written_off_by_username"),
        )
        .join(Party, Invoice.party_id == Party.id, isouter=True)
        .join(User, Invoice.write_off_by == User.id, isouter=True)
        .where(*filters)
        .order_by(Invoice.write_off_at.desc())
    )).all()

    items = []
    by_party: dict[str, dict] = {}
    total_amount = Decimal("0")
    for r in rows:
        amt = Decimal(str(r.write_off_amount or 0))
        total_amount += amt
        party_label = r.party_name or "Walk-in / Cash"
        items.append({
            "invoice_id": str(r.id),
            "invoice_no": r.invoice_no,
            "invoice_date": r.invoice_date.isoformat() if r.invoice_date else None,
            "invoice_type": r.invoice_type,
            "party_id": str(r.party_id) if r.party_id else None,
            "party_name": party_label,
            "party_phone": r.party_phone,
            "grand_total": float(r.grand_total or 0),
            "write_off_amount": float(amt),
            "write_off_reason": r.write_off_reason or "",
            "write_off_at": r.write_off_at.isoformat() if r.write_off_at else None,
            "written_off_by": r.written_off_by_name or r.written_off_by_username or "",
        })
        # Per-party aggregate
        key = str(r.party_id) if r.party_id else "_walkin_"
        if key not in by_party:
            by_party[key] = {
                "party_id": str(r.party_id) if r.party_id else None,
                "party_name": party_label,
                "party_phone": r.party_phone,
                "count": 0,
                "total_amount": 0.0,
            }
        by_party[key]["count"] += 1
        by_party[key]["total_amount"] = float(
            Decimal(str(by_party[key]["total_amount"])) + amt
        )

    by_party_list = sorted(
        by_party.values(), key=lambda x: x["total_amount"], reverse=True
    )

    return {
        "period": f"{from_date.isoformat()} to {to_date.isoformat()}",
        "items": items,
        "by_party": by_party_list,
        "totals": {
            "count": len(items),
            "amount": float(total_amount),
            "customer_count": len(by_party_list),
        },
    }


# ── GST split report (with vs without GST) ──────────────────────────────────

@router.get("/gst-split")
async def gst_split_report(
    from_date: date = Query(...),
    to_date: date = Query(...),
    invoice_type: Optional[str] = Query(None, description="'sale' or 'purchase' to filter"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Counts + totals of GST vs non-GST (Bill of Supply) invoices in a date range.

    Returns:
      - summary: { gst_count, non_gst_count, gst_amount, non_gst_amount, gst_tax_collected }
      - monthly: list of { month, label, gst_count, non_gst_count, gst_amount, non_gst_amount }
      - top_cash_customers: customers with the most non-GST invoices in the window
    """
    filters = [
        Invoice.status == "final",
        Invoice.company_id == current_user.company_id,
        Invoice.invoice_date >= from_date,
        Invoice.invoice_date <= to_date,
    ]
    if invoice_type:
        filters.append(Invoice.invoice_type == invoice_type)

    # Aggregate by tax_type
    summary_rows = (await db.execute(
        select(
            Invoice.tax_type,
            func.count(Invoice.id).label("cnt"),
            func.coalesce(func.sum(Invoice.grand_total), 0).label("total"),
            func.coalesce(func.sum(Invoice.cgst_amount + Invoice.sgst_amount + Invoice.igst_amount), 0).label("tax"),
        )
        .where(*filters)
        .group_by(Invoice.tax_type)
    )).all()

    gst_count = gst_amount = gst_tax = 0
    non_gst_count = non_gst_amount = 0
    for r in summary_rows:
        if r.tax_type == "gst":
            gst_count = int(r.cnt or 0)
            gst_amount = _r2(r.total)
            gst_tax = _r2(r.tax)
        else:
            non_gst_count = int(r.cnt or 0)
            non_gst_amount = _r2(r.total)

    # Monthly breakdown
    yr = func.extract("year", Invoice.invoice_date)
    mo = func.extract("month", Invoice.invoice_date)
    monthly_rows = (await db.execute(
        select(
            yr.label("yr"), mo.label("mo"),
            Invoice.tax_type,
            func.count(Invoice.id).label("cnt"),
            func.coalesce(func.sum(Invoice.grand_total), 0).label("total"),
        )
        .where(*filters)
        .group_by(yr, mo, Invoice.tax_type)
        .order_by(yr, mo)
    )).all()

    import calendar
    by_month: dict[str, dict] = {}
    for r in monthly_rows:
        key = f"{int(r.yr)}-{int(r.mo):02d}"
        if key not in by_month:
            by_month[key] = {
                "month": key,
                "label": f"{calendar.month_abbr[int(r.mo)]} {int(r.yr)}",
                "gst_count": 0, "non_gst_count": 0,
                "gst_amount": 0.0, "non_gst_amount": 0.0,
            }
        if r.tax_type == "gst":
            by_month[key]["gst_count"] = int(r.cnt or 0)
            by_month[key]["gst_amount"] = _r2(r.total)
        else:
            by_month[key]["non_gst_count"] = int(r.cnt or 0)
            by_month[key]["non_gst_amount"] = _r2(r.total)
    monthly = [by_month[k] for k in sorted(by_month.keys())]

    # Top cash (non-GST) customers
    top_cash_rows = (await db.execute(
        select(
            Invoice.party_id,
            Party.name.label("party_name"),
            func.count(Invoice.id).label("cnt"),
            func.coalesce(func.sum(Invoice.grand_total), 0).label("total"),
        )
        .join(Party, Invoice.party_id == Party.id, isouter=True)
        .where(*filters, Invoice.tax_type == "non_gst")
        .group_by(Invoice.party_id, Party.name)
        .order_by(func.sum(Invoice.grand_total).desc())
        .limit(10)
    )).all()
    top_cash_customers = [
        {
            "party_id": str(r.party_id) if r.party_id else None,
            "party_name": r.party_name or "Walk-in / Cash",
            "count": int(r.cnt or 0),
            "total_amount": _r2(r.total),
        }
        for r in top_cash_rows
    ]

    total_count = gst_count + non_gst_count
    total_amount = gst_amount + non_gst_amount
    return {
        "period": f"{from_date.isoformat()} to {to_date.isoformat()}",
        "summary": {
            "gst_count": gst_count,
            "non_gst_count": non_gst_count,
            "gst_amount": gst_amount,
            "non_gst_amount": non_gst_amount,
            "gst_tax_collected": gst_tax,
            "total_count": total_count,
            "total_amount": total_amount,
            "gst_share_pct": _r2(gst_amount / total_amount * 100) if total_amount > 0 else 0,
            "non_gst_share_pct": _r2(non_gst_amount / total_amount * 100) if total_amount > 0 else 0,
        },
        "monthly": monthly,
        "top_cash_customers": top_cash_customers,
    }


@router.get("/sales-by-status")
async def sales_by_status(
    from_date: date = Query(...),
    to_date: date = Query(...),
    granularity: str = Query("day"),   # day | week | month
    tax_type: str | None = Query(None),  # gst | non_gst | None (all)
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sales amount split by invoice status (Draft vs Final/'Complete') over a
    date range, bucketed by day/week/month for charting. Sale invoices only.
    Optional tax_type filter: 'gst' (INV series) or 'non_gst' (CINV series)."""
    if granularity not in ("day", "week", "month"):
        granularity = "day"
    if tax_type not in ("gst", "non_gst"):
        tax_type = None

    conditions = [
        Invoice.company_id == current_user.company_id,
        Invoice.invoice_type == "sale",
        Invoice.invoice_date >= from_date,
        Invoice.invoice_date <= to_date,
    ]
    if tax_type:
        conditions.append(Invoice.tax_type == tax_type)

    rows = (await db.execute(
        select(Invoice.invoice_date, Invoice.status, Invoice.grand_total).where(*conditions)
    )).all()

    def bucket(d: date):
        if granularity == "month":
            return d.replace(day=1).isoformat(), d.strftime("%b %Y")
        if granularity == "week":
            monday = d - timedelta(days=d.weekday())
            return monday.isoformat(), monday.strftime("%d %b")
        return d.isoformat(), d.strftime("%d %b")

    buckets: dict = {}
    totals = {"draft": Decimal("0"), "final": Decimal("0"), "cancelled": Decimal("0")}
    counts = {"draft": 0, "final": 0, "cancelled": 0}
    for inv_date, status, gt in rows:
        gt = gt or Decimal("0")
        bucket_status = status if status in ("draft", "final", "cancelled") else "draft"
        totals[bucket_status] += gt
        counts[bucket_status] += 1
        # cancelled excluded from the time-series (focus on draft vs final)
        if bucket_status == "cancelled":
            continue
        key, label = bucket(inv_date)
        b = buckets.setdefault(key, {"period": key, "label": label,
                                     "draft": Decimal("0"), "final": Decimal("0")})
        b[bucket_status] += gt

    series = [
        {"period": v["period"], "label": v["label"],
         "draft": _f(v["draft"]), "final": _f(v["final"]),
         "total": _f(v["draft"] + v["final"])}
        for _, v in sorted(buckets.items())
    ]

    return {
        "from_date": from_date.isoformat(), "to_date": to_date.isoformat(),
        "granularity": granularity,
        "summary": {
            "draft": {"count": counts["draft"], "amount": _f(totals["draft"])},
            "final": {"count": counts["final"], "amount": _f(totals["final"])},
            "cancelled": {"count": counts["cancelled"], "amount": _f(totals["cancelled"])},
            "total_count": counts["draft"] + counts["final"],
            "total_amount": _f(totals["draft"] + totals["final"]),
        },
        "series": series,
    }


# ── Gate Pass Register ────────────────────────────────────────────────────────

@router.get("/gate-pass-register")
async def gate_pass_register(
    from_date: date = Query(...),
    to_date: date = Query(...),
    status: Optional[str] = Query(None),        # inside | exited | cancelled
    purpose: Optional[str] = Query(None),        # weighbridge | delivery | …
    vehicle_no: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = [
        "gp.company_id = :company_id",
        "gp.pass_date >= :from_date",
        "gp.pass_date <= :to_date",
    ]
    params: dict = {
        "company_id": str(current_user.company_id),
        "from_date": from_date,
        "to_date": to_date,
    }
    if status:
        filters.append("gp.status = :status")
        params["status"] = status
    if purpose:
        filters.append("gp.purpose = :purpose")
        params["purpose"] = purpose
    if vehicle_no:
        filters.append("gp.vehicle_no ILIKE :vehicle_no")
        params["vehicle_no"] = f"%{vehicle_no}%"

    where = " AND ".join(filters)
    sql = text(f"""
        SELECT
            gp.id,
            gp.gate_pass_no,
            gp.pass_date,
            gp.vehicle_no,
            gp.vehicle_name,
            gp.vehicle_type,
            gp.driver_name,
            gp.driver_phone,
            gp.material,
            gp.purpose,
            gp.status,
            gp.entry_time,
            gp.exit_time,
            gp.notes,
            gp.entry_photo_path,
            gp.exit_photo_path,
            gp.token_id,
            t.token_no,
            t.net_weight,
            COALESCE(pr.name, tp.name) AS product_name,
            u.username AS created_by_name,
            inv.id   AS invoice_id,
            inv.invoice_no
        FROM gate_passes gp
        LEFT JOIN tokens t       ON t.id  = gp.token_id
        LEFT JOIN products pr    ON pr.id = gp.product_id
        LEFT JOIN products tp    ON tp.id = t.product_id
        LEFT JOIN users u        ON u.id  = gp.created_by
        LEFT JOIN LATERAL (
            SELECT id, invoice_no FROM invoices
            WHERE token_id     = gp.token_id
              AND invoice_type = 'sale'
              AND status       = 'final'
              AND company_id   = gp.company_id
            ORDER BY revision_no DESC
            LIMIT 1
        ) inv ON gp.token_id IS NOT NULL
        WHERE {where}
        ORDER BY gp.pass_date DESC, gp.entry_time DESC
    """)

    result = await db.execute(sql, params)
    rows = result.mappings().all()

    items = []
    for r in rows:
        entry = r["entry_time"]
        exit_ = r["exit_time"]
        dwell_minutes = None
        if entry and exit_:
            dwell_minutes = round((exit_ - entry).total_seconds() / 60, 1)

        items.append({
            "id": str(r["id"]),
            "gate_pass_no": r["gate_pass_no"],
            "pass_date": r["pass_date"].isoformat() if r["pass_date"] else None,
            "vehicle_no": r["vehicle_no"],
            "vehicle_name": r["vehicle_name"],
            "vehicle_type": r["vehicle_type"],
            "driver_name": r["driver_name"],
            "driver_phone": r["driver_phone"],
            "material": r["material"] or r["product_name"],
            "purpose": r["purpose"],
            "status": r["status"],
            "entry_time": entry.isoformat() if entry else None,
            "exit_time": exit_.isoformat() if exit_ else None,
            "dwell_minutes": dwell_minutes,
            "token_no": r["token_no"],
            "token_id": str(r["token_id"]) if r["token_id"] else None,
            "net_weight_mt": _r2(r["net_weight"] / 1000) if r["net_weight"] else None,
            "entry_photo_path": r["entry_photo_path"],
            "exit_photo_path": r["exit_photo_path"],
            "notes": r["notes"],
            "created_by": r["created_by_name"],
            "invoice_id": str(r["invoice_id"]) if r["invoice_id"] else None,
            "invoice_no": r["invoice_no"],
        })

    return {
        "items": items,
        "count": len(items),
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "total_vehicles": len({r["vehicle_no"] for r in rows if r["vehicle_no"]}),
        "total_exited": sum(1 for i in items if i["status"] == "exited"),
        "total_inside": sum(1 for i in items if i["status"] == "inside"),
    }


# ── Token Register (all statuses) ────────────────────────────────────────────

@router.get("/token-register")
async def token_register(
    from_date: date = Query(...),
    to_date: date = Query(...),
    token_type: Optional[str] = Query(None),     # sale | purchase | general
    status: Optional[str] = Query(None),          # OPEN|COMPLETED|CANCELLED|…
    party_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = (
        select(Token, Party, Product, Invoice)
        .outerjoin(Party, Token.party_id == Party.id)
        .outerjoin(Product, Token.product_id == Product.id)
        # left join most-recent non-cancelled invoice for this token
        .outerjoin(
            Invoice,
            and_(
                Invoice.token_id == Token.id,
                Invoice.status != "cancelled",
                Invoice.invoice_type == "sale",
            ),
        )
        .where(
            Token.company_id == current_user.company_id,
            Token.token_date >= from_date,
            Token.token_date <= to_date,
            Token.is_supplement.is_(False),
        )
        .order_by(Token.token_date.desc(), Token.created_at.desc())
    )
    if token_type:
        q = q.where(Token.token_type == token_type)
    if status:
        q = q.where(Token.status == status)
    if party_id:
        q = q.where(Token.party_id == party_id)

    result = await db.execute(q)
    rows = result.all()

    items = []
    total_net = Decimal(0)
    seen_token_ids: set = set()          # deduplicate when multiple invoices match
    for token, party, product, invoice in rows:
        tid = str(token.id)
        if tid in seen_token_ids:
            continue
        seen_token_ids.add(tid)

        if token.net_weight:
            total_net += token.net_weight

        items.append({
            "id": tid,
            "token_no": token.token_no,
            "token_date": token.token_date.isoformat(),
            "created_at": token.created_at.isoformat() if token.created_at else None,
            "token_type": token.token_type,
            "status": token.status,
            "source": getattr(token, "source", "manual"),
            "vehicle_no": token.vehicle_no,
            "vehicle_type": getattr(token, "vehicle_type", None),
            "party_name": party.name if party else None,
            "product_name": product.name if product else None,
            "weight_method": token.weight_method,
            "gross_weight_mt": _r2(token.gross_weight / 1000) if token.gross_weight else None,
            "tare_weight_mt": _r2(token.tare_weight / 1000) if token.tare_weight else None,
            "net_weight_mt": _r2(token.net_weight / 1000) if token.net_weight else None,
            "volume_cft": _f(getattr(token, "volume_cft", None)),
            "gate_pass_no": getattr(token, "gate_pass_no", None),
            "invoice_no": invoice.invoice_no if invoice else None,
            "invoice_status": invoice.status if invoice else None,
            "grand_total": _r2(invoice.grand_total) if invoice else None,
            "is_manual_weight": token.is_manual_weight,
        })

    return {
        "items": items,
        "count": len(items),
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "total_net_weight_mt": _r2(total_net / 1000),
        "completed_count": sum(1 for i in items if i["status"] == "COMPLETED"),
        "cancelled_count": sum(1 for i in items if i["status"] == "CANCELLED"),
    }

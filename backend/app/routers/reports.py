"""
Reports router — sales register, weight register, GSTR-1 summary + JSON export,
GSTR-3B, Profit & Loss, Stock Summary.
"""
import io
import json
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.database import get_db
from app.dependencies import get_current_user
from app.models.company import Company
from app.models.invoice import Invoice, InvoiceItem
from app.models.token import Token
from app.models.party import Party
from app.models.product import Product
from app.models.user import User

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])


# ── helpers ─────────────────────────────────────────────────────────────────

def _f(v) -> float:
    return float(v or 0)

def _r2(v) -> float:
    return round(float(v or 0), 2)


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
        .where(Token.token_date >= from_date, Token.token_date <= to_date, Token.status == "COMPLETED")
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

    return {
        "b2b": b2b, "b2b_totals": {k: _f(v) for k, v in b2b_totals.items()},
        "b2c": b2c, "b2c_totals": {k: _f(v) for k, v in b2c_totals.items()},
        "hsn_summary": hsn_summary,
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
        total_turnover += inv.grand_total
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
            "val": _r2(inv.grand_total),
            "pos": party.billing_state_code or company_state_code if hasattr(party, "billing_state_code") else company_state_code,
            "rchrg": "N",
            "inv_typ": "R",
            "itms": itms,
        }

        if party.gstin:
            b2b_map.setdefault(party.gstin, []).append(inv_entry)
        else:
            # B2CS — aggregate by rate + state
            for item in inv_items:
                rate = float(item.gst_rate or 0)
                pos = company_state_code
                supply_type = "INTRA" if inv.igst_amount == 0 else "INTER"
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
                supply_type = "INTRA" if _f(inv.igst_amount) == 0 else "INTER"
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

    payload = {
        "gstin": company_gstin,
        "fp": fp,
        "gt": _r2(total_turnover),
        "cur_gt": _r2(total_turnover),
        "b2b": [{"ctin": gstin, "inv": invs} for gstin, invs in b2b_map.items()],
        "b2cs": list(b2cs_map.values()),
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
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
    )
    purch_row = purchase_result.one()

    outward_cgst = _r2(sale_row.cgst)
    outward_sgst = _r2(sale_row.sgst)
    outward_igst = _r2(sale_row.igst)
    outward_tax = outward_cgst + outward_sgst + outward_igst

    itc_cgst = _r2(purch_row.cgst)
    itc_sgst = _r2(purch_row.sgst)
    itc_igst = _r2(purch_row.igst)
    itc_total = itc_cgst + itc_sgst + itc_igst

    net_cgst = _r2(outward_cgst - itc_cgst)
    net_sgst = _r2(outward_sgst - itc_sgst)
    net_igst = _r2(outward_igst - itc_igst)

    return {
        "gstin": company_gstin,
        "period": f"{from_date.strftime('%b %Y')} – {to_date.strftime('%b %Y')}",
        "section_3_1": {
            "a_taxable_outward": {
                "description": "Outward taxable supplies (other than zero rated, nil and exempted)",
                "invoice_count": int(sale_row.count or 0),
                "taxable_value": _r2(sale_row.taxable),
                "igst": outward_igst,
                "cgst": outward_cgst,
                "sgst": outward_sgst,
                "cess": 0.0,
                "total_tax": outward_tax,
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
                    "description": "All other ITC — purchases from GST-registered suppliers",
                    "invoice_count": int(purch_row.count or 0),
                    "taxable_value": _r2(purch_row.taxable),
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Basic P&L: Revenue (sales) vs COGS (purchases) by month."""
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
               Invoice.invoice_date >= from_date, Invoice.invoice_date <= to_date)
        .group_by(yr, mo)
        .order_by(yr, mo)
    )

    import calendar

    def _month_label(yr_val, mo_val) -> tuple[str, str]:
        y, m = int(yr_val), int(mo_val)
        return f"{y}-{m:02d}", f"{calendar.month_abbr[m]} {y}"

    rev_by_month: dict[str, dict] = {}
    for r in rev_result.all():
        key, label = _month_label(r.yr, r.mo)
        rev_by_month[key] = {"month": key, "label": label, "revenue": _r2(r.total), "revenue_taxable": _r2(r.taxable), "sale_count": int(r.count)}

    cogs_by_month: dict[str, dict] = {}
    for r in cogs_result.all():
        key, label = _month_label(r.yr, r.mo)
        cogs_by_month[key] = {"month": key, "label": label, "cogs": _r2(r.total), "cogs_taxable": _r2(r.taxable), "purchase_count": int(r.count)}

    # Merge by month
    all_months = sorted(set(list(rev_by_month.keys()) + list(cogs_by_month.keys())))
    monthly = []
    total_revenue = total_cogs = 0.0
    for key in all_months:
        rev = rev_by_month.get(key, {})
        cogs = cogs_by_month.get(key, {})
        label = rev.get("label") or cogs.get("label") or key
        revenue = rev.get("revenue", 0.0)
        cost = cogs.get("cogs", 0.0)
        profit = _r2(revenue - cost)
        margin = _r2((profit / revenue * 100) if revenue > 0 else 0)
        total_revenue += revenue
        total_cogs += cost
        monthly.append({
            "month": key, "label": label,
            "revenue": revenue, "cogs": cost,
            "gross_profit": profit, "margin_pct": margin,
            "sale_count": rev.get("sale_count", 0),
            "purchase_count": cogs.get("purchase_count", 0),
        })

    total_profit = _r2(total_revenue - total_cogs)
    return {
        "period": f"{from_date.isoformat()} to {to_date.isoformat()}",
        "summary": {
            "total_revenue": _r2(total_revenue),
            "total_cogs": _r2(total_cogs),
            "gross_profit": total_profit,
            "margin_pct": _r2((total_profit / total_revenue * 100) if total_revenue > 0 else 0),
        },
        "monthly": monthly,
    }


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
    total_purchased = total_sold = total_closing_value = 0.0
    for pid in all_ids:
        p = purch_map.get(pid, {})
        s = sale_map.get(pid, {})
        name = p.get("name") or s.get("name") or "Unknown"
        hsn = p.get("hsn_code") or s.get("hsn_code") or "—"
        unit = p.get("unit") or s.get("unit") or ""
        rate = p.get("default_rate") or s.get("default_rate") or 0.0
        qty_in = p.get("qty_purchased", 0.0)
        qty_out = s.get("qty_sold", 0.0)
        closing_qty = _r2(qty_in - qty_out)
        closing_value = _r2(closing_qty * rate)
        total_purchased += qty_in
        total_sold += qty_out
        total_closing_value += closing_value
        items.append({
            "product_name": name, "hsn_code": hsn, "unit": unit, "rate": rate,
            "qty_purchased": qty_in, "value_purchased": p.get("value_purchased", 0.0),
            "qty_sold": qty_out, "value_sold": s.get("value_sold", 0.0),
            "closing_qty": closing_qty, "closing_value": closing_value,
        })

    # Sort by name
    items.sort(key=lambda x: x["product_name"])

    return {
        "period": f"{from_date.isoformat()} to {to_date.isoformat()}",
        "items": items,
        "totals": {
            "qty_purchased": _r2(total_purchased),
            "qty_sold": _r2(total_sold),
            "closing_value": _r2(total_closing_value),
        },
    }

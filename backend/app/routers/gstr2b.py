"""GSTR-2B ITC reconciliation (Horizon 3).

Stateless: the accountant downloads the GSTR-2B JSON from the GST portal and
uploads it here. We parse the B2B inward supplies and match them against the
company's finalised PURCHASE invoices (by supplier GSTIN + invoice number),
classifying each as matched / value-mismatch / in-2B-not-books / in-books-not-2B,
and summarising ITC available vs at-risk. No data is written.
"""
import json
import re
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.invoice import Invoice
from app.models.party import Party
from app.models.user import User

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])


def _norm_inv(s) -> str:
    return re.sub(r"[\s\-/]", "", str(s or "")).upper()


def _f(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _parse_2b(payload: dict) -> list[dict]:
    """Extract B2B inward invoices from a GSTR-2B JSON (tolerant of layout).

    Returns rows: {gstin, supplier, inv_no, inv_date, taxable, igst, cgst, sgst}.
    """
    # The B2B block lives at data.docdata.b2b in the portal export; some tools
    # flatten it to docdata.b2b or b2b directly. Probe the common shapes.
    root = payload.get("data", payload)
    docdata = root.get("docdata", root)
    b2b = docdata.get("b2b") or root.get("b2b") or []

    rows: list[dict] = []
    for supplier in b2b:
        gstin = (supplier.get("ctin") or supplier.get("gstin") or "").strip().upper()
        name = supplier.get("trdnm") or supplier.get("name") or ""
        for inv in (supplier.get("inv") or supplier.get("invoices") or []):
            txval = igst = cgst = sgst = 0.0
            items = inv.get("items") or inv.get("itms") or []
            if items:
                for it in items:
                    d = it.get("itm_det", it)
                    txval += _f(d.get("txval"))
                    igst += _f(d.get("iamt") or d.get("igst"))
                    cgst += _f(d.get("camt") or d.get("cgst"))
                    sgst += _f(d.get("samt") or d.get("sgst"))
            else:
                txval = _f(inv.get("txval"))
                igst = _f(inv.get("iamt") or inv.get("igst"))
                cgst = _f(inv.get("camt") or inv.get("cgst"))
                sgst = _f(inv.get("samt") or inv.get("sgst"))
            rows.append({
                "gstin": gstin, "supplier": name,
                "inv_no": str(inv.get("inum") or inv.get("inv_no") or ""),
                "inv_date": inv.get("dt") or inv.get("inv_date") or "",
                "taxable": round(txval, 2),
                "igst": round(igst, 2), "cgst": round(cgst, 2), "sgst": round(sgst, 2),
                "total_tax": round(igst + cgst + sgst, 2),
            })
    return rows


@router.post("/gstr2b-reconcile")
async def gstr2b_reconcile(
    file: UploadFile = File(...),
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        payload = json.loads((await file.read()).decode("utf-8-sig"))
    except Exception:
        raise HTTPException(400, "Could not parse the uploaded file — it must be a GSTR-2B JSON export.")

    twob = _parse_2b(payload)
    if not twob:
        raise HTTPException(400, "No B2B inward invoices found in the JSON (expected data.docdata.b2b).")

    # Books: finalised purchase invoices with a supplier GSTIN
    stmt = select(Invoice, Party).join(Party, Invoice.party_id == Party.id).where(
        Invoice.company_id == current_user.company_id,
        Invoice.invoice_type == "purchase",
        Invoice.status == "final",
    )
    if date_from:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    book_rows = (await db.execute(stmt)).all()

    # Index books by (gstin, normalized invoice no)
    book_index: dict[tuple, dict] = {}
    used: set[tuple] = set()
    for inv, party in book_rows:
        g = (party.gstin or "").strip().upper()
        if not g or not inv.invoice_no:
            continue
        book_index[(g, _norm_inv(inv.invoice_no))] = {
            "gstin": g, "supplier": party.name,
            "inv_no": inv.invoice_no,
            "inv_date": inv.invoice_date.isoformat() if inv.invoice_date else "",
            "taxable": _f(inv.taxable_amount),
            "igst": _f(inv.igst_amount), "cgst": _f(inv.cgst_amount), "sgst": _f(inv.sgst_amount),
            "total_tax": _f((inv.igst_amount or 0) + (inv.cgst_amount or 0) + (inv.sgst_amount or 0)),
        }

    matched, value_mismatch, in_2b_not_books = [], [], []
    TOL = 1.0  # ₹ tolerance
    for r in twob:
        key = (r["gstin"], _norm_inv(r["inv_no"]))
        bk = book_index.get(key)
        if bk:
            used.add(key)
            if abs(bk["total_tax"] - r["total_tax"]) <= TOL and abs(bk["taxable"] - r["taxable"]) <= TOL:
                matched.append({**r, "book_tax": bk["total_tax"], "book_taxable": bk["taxable"]})
            else:
                value_mismatch.append({
                    **r, "book_taxable": bk["taxable"], "book_tax": bk["total_tax"],
                    "diff_tax": round(bk["total_tax"] - r["total_tax"], 2),
                })
        else:
            in_2b_not_books.append(r)   # supplier reported it; we haven't booked it

    in_books_not_2b = [v for k, v in book_index.items() if k not in used]

    def _sum(rows, field="total_tax"):
        return round(sum(x.get(field, 0) for x in rows), 2)

    return {
        "period": {"from": date_from.isoformat() if date_from else None,
                   "to": date_to.isoformat() if date_to else None},
        "summary": {
            "twob_count": len(twob),
            "twob_taxable": _sum(twob, "taxable"),
            "twob_igst": _sum(twob, "igst"), "twob_cgst": _sum(twob, "cgst"), "twob_sgst": _sum(twob, "sgst"),
            "twob_total_tax": _sum(twob),
            "books_count": len(book_index),
            "matched_count": len(matched), "matched_tax": _sum(matched),
            "value_mismatch_count": len(value_mismatch),
            "in_2b_not_books_count": len(in_2b_not_books),
            "in_2b_not_books_tax": _sum(in_2b_not_books),   # ITC available, not yet booked
            "in_books_not_2b_count": len(in_books_not_2b),
            "in_books_not_2b_tax": _sum(in_books_not_2b),    # ITC at risk (supplier hasn't filed)
        },
        "matched": matched,
        "value_mismatch": value_mismatch,
        "in_2b_not_books": in_2b_not_books,
        "in_books_not_2b": in_books_not_2b,
    }

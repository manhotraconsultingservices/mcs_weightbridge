"""
Payments router — receipts, vouchers, party ledger, outstanding.
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.database import get_db
from app.dependencies import get_current_user
from app.models.payment import PaymentReceipt, PaymentVoucher, InvoicePayment
from app.models.invoice import Invoice
from app.models.party import Party
from app.models.company import Company, FinancialYear
from app.models.settings import NumberSequence
from app.models.user import User
from app.schemas.payment import (
    PaymentReceiptCreate, PaymentReceiptResponse, PaymentReceiptListResponse,
    PaymentVoucherCreate, PaymentVoucherResponse, PaymentVoucherListResponse,
    LedgerEntrySchema, PartyLedgerResponse,
    OutstandingInvoice, OutstandingResponse,
)

router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])


async def _get_company_fy(db: AsyncSession):
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not co:
        raise HTTPException(500, "Company not configured")
    fy = (await db.execute(
        select(FinancialYear).where(FinancialYear.is_active == True).limit(1)
    )).scalar_one_or_none()
    if not fy:
        raise HTTPException(500, "No active financial year")
    return co, fy


async def _next_seq(db, company_id, fy_id, seq_type, prefix, fy_label) -> str:
    result = await db.execute(
        select(NumberSequence)
        .where(NumberSequence.company_id == company_id,
               NumberSequence.fy_id == fy_id,
               NumberSequence.sequence_type == seq_type)
        .with_for_update()
    )
    seq = result.scalar_one_or_none()
    if not seq:
        seq = NumberSequence(company_id=company_id, fy_id=fy_id,
                             sequence_type=seq_type, prefix=prefix,
                             last_number=0, reset_daily=False)
        db.add(seq)
    seq.last_number += 1
    await db.flush()
    short_fy = fy_label[-5:] if fy_label else "25-26"
    return f"{prefix}/{short_fy}/{seq.last_number:04d}"


def _settle_invoice(inv: Invoice, amount: Decimal):
    inv.amount_paid = (inv.amount_paid or Decimal("0")) + amount
    if inv.amount_paid >= inv.grand_total:
        inv.payment_status = "paid"
        inv.amount_due = Decimal("0")
    elif inv.amount_paid > 0:
        inv.payment_status = "partial"
        inv.amount_due = inv.grand_total - inv.amount_paid
    else:
        inv.payment_status = "unpaid"
        inv.amount_due = inv.grand_total


# ── Receipts ─────────────────────────────────────────────────────────────── #

@router.post("/receipts", response_model=PaymentReceiptResponse, status_code=201)
async def create_receipt(
    payload: PaymentReceiptCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co, fy = await _get_company_fy(db)
    party = (await db.execute(select(Party).where(Party.id == payload.party_id))).scalar_one_or_none()
    if not party:
        raise HTTPException(404, "Party not found")

    receipt_no = await _next_seq(db, co.id, fy.id, "receipt", "REC", fy.label)
    rec = PaymentReceipt(
        company_id=co.id, fy_id=fy.id,
        receipt_no=receipt_no,
        receipt_date=payload.receipt_date,
        party_id=payload.party_id,
        amount=payload.amount,
        payment_mode=payload.payment_mode,
        reference_no=payload.reference_no,
        bank_name=payload.bank_name,
        notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(rec)
    await db.flush()

    for alloc in payload.allocations:
        inv = (await db.execute(select(Invoice).where(Invoice.id == alloc.invoice_id))).scalar_one_or_none()
        if inv:
            db.add(InvoicePayment(invoice_id=inv.id, receipt_id=rec.id, amount=alloc.amount))
            _settle_invoice(inv, alloc.amount)

    await db.commit()
    await db.refresh(rec)

    # ── Fire payment_received notification (background, non-blocking) ─────────
    _notify_ctx = {
        "receipt_no": receipt_no,
        "receipt_date": payload.receipt_date.strftime("%d-%m-%Y") if hasattr(payload.receipt_date, "strftime") else str(payload.receipt_date),
        "amount": f"{float(payload.amount):,.2f}",
        "party_name": party.name,
        "party_email": party.email or "",
        "party_phone": party.phone or "",
        "company_name": co.name,
    }
    _bg_tenant = None
    try:
        from app.multitenancy.context import current_tenant_slug
        _bg_tenant = current_tenant_slug.get()
    except Exception:
        pass
    background_tasks.add_task(
        _send_notification_bg,
        co.id, "payment_received", _notify_ctx, "receipt", str(rec.id), _bg_tenant,
    )

    return PaymentReceiptResponse(
        id=rec.id, receipt_no=rec.receipt_no, receipt_date=rec.receipt_date,
        party_id=rec.party_id, party_name=party.name,
        amount=rec.amount, payment_mode=rec.payment_mode,
        reference_no=rec.reference_no, bank_name=rec.bank_name,
        notes=rec.notes, tally_synced=rec.tally_synced, created_at=rec.created_at,
    )


async def _send_notification_bg(
    company_id: uuid.UUID,
    event_type: str,
    context: dict,
    entity_type: str | None = None,
    entity_id: str | None = None,
    tenant_slug: str | None = None,
) -> None:
    """Background-task wrapper: opens its own DB session and fires a notification."""
    import logging as _logging
    try:
        from app.database import get_tenant_session
        from app.integrations.notifications.service import send_notification
        async with await get_tenant_session(tenant_slug) as db:
            await send_notification(db, company_id, event_type, context, entity_type, entity_id)
    except Exception as exc:
        _logging.getLogger(__name__).warning("Background notification failed [%s]: %s", event_type, exc)


@router.get("/receipts", response_model=PaymentReceiptListResponse)
async def list_receipts(
    party_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co, _ = await _get_company_fy(db)
    filters = [PaymentReceipt.company_id == co.id]
    if party_id:
        filters.append(PaymentReceipt.party_id == party_id)

    total = (await db.execute(
        select(func.count()).select_from(PaymentReceipt).where(and_(*filters))
    )).scalar()

    rows = (await db.execute(
        select(PaymentReceipt, Party.name.label("party_name"))
        .join(Party, PaymentReceipt.party_id == Party.id)
        .where(and_(*filters))
        .order_by(PaymentReceipt.receipt_date.desc(), PaymentReceipt.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).all()

    items = [
        PaymentReceiptResponse(
            id=r.PaymentReceipt.id, receipt_no=r.PaymentReceipt.receipt_no,
            receipt_date=r.PaymentReceipt.receipt_date, party_id=r.PaymentReceipt.party_id,
            party_name=r.party_name, amount=r.PaymentReceipt.amount,
            payment_mode=r.PaymentReceipt.payment_mode, reference_no=r.PaymentReceipt.reference_no,
            bank_name=r.PaymentReceipt.bank_name, notes=r.PaymentReceipt.notes,
            tally_synced=r.PaymentReceipt.tally_synced, created_at=r.PaymentReceipt.created_at,
        )
        for r in rows
    ]
    return PaymentReceiptListResponse(items=items, total=total, page=page, page_size=page_size)


# ── Vouchers ─────────────────────────────────────────────────────────────── #

@router.post("/vouchers", response_model=PaymentVoucherResponse, status_code=201)
async def create_voucher(
    payload: PaymentVoucherCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co, fy = await _get_company_fy(db)
    party = (await db.execute(select(Party).where(Party.id == payload.party_id))).scalar_one_or_none()
    if not party:
        raise HTTPException(404, "Party not found")

    voucher_no = await _next_seq(db, co.id, fy.id, "voucher", "PMT", fy.label)
    vch = PaymentVoucher(
        company_id=co.id, fy_id=fy.id,
        voucher_no=voucher_no,
        voucher_date=payload.voucher_date,
        party_id=payload.party_id,
        amount=payload.amount,
        payment_mode=payload.payment_mode,
        reference_no=payload.reference_no,
        bank_name=payload.bank_name,
        notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(vch)
    await db.flush()

    for alloc in payload.allocations:
        inv = (await db.execute(select(Invoice).where(Invoice.id == alloc.invoice_id))).scalar_one_or_none()
        if inv:
            db.add(InvoicePayment(invoice_id=inv.id, voucher_id=vch.id, amount=alloc.amount))
            _settle_invoice(inv, alloc.amount)

    await db.commit()
    await db.refresh(vch)
    return PaymentVoucherResponse(
        id=vch.id, voucher_no=vch.voucher_no, voucher_date=vch.voucher_date,
        party_id=vch.party_id, party_name=party.name,
        amount=vch.amount, payment_mode=vch.payment_mode,
        reference_no=vch.reference_no, bank_name=vch.bank_name,
        notes=vch.notes, tally_synced=vch.tally_synced, created_at=vch.created_at,
    )


@router.get("/vouchers", response_model=PaymentVoucherListResponse)
async def list_vouchers(
    party_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co, _ = await _get_company_fy(db)
    filters = [PaymentVoucher.company_id == co.id]
    if party_id:
        filters.append(PaymentVoucher.party_id == party_id)

    total = (await db.execute(
        select(func.count()).select_from(PaymentVoucher).where(and_(*filters))
    )).scalar()

    rows = (await db.execute(
        select(PaymentVoucher, Party.name.label("party_name"))
        .join(Party, PaymentVoucher.party_id == Party.id)
        .where(and_(*filters))
        .order_by(PaymentVoucher.voucher_date.desc(), PaymentVoucher.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).all()

    items = [
        PaymentVoucherResponse(
            id=r.PaymentVoucher.id, voucher_no=r.PaymentVoucher.voucher_no,
            voucher_date=r.PaymentVoucher.voucher_date, party_id=r.PaymentVoucher.party_id,
            party_name=r.party_name, amount=r.PaymentVoucher.amount,
            payment_mode=r.PaymentVoucher.payment_mode, reference_no=r.PaymentVoucher.reference_no,
            bank_name=r.PaymentVoucher.bank_name, notes=r.PaymentVoucher.notes,
            tally_synced=r.PaymentVoucher.tally_synced, created_at=r.PaymentVoucher.created_at,
        )
        for r in rows
    ]
    return PaymentVoucherListResponse(items=items, total=total, page=page, page_size=page_size)


# ── Party Ledger ─────────────────────────────────────────────────────────── #

@router.get("/party-ledger/{party_id}", response_model=PartyLedgerResponse)
async def party_ledger(
    party_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co, fy = await _get_company_fy(db)
    party = (await db.execute(select(Party).where(Party.id == party_id))).scalar_one_or_none()
    if not party:
        raise HTTPException(404, "Party not found")

    d_from = from_date or fy.start_date
    d_to = to_date or date.today()

    invoices = (await db.execute(
        select(Invoice)
        .where(Invoice.company_id == co.id, Invoice.party_id == party_id,
               Invoice.status != "cancelled",
               Invoice.invoice_date >= d_from, Invoice.invoice_date <= d_to)
        .order_by(Invoice.invoice_date, Invoice.created_at)
    )).scalars().all()

    receipts = (await db.execute(
        select(PaymentReceipt)
        .where(PaymentReceipt.company_id == co.id, PaymentReceipt.party_id == party_id,
               PaymentReceipt.receipt_date >= d_from, PaymentReceipt.receipt_date <= d_to)
        .order_by(PaymentReceipt.receipt_date, PaymentReceipt.created_at)
    )).scalars().all()

    vouchers = (await db.execute(
        select(PaymentVoucher)
        .where(PaymentVoucher.company_id == co.id, PaymentVoucher.party_id == party_id,
               PaymentVoucher.voucher_date >= d_from, PaymentVoucher.voucher_date <= d_to)
        .order_by(PaymentVoucher.voucher_date, PaymentVoucher.created_at)
    )).scalars().all()

    raw = []
    for inv in invoices:
        gt = inv.grand_total or Decimal("0")
        dr = gt if inv.invoice_type == "sale" else Decimal("0")
        cr = gt if inv.invoice_type == "purchase" else Decimal("0")
        raw.append({"date": inv.invoice_date, "type": f"{inv.invoice_type}_invoice",
                    "no": inv.invoice_no,
                    "narration": f"{inv.invoice_type.title()} Invoice",
                    "debit": dr, "credit": cr, "ts": inv.created_at})
    for rec in receipts:
        raw.append({"date": rec.receipt_date, "type": "receipt", "no": rec.receipt_no,
                    "narration": f"Payment received ({rec.payment_mode})",
                    "debit": Decimal("0"), "credit": rec.amount, "ts": rec.created_at})
    for vch in vouchers:
        raw.append({"date": vch.voucher_date, "type": "voucher", "no": vch.voucher_no,
                    "narration": f"Payment made ({vch.payment_mode})",
                    "debit": vch.amount, "credit": Decimal("0"), "ts": vch.created_at})

    raw.sort(key=lambda e: (e["date"], e["ts"]))

    opening = party.opening_balance or Decimal("0")
    balance = opening
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    entries = []
    for e in raw:
        balance = balance + e["debit"] - e["credit"]
        total_debit += e["debit"]
        total_credit += e["credit"]
        entries.append(LedgerEntrySchema(
            entry_date=e["date"], voucher_type=e["type"], voucher_no=e["no"],
            narration=e["narration"], debit=e["debit"], credit=e["credit"], balance=balance,
        ))

    return PartyLedgerResponse(
        party_id=party.id, party_name=party.name,
        opening_balance=opening, entries=entries,
        closing_balance=balance, total_debit=total_debit, total_credit=total_credit,
    )


# ── Outstanding ───────────────────────────────────────────────────────────── #

@router.get("/outstanding", response_model=OutstandingResponse)
async def outstanding(
    invoice_type: str | None = None,
    party_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co, _ = await _get_company_fy(db)
    filters = [Invoice.company_id == co.id, Invoice.status == "final",
               Invoice.payment_status != "paid"]
    if invoice_type:
        filters.append(Invoice.invoice_type == invoice_type)
    if party_id:
        filters.append(Invoice.party_id == party_id)

    rows = (await db.execute(
        select(Invoice, Party.name.label("party_name"))
        .join(Party, Invoice.party_id == Party.id)
        .where(and_(*filters))
        .order_by(Invoice.invoice_date)
    )).all()

    today = date.today()
    items = []
    total_outstanding = Decimal("0")
    total_overdue = Decimal("0")

    for row in rows:
        inv = row.Invoice
        balance = inv.grand_total - inv.amount_paid
        days_overdue = 0
        age_bucket = "current"
        if inv.due_date and inv.due_date < today:
            days_overdue = (today - inv.due_date).days
            if days_overdue <= 30:
                age_bucket = "1-30"
            elif days_overdue <= 60:
                age_bucket = "31-60"
            elif days_overdue <= 90:
                age_bucket = "61-90"
            else:
                age_bucket = "90+"
            total_overdue += balance
        total_outstanding += balance
        items.append(OutstandingInvoice(
            id=inv.id, invoice_no=inv.invoice_no,
            invoice_date=inv.invoice_date, due_date=inv.due_date,
            invoice_type=inv.invoice_type, party_id=inv.party_id,
            party_name=row.party_name, grand_total=inv.grand_total,
            amount_paid=inv.amount_paid, balance=balance,
            days_overdue=days_overdue, age_bucket=age_bucket,
        ))

    return OutstandingResponse(items=items, total_outstanding=total_outstanding,
                               total_overdue=total_overdue)


# ── Voucher / Receipt PDF ────────────────────────────────────────────────────

def _amount_to_words(amount: float) -> str:
    """Simple INR amount-to-words (handles up to crores)."""
    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
            'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
            'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def _two_digits(n: int) -> str:
        if n < 20: return ones[n]
        return tens[n // 10] + (' ' + ones[n % 10] if n % 10 else '')

    n = int(round(amount))
    if n == 0: return 'Zero Rupees'
    parts = []
    if n >= 10000000:
        parts.append(_two_digits(n // 10000000) + ' Crore')
        n %= 10000000
    if n >= 100000:
        parts.append(_two_digits(n // 100000) + ' Lakh')
        n %= 100000
    if n >= 1000:
        parts.append(_two_digits(n // 1000) + ' Thousand')
        n %= 1000
    if n >= 100:
        parts.append(ones[n // 100] + ' Hundred')
        n %= 100
    if n > 0:
        parts.append(_two_digits(n))
    return ' '.join(parts) + ' Rupees Only'


@router.get("/receipts/{receipt_id}/pdf")
async def receipt_pdf(
    receipt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate PDF for a payment receipt."""
    rec = (await db.execute(select(PaymentReceipt).where(PaymentReceipt.id == receipt_id))).scalar_one_or_none()
    if not rec:
        raise HTTPException(404, "Receipt not found")

    party = (await db.execute(select(Party).where(Party.id == rec.party_id))).scalar_one_or_none()
    company = (await db.execute(select(Company).limit(1))).scalar_one_or_none()

    # Get linked invoices
    linked = []
    links = (await db.execute(
        select(InvoicePayment).where(InvoicePayment.receipt_id == rec.id)
    )).scalars().all()
    for link in links:
        inv = (await db.execute(select(Invoice).where(Invoice.id == link.invoice_id))).scalar_one_or_none()
        if inv:
            linked.append({
                "invoice_no": inv.invoice_no or "Draft",
                "invoice_date": inv.invoice_date.strftime("%d-%m-%Y") if inv.invoice_date else "",
                "invoice_amount": f"{float(inv.grand_total):,.2f}",
                "applied_amount": f"{float(link.amount):,.2f}",
            })

    from app.utils.pdf_generator import generate_pdf
    context = {
        "company": company,
        "voucher_type": "receipt",
        "voucher_no": rec.receipt_no or "—",
        "voucher_date": rec.receipt_date.strftime("%d-%m-%Y") if rec.receipt_date else "",
        "party_name": party.name if party else "—",
        "party_gstin": party.gstin if party else "",
        "payment_mode": rec.payment_mode or "cash",
        "reference_no": rec.reference_no or "",
        "amount": f"{float(rec.amount):,.2f}",
        "amount_words": _amount_to_words(float(rec.amount)),
        "narration": rec.narration if hasattr(rec, 'narration') else "",
        "linked_invoices": linked,
    }

    from fastapi.responses import Response
    pdf_bytes = generate_pdf("voucher.html", context)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=Receipt_{rec.receipt_no or 'draft'}.pdf"})


@router.get("/vouchers/{voucher_id}/pdf")
async def voucher_pdf(
    voucher_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate PDF for a payment voucher."""
    rec = (await db.execute(select(PaymentVoucher).where(PaymentVoucher.id == voucher_id))).scalar_one_or_none()
    if not rec:
        raise HTTPException(404, "Voucher not found")

    party = (await db.execute(select(Party).where(Party.id == rec.party_id))).scalar_one_or_none()
    company = (await db.execute(select(Company).limit(1))).scalar_one_or_none()

    # Get linked invoices
    linked = []
    links = (await db.execute(
        select(InvoicePayment).where(InvoicePayment.voucher_id == rec.id)
    )).scalars().all()
    for link in links:
        inv = (await db.execute(select(Invoice).where(Invoice.id == link.invoice_id))).scalar_one_or_none()
        if inv:
            linked.append({
                "invoice_no": inv.invoice_no or "Draft",
                "invoice_date": inv.invoice_date.strftime("%d-%m-%Y") if inv.invoice_date else "",
                "invoice_amount": f"{float(inv.grand_total):,.2f}",
                "applied_amount": f"{float(link.amount):,.2f}",
            })

    from app.utils.pdf_generator import generate_pdf
    context = {
        "company": company,
        "voucher_type": "voucher",
        "voucher_no": rec.voucher_no or "—",
        "voucher_date": rec.voucher_date.strftime("%d-%m-%Y") if rec.voucher_date else "",
        "party_name": party.name if party else "—",
        "party_gstin": party.gstin if party else "",
        "payment_mode": rec.payment_mode or "cash",
        "reference_no": rec.reference_no if hasattr(rec, 'reference_no') else "",
        "amount": f"{float(rec.amount):,.2f}",
        "amount_words": _amount_to_words(float(rec.amount)),
        "narration": rec.narration if hasattr(rec, 'narration') else "",
        "linked_invoices": linked,
    }

    from fastapi.responses import Response
    pdf_bytes = generate_pdf("voucher.html", context)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=Voucher_{rec.voucher_no or 'draft'}.pdf"})

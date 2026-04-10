"""
Quotation router with convert-to-invoice flow.
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.quotation import Quotation, QuotationItem
from app.models.invoice import Invoice, InvoiceItem
from app.models.party import Party
from app.models.company import Company, FinancialYear
from app.models.settings import NumberSequence
from app.models.user import User
from app.schemas.quotation import (
    QuotationCreate, QuotationUpdate, QuotationResponse, QuotationListResponse
)
from app.schemas.invoice import InvoiceResponse
from app.services.gst_service import calculate_invoice_totals, is_intra_state
from app.utils.pdf_generator import generate_pdf, invoice_context, quotation_context

router = APIRouter(prefix="/api/v1/quotations", tags=["Quotations"])


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


async def _next_seq_no(db, company_id, fy_id, seq_type, prefix, fy_label) -> str:
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


async def _load_quotation(db: AsyncSession, qid: uuid.UUID) -> Quotation:
    result = await db.execute(
        select(Quotation)
        .options(selectinload(Quotation.items), selectinload(Quotation.party))
        .where(Quotation.id == qid)
    )
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(404, "Quotation not found")
    return q


_QUOTATION_EXTRA_KEYS = {"freight", "tcs_amount", "tcs_rate", "amount_due", "amount_paid"}

def _compute_quotation_totals(items_data, discount_type, discount_value, intra, tax_type="gst"):
    totals = calculate_invoice_totals(
        items=items_data,
        discount_type=discount_type,
        discount_value=discount_value,
        freight=Decimal("0"),
        tcs_rate=Decimal("0"),
        intra_state=intra,
        tax_type=tax_type,
    )
    # Strip invoice-only fields not present on Quotation model
    return {k: v for k, v in totals.items() if k not in _QUOTATION_EXTRA_KEYS}


@router.post("", response_model=QuotationResponse, status_code=201)
async def create_quotation(
    payload: QuotationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co, fy = await _get_company_fy(db)
    party = (await db.execute(select(Party).where(Party.id == payload.party_id))).scalar_one_or_none()
    if not party:
        raise HTTPException(404, "Party not found")

    qno = await _next_seq_no(db, co.id, fy.id, "quotation", co.quotation_prefix, fy.label)
    intra = is_intra_state(co.state_code, party.billing_state_code)
    items_data = [i.model_dump() for i in payload.items]
    totals = _compute_quotation_totals(items_data, payload.discount_type, payload.discount_value, intra, payload.tax_type)

    q = Quotation(
        company_id=co.id, fy_id=fy.id,
        quotation_no=qno,
        quotation_date=payload.quotation_date,
        valid_to=payload.valid_to,
        party_id=payload.party_id,
        status="draft",
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        notes=payload.notes,
        terms_and_conditions=payload.terms_and_conditions,
        created_by=current_user.id,
        **{k: v for k, v in totals.items() if k != "computed_items"},
    )
    db.add(q)
    await db.flush()

    for i, item in enumerate(totals["computed_items"]):
        db.add(QuotationItem(
            quotation_id=q.id,
            product_id=item["product_id"],
            description=item.get("description"),
            hsn_code=item.get("hsn_code"),
            quantity=Decimal(str(item["quantity"])),
            unit=item["unit"],
            rate=Decimal(str(item["rate"])),
            amount=item["amount"],
            gst_rate=Decimal(str(item.get("gst_rate", 0))),
            total_amount=item["total_amount"],
            sort_order=item.get("sort_order", i),
        ))

    await db.commit()
    return await _load_quotation(db, q.id)


@router.get("", response_model=QuotationListResponse)
async def list_quotations(
    status: str | None = None,
    party_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co, fy = await _get_company_fy(db)
    filters = [Quotation.company_id == co.id]
    if status:
        filters.append(Quotation.status == status)
    if party_id:
        filters.append(Quotation.party_id == party_id)

    total = (await db.execute(
        select(func.count()).select_from(Quotation).where(and_(*filters))
    )).scalar()
    items = (await db.execute(
        select(Quotation)
        .options(selectinload(Quotation.items), selectinload(Quotation.party))
        .where(and_(*filters))
        .order_by(Quotation.quotation_date.desc(), Quotation.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return QuotationListResponse(items=list(items), total=total, page=page, page_size=page_size)


@router.get("/{qid}", response_model=QuotationResponse)
async def get_quotation(qid: uuid.UUID, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    return await _load_quotation(db, qid)


@router.put("/{qid}", response_model=QuotationResponse)
async def update_quotation(
    qid: uuid.UUID,
    payload: QuotationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = await _load_quotation(db, qid)
    if q.status in ("converted", "rejected"):
        raise HTTPException(400, f"Cannot edit a {q.status} quotation")

    for field in ("valid_to", "discount_type", "discount_value", "notes", "terms_and_conditions"):
        val = getattr(payload, field, None)
        if val is not None:
            setattr(q, field, val)

    if payload.items is not None:
        for item in list(q.items):
            await db.delete(item)
        await db.flush()
        co, _ = await _get_company_fy(db)
        party = (await db.execute(select(Party).where(Party.id == q.party_id))).scalar_one_or_none()
        intra = is_intra_state(co.state_code, party.billing_state_code if party else None)
        items_data = [i.model_dump() for i in payload.items]
        totals = _compute_quotation_totals(items_data, q.discount_type, q.discount_value, intra)
        for k, v in totals.items():
            if k != "computed_items":
                setattr(q, k, v)
        for i, item in enumerate(totals["computed_items"]):
            db.add(QuotationItem(quotation_id=q.id, product_id=item["product_id"],
                description=item.get("description"), hsn_code=item.get("hsn_code"),
                quantity=Decimal(str(item["quantity"])), unit=item["unit"],
                rate=Decimal(str(item["rate"])), amount=item["amount"],
                gst_rate=Decimal(str(item.get("gst_rate", 0))), total_amount=item["total_amount"],
                sort_order=item.get("sort_order", i)))

    await db.commit()
    return await _load_quotation(db, qid)


@router.post("/{qid}/send", response_model=QuotationResponse)
async def mark_sent(qid: uuid.UUID, db: AsyncSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    q = await _load_quotation(db, qid)
    if q.status not in ("draft",):
        raise HTTPException(400, "Only draft quotations can be marked sent")
    q.status = "sent"
    await db.commit()
    return await _load_quotation(db, qid)


@router.post("/{qid}/convert", response_model=InvoiceResponse)
async def convert_to_invoice(
    qid: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Convert an accepted quotation into a sale invoice."""
    q = await _load_quotation(db, qid)
    if q.status not in ("draft", "sent", "accepted"):
        raise HTTPException(400, f"Cannot convert a {q.status} quotation")

    co, fy = await _get_company_fy(db)
    from app.routers.invoices import _next_invoice_no, _load_invoice

    invoice_no = await _next_invoice_no(db, co.id, fy.id, "sale", co.invoice_prefix)
    party = (await db.execute(select(Party).where(Party.id == q.party_id))).scalar_one_or_none()
    intra = is_intra_state(co.state_code, party.billing_state_code if party else None)

    items_data = [
        {
            "product_id": str(item.product_id),
            "description": item.description,
            "hsn_code": item.hsn_code,
            "quantity": item.quantity,
            "unit": item.unit,
            "rate": item.rate,
            "gst_rate": item.gst_rate,
            "sort_order": item.sort_order,
        }
        for item in q.items
    ]
    totals = calculate_invoice_totals(
        items=items_data,
        discount_type=q.discount_type,
        discount_value=q.discount_value,
        freight=Decimal("0"),
        tcs_rate=Decimal("0"),
        intra_state=intra,
    )

    inv = Invoice(
        company_id=co.id, fy_id=fy.id,
        invoice_type="sale", tax_type="gst",
        invoice_no=invoice_no,
        invoice_date=date.today(),
        party_id=q.party_id,
        quotation_id=q.id,
        status="draft",
        payment_status="unpaid",
        amount_paid=Decimal("0"),
        discount_type=q.discount_type,
        discount_value=q.discount_value,
        notes=q.notes,
        tcs_rate=Decimal("0"),
        created_by=current_user.id,
        **{k: v for k, v in totals.items() if k != "computed_items"},
    )
    db.add(inv)
    await db.flush()

    for i, item in enumerate(totals["computed_items"]):
        db.add(InvoiceItem(
            invoice_id=inv.id, product_id=item["product_id"],
            description=item.get("description"), hsn_code=item.get("hsn_code"),
            quantity=Decimal(str(item["quantity"])), unit=item["unit"],
            rate=Decimal(str(item["rate"])), amount=item["amount"],
            gst_rate=Decimal(str(item.get("gst_rate", 0))),
            cgst_amount=item["cgst_amount"], sgst_amount=item["sgst_amount"],
            igst_amount=item["igst_amount"], total_amount=item["total_amount"],
            sort_order=item.get("sort_order", i),
        ))

    q.status = "converted"
    await db.commit()
    return await _load_invoice(db, inv.id)


@router.post("/{qid}/cancel", response_model=QuotationResponse)
async def cancel_quotation(
    qid: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = await _load_quotation(db, qid)
    if q.status in ("converted", "cancelled"):
        raise HTTPException(400, f"Cannot cancel a {q.status} quotation")
    q.status = "cancelled"
    await db.commit()
    return await _load_quotation(db, qid)


@router.get("/{qid}/pdf")
async def download_quotation_pdf(
    qid: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = await _load_quotation(db, qid)
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    ctx = quotation_context(q, co)
    pdf_bytes = generate_pdf("quotation.html", ctx)
    media_type = "application/pdf" if pdf_bytes[:4] == b"%PDF" else "text/html"
    filename = f"quotation_{q.quotation_no.replace('/', '-')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

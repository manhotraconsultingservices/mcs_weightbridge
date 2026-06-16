"""Delivery Challan router — dispatch document that converts to a tax invoice.

A challan is issued when goods leave the plant; the tax invoice follows. Kept
in its own tables so it never touches GSTR-1 / P&L / receivables until it is
converted. ``challan_no`` is allocated gap-free at create (prefix ``DC``).
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.company import Company, FinancialYear
from app.models.delivery_challan import DeliveryChallan, DeliveryChallanItem
from app.models.invoice import Invoice
from app.models.party import Party
from app.models.product import Product
from app.models.token import Token
from app.models.user import User
from app.schemas.delivery_challan import (
    DeliveryChallanCreate, DeliveryChallanResponse, DeliveryChallanListResponse,
    ConvertToInvoiceRequest,
)
from app.schemas.invoice import InvoiceCreate, InvoiceItemCreate
from app.services.numbering import next_doc_no
from app.utils.pdf_generator import render_html

router = APIRouter(prefix="/api/v1/delivery-challans", tags=["Delivery Challans"])


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


async def _load(db: AsyncSession, challan_id: uuid.UUID) -> DeliveryChallan:
    ch = (await db.execute(
        select(DeliveryChallan)
        .options(selectinload(DeliveryChallan.items))
        .where(DeliveryChallan.id == challan_id)
    )).scalar_one_or_none()
    if not ch:
        raise HTTPException(404, "Delivery challan not found")
    return ch


async def _to_response(db: AsyncSession, ch: DeliveryChallan) -> DeliveryChallanResponse:
    resp = DeliveryChallanResponse.model_validate(ch)
    if ch.party_id:
        p = (await db.execute(select(Party.name).where(Party.id == ch.party_id))).scalar_one_or_none()
        resp.party_name = p
    if ch.token_id:
        tn = (await db.execute(select(Token.token_no).where(Token.id == ch.token_id))).scalar_one_or_none()
        resp.token_no = tn
    if ch.invoice_id:
        inv = (await db.execute(select(Invoice.invoice_no).where(Invoice.id == ch.invoice_id))).scalar_one_or_none()
        resp.invoice_no = inv
    return resp


@router.post("", response_model=DeliveryChallanResponse, status_code=201)
async def create_challan(
    payload: DeliveryChallanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.items:
        raise HTTPException(400, "At least one line item is required")
    co, fy = await _get_company_fy(db)

    party = None
    if payload.party_id:
        party = (await db.execute(select(Party).where(Party.id == payload.party_id))).scalar_one_or_none()
        if not party:
            raise HTTPException(404, "Party not found")

    challan_no = await next_doc_no(db, co.id, fy.id, "delivery_challan", "DC")

    sub_total = Decimal("0")
    ch = DeliveryChallan(
        company_id=co.id, fy_id=fy.id,
        challan_no=challan_no,
        challan_date=payload.challan_date,
        purpose=payload.purpose or "supply",
        party_id=payload.party_id,
        customer_name=payload.customer_name,
        token_id=payload.token_id,
        vehicle_no=(payload.vehicle_no or "").upper().strip() or None,
        transporter_name=payload.transporter_name,
        driver_name=payload.driver_name,
        distance_km=payload.distance_km,
        destination=payload.destination,
        tax_type=payload.tax_type or "gst",
        notes=payload.notes,
        status="open",
        created_by=current_user.id,
    )
    db.add(ch)
    await db.flush()

    for i, it in enumerate(payload.items):
        qty = Decimal(str(it.quantity))
        rate = Decimal(str(it.rate or 0))
        amount = (qty * rate).quantize(Decimal("0.01"))
        sub_total += amount
        db.add(DeliveryChallanItem(
            challan_id=ch.id,
            product_id=it.product_id,
            description=it.description,
            hsn_code=it.hsn_code,
            quantity=qty,
            unit=it.unit or "MT",
            rate=rate,
            amount=amount,
            gst_rate=Decimal(str(it.gst_rate or 0)),
            sort_order=it.sort_order or i,
        ))

    ch.sub_total = sub_total
    ch.total_amount = sub_total   # tax applied at invoice; challan shows value only

    try:
        from app.routers.audit import log_action
        await log_action(db, co.id, current_user.id, "create", "delivery_challan",
                         str(ch.id), {"challan_no": challan_no})
    except Exception:
        pass

    await db.commit()
    ch = await _load(db, ch.id)
    return await _to_response(db, ch)


@router.get("", response_model=DeliveryChallanListResponse)
async def list_challans(
    status: str | None = None,
    party_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(DeliveryChallan).where(DeliveryChallan.company_id == current_user.company_id)
    if status:
        stmt = stmt.where(DeliveryChallan.status == status)
    if party_id:
        stmt = stmt.where(DeliveryChallan.party_id == party_id)
    if date_from:
        stmt = stmt.where(DeliveryChallan.challan_date >= date_from)
    if date_to:
        stmt = stmt.where(DeliveryChallan.challan_date <= date_to)
    if search:
        like = f"%{search.upper()}%"
        stmt = stmt.where(
            func.upper(func.coalesce(DeliveryChallan.challan_no, "")).like(like)
            | func.upper(func.coalesce(DeliveryChallan.vehicle_no, "")).like(like)
        )

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (await db.execute(
        stmt.options(selectinload(DeliveryChallan.items))
        .order_by(DeliveryChallan.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    items = [await _to_response(db, ch) for ch in rows]
    return DeliveryChallanListResponse(items=items, total=int(total))


@router.get("/{challan_id}", response_model=DeliveryChallanResponse)
async def get_challan(
    challan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ch = await _load(db, challan_id)
    return await _to_response(db, ch)


@router.post("/{challan_id}/cancel", response_model=DeliveryChallanResponse)
async def cancel_challan(
    challan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ch = await _load(db, challan_id)
    if ch.status == "invoiced":
        raise HTTPException(400, "Challan already converted to an invoice — cancel the invoice instead")
    if ch.status == "cancelled":
        raise HTTPException(400, "Challan is already cancelled")
    ch.status = "cancelled"
    await db.commit()
    ch = await _load(db, challan_id)
    return await _to_response(db, ch)


@router.post("/{challan_id}/convert-to-invoice", response_model=DeliveryChallanResponse)
async def convert_to_invoice(
    challan_id: uuid.UUID,
    payload: ConvertToInvoiceRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Clone the challan into a DRAFT sale invoice and link them.

    Reuses the canonical invoice-creation path (GST math, party-rate safety net,
    due-date) so the invoice is identical to one raised manually.
    """
    ch = await _load(db, challan_id)
    if ch.status == "invoiced":
        raise HTTPException(400, "Challan already converted")
    if ch.status == "cancelled":
        raise HTTPException(400, "Cannot convert a cancelled challan")
    if not ch.items:
        raise HTTPException(400, "Challan has no line items")

    inv_payload = InvoiceCreate(
        invoice_type="sale",
        tax_type=ch.tax_type or "gst",
        invoice_date=(payload.invoice_date if payload and payload.invoice_date else date.today()),
        party_id=ch.party_id,
        customer_name=ch.customer_name,
        token_id=ch.token_id,
        vehicle_no=ch.vehicle_no,
        transporter_name=ch.transporter_name,
        driver_name=ch.driver_name,
        destination=ch.destination,
        delivery_note=ch.challan_no,
        notes=ch.notes,
        items=[
            InvoiceItemCreate(
                product_id=it.product_id,
                description=it.description,
                hsn_code=it.hsn_code,
                quantity=it.quantity,
                unit=it.unit,
                rate=it.rate,
                gst_rate=it.gst_rate,
                sort_order=it.sort_order,
            )
            for it in ch.items
        ],
    )

    # Reuse the invoice endpoint logic (it commits the invoice itself).
    from app.routers.invoices import create_invoice
    inv_resp = await create_invoice(inv_payload, db, current_user)

    ch.status = "invoiced"
    ch.invoice_id = inv_resp.id
    await db.commit()
    ch = await _load(db, challan_id)
    return await _to_response(db, ch)


class _GenerateEwbBody(BaseModel):
    distance_km: int | None = None
    vehicle_no: str | None = None


class _CancelEwbBody(BaseModel):
    reason: str = "2"
    remark: str = ""


@router.post("/{challan_id}/generate-ewb", response_model=DeliveryChallanResponse)
async def generate_challan_ewb(
    challan_id: uuid.UUID,
    payload: _GenerateEwbBody | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate an E-Way Bill for a delivery challan (goods moving without an invoice)."""
    from app.services.eway_service import load_eway_config, generate_for_challan
    ch = await _load(db, challan_id)
    if ch.status == "cancelled":
        raise HTTPException(400, "Cannot generate an E-Way Bill for a cancelled challan")
    if ch.ewb_status == "generated" and ch.ewb_no:
        raise HTTPException(400, f"E-Way Bill {ch.ewb_no} already exists for this challan")
    cfg = await load_eway_config(db)
    if not cfg or not cfg.is_enabled:
        raise HTTPException(400, "E-Way Bill is not configured/enabled (Settings → E-Way Bill)")
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    result = await generate_for_challan(
        db, ch, co, cfg,
        distance_km=(payload.distance_km if payload and payload.distance_km else 0),
        vehicle_no=(payload.vehicle_no if payload else None),
    )
    await db.commit()
    if not result.success:
        raise HTTPException(502, result.error_message or "EWB generation failed")
    ch = await _load(db, challan_id)
    return await _to_response(db, ch)


@router.post("/{challan_id}/cancel-ewb", response_model=DeliveryChallanResponse)
async def cancel_challan_ewb(
    challan_id: uuid.UUID,
    payload: _CancelEwbBody | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.eway_service import load_eway_config, cancel_ewb as _cancel
    ch = await _load(db, challan_id)
    if not ch.ewb_no or ch.ewb_status != "generated":
        raise HTTPException(400, "No active E-Way Bill to cancel")
    cfg = await load_eway_config(db)
    if not cfg or not cfg.is_enabled:
        raise HTTPException(400, "E-Way Bill is not configured/enabled")
    result = await _cancel(cfg, ch.ewb_no,
                           reason=(payload.reason if payload else "2"),
                           remark=(payload.remark if payload else ""))
    if result.success:
        ch.ewb_status = "cancelled"
        ch.ewb_error = None
    else:
        ch.ewb_error = result.error_message
    await db.commit()
    if not result.success:
        raise HTTPException(502, result.error_message or "EWB cancellation failed")
    ch = await _load(db, challan_id)
    return await _to_response(db, ch)


@router.get("/{challan_id}/pdf", response_class=HTMLResponse)
async def challan_pdf(
    challan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ch = await _load(db, challan_id)
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    party = None
    if ch.party_id:
        party = (await db.execute(select(Party).where(Party.id == ch.party_id))).scalar_one_or_none()
    # Resolve product names for line items
    prod_names: dict = {}
    for it in ch.items:
        if it.product_id not in prod_names:
            prod_names[it.product_id] = (await db.execute(
                select(Product.name).where(Product.id == it.product_id)
            )).scalar_one_or_none()
    html = render_html("delivery_challan.html", {
        "challan": ch,
        "company": co,
        "party": party,
        "product_names": {str(k): v for k, v in prod_names.items()},
    })
    return HTMLResponse(content=html)

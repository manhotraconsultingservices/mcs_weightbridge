"""
Invoice router — Sales & Purchase invoices with GST.

Gap-free numbering:
  invoice_no is assigned ONLY at POST /{id}/finalise (not at draft creation).
  Draft invoices display invoice_no=None until the user decides to finalise.

Move-to-Supplement:
  POST /{id}/move-to-supplement — USB-gated. Migrates draft invoice + token data
  out of normal tables into the encrypted supplementary_entries table.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.invoice import Invoice, InvoiceItem
from app.models.party import Party
from app.models.product import Product
from app.models.token import Token
from app.models.company import Company, FinancialYear
from app.models.settings import NumberSequence
from app.models.user import User
from app.schemas.invoice import (
    InvoiceCreate, InvoiceUpdate, InvoiceResponse, InvoiceListResponse
)
from app.services.gst_service import calculate_invoice_totals, is_intra_state
from app.utils.pdf_generator import generate_pdf, invoice_context, render_html

router = APIRouter(prefix="/api/v1/invoices", tags=["Invoices"])


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

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


async def _next_invoice_no(
    db: AsyncSession, company_id: uuid.UUID, fy_id: uuid.UUID,
    invoice_type: str, prefix: str
) -> str:
    """
    Assign the next sequential invoice number with row-level locking.
    Called at FINALISE — not at draft creation — to prevent numbering gaps.
    """
    seq_type = f"{invoice_type}_invoice"
    result = await db.execute(
        select(NumberSequence)
        .where(
            NumberSequence.company_id == company_id,
            NumberSequence.fy_id == fy_id,
            NumberSequence.sequence_type == seq_type,
        )
        .with_for_update()
    )
    seq = result.scalar_one_or_none()
    if not seq:
        seq = NumberSequence(
            company_id=company_id, fy_id=fy_id,
            sequence_type=seq_type, prefix=prefix,
            last_number=0, reset_daily=False,
        )
        db.add(seq)
    seq.last_number += 1
    await db.flush()
    fy_label = (await db.get(FinancialYear, fy_id)).label  # type: ignore[arg-type]
    short_fy = fy_label[-5:] if fy_label else "25-26"
    return f"{prefix}/{short_fy}/{seq.last_number:04d}"


async def _load_invoice(db: AsyncSession, invoice_id: uuid.UUID) -> Invoice:
    result = await db.execute(
        select(Invoice)
        .options(
            selectinload(Invoice.items),
            selectinload(Invoice.party),
        )
        .where(Invoice.id == invoice_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


def _get_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _invoice_to_dict(inv: Invoice, token_no: int | None = None,
                     token_date: date | None = None) -> dict:
    """Build a dict from an ORM Invoice, injecting denormalized token fields."""
    d = {c.name: getattr(inv, c.name) for c in inv.__table__.columns}
    d["items"] = inv.items
    d["party"] = inv.party
    d["token_no"] = token_no
    d["token_date"] = token_date
    return d


# ------------------------------------------------------------------ #
# CRUD Endpoints
# ------------------------------------------------------------------ #

@router.post("", response_model=InvoiceResponse, status_code=201)
async def create_invoice(
    payload: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co, fy = await _get_company_fy(db)

    # invoice_no intentionally left NULL — assigned at finalise for gap-free numbering
    prefix = "INV" if payload.invoice_type == "sale" else "PUR"

    party = None
    if payload.party_id:
        party = (await db.execute(select(Party).where(Party.id == payload.party_id))).scalar_one_or_none()
        if not party:
            raise HTTPException(404, "Party not found")

    intra = is_intra_state(co.state_code, party.billing_state_code if party else co.state_code)

    items_data = [i.model_dump() for i in payload.items]
    totals = calculate_invoice_totals(
        items=items_data,
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        freight=payload.freight,
        tcs_rate=payload.tcs_rate,
        intra_state=intra,
        tax_type=payload.tax_type,
    )

    gross_weight = payload.gross_weight
    tare_weight = payload.tare_weight
    net_weight = payload.net_weight
    vehicle_no = payload.vehicle_no

    if payload.token_id:
        token = (await db.execute(select(Token).where(Token.id == payload.token_id))).scalar_one_or_none()
        if token:
            gross_weight = gross_weight or token.gross_weight
            tare_weight = tare_weight or token.tare_weight
            net_weight = net_weight or token.net_weight
            vehicle_no = vehicle_no or token.vehicle_no

    invoice = Invoice(
        company_id=co.id,
        fy_id=fy.id,
        invoice_type=payload.invoice_type,
        tax_type=payload.tax_type,
        invoice_no=None,          # gap-free: assigned at finalise
        invoice_date=payload.invoice_date,
        party_id=payload.party_id,
        customer_name=payload.customer_name,
        token_id=payload.token_id,
        quotation_id=payload.quotation_id,
        vehicle_no=vehicle_no,
        transporter_name=payload.transporter_name,
        eway_bill_no=payload.eway_bill_no,
        gross_weight=gross_weight,
        tare_weight=tare_weight,
        net_weight=net_weight,
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        payment_mode=payload.payment_mode,
        notes=payload.notes,
        tcs_rate=payload.tcs_rate,
        created_by=current_user.id,
        status="draft",
        payment_status="unpaid",
        amount_paid=Decimal("0"),
        **{k: v for k, v in totals.items() if k != "computed_items"},
    )
    db.add(invoice)
    await db.flush()

    for i, item_data in enumerate(totals["computed_items"]):
        db.add(InvoiceItem(
            invoice_id=invoice.id,
            product_id=item_data["product_id"],
            description=item_data.get("description"),
            hsn_code=item_data.get("hsn_code"),
            quantity=Decimal(str(item_data["quantity"])),
            unit=item_data["unit"],
            rate=Decimal(str(item_data["rate"])),
            amount=item_data["amount"],
            gst_rate=Decimal(str(item_data.get("gst_rate", 0))),
            cgst_amount=item_data["cgst_amount"],
            sgst_amount=item_data["sgst_amount"],
            igst_amount=item_data["igst_amount"],
            total_amount=item_data["total_amount"],
            sort_order=item_data.get("sort_order", i),
        ))

    from app.routers.audit import log_action
    await log_action(db, co.id, current_user.id, "create", "invoice",
                     entity_id=str(invoice.id),
                     details={"type": payload.invoice_type, "status": "draft"})
    await db.commit()
    return await _load_invoice(db, invoice.id)


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    invoice_type: str | None = None,
    status: str | None = None,
    party_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co, fy = await _get_company_fy(db)

    filters = [Invoice.company_id == co.id]
    if invoice_type:
        filters.append(Invoice.invoice_type == invoice_type)
    if status:
        filters.append(Invoice.status == status)
    if party_id:
        filters.append(Invoice.party_id == party_id)
    if date_from:
        filters.append(Invoice.invoice_date >= date_from)
    if date_to:
        filters.append(Invoice.invoice_date <= date_to)
    if search:
        filters.append(Invoice.invoice_no.ilike(f"%{search}%"))

    total = (await db.execute(
        select(func.count()).select_from(Invoice).where(and_(*filters))
    )).scalar()

    invoices = (await db.execute(
        select(Invoice)
        .options(selectinload(Invoice.items), selectinload(Invoice.party))
        .where(and_(*filters))
        .order_by(Invoice.invoice_date.desc(), Invoice.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()

    # Denormalize token_no and token_date for each invoice
    enriched = []
    for inv in invoices:
        token_no = None
        token_date = None
        if inv.token_id:
            tok = (await db.execute(
                select(Token.token_no, Token.token_date).where(Token.id == inv.token_id)
            )).first()
            if tok:
                token_no, token_date = tok
        # Inject token fields into the pydantic response
        inv_dict = InvoiceResponse.model_validate(inv)
        inv_dict.token_no = token_no
        inv_dict.token_date = token_date
        enriched.append(inv_dict)

    return {"items": enriched, "total": total, "page": page, "page_size": page_size}


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = await _load_invoice(db, invoice_id)
    resp = InvoiceResponse.model_validate(inv)
    if inv.token_id:
        tok = (await db.execute(
            select(Token.token_no, Token.token_date).where(Token.id == inv.token_id)
        )).first()
        if tok:
            resp.token_no, resp.token_date = tok
    return resp


@router.put("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: uuid.UUID,
    payload: InvoiceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = await _load_invoice(db, invoice_id)
    if inv.status == "cancelled":
        raise HTTPException(400, "Cannot edit a cancelled invoice")
    if inv.status == "final":
        raise HTTPException(400, "Finalise a new invoice; editing is not allowed after finalisation")

    # Header fields — only editable on draft invoices
    if inv.status == "draft":
        if payload.party_id is not None:
            inv.party_id = payload.party_id
            inv.customer_name = None          # clear walk-in name when party is set
        if payload.customer_name is not None:
            inv.customer_name = payload.customer_name
            inv.party_id = None               # clear party when walk-in name is set
        if payload.invoice_date is not None:
            inv.invoice_date = payload.invoice_date
        if payload.tax_type is not None:
            inv.tax_type = payload.tax_type

    for field in ("vehicle_no", "transporter_name", "eway_bill_no",
                  "discount_type", "discount_value", "freight",
                  "tcs_rate", "payment_mode", "notes"):
        val = getattr(payload, field, None)
        if val is not None:
            setattr(inv, field, val)

    if payload.items is not None:
        for item in list(inv.items):
            await db.delete(item)
        await db.flush()

        co, _ = await _get_company_fy(db)
        party = (await db.execute(select(Party).where(Party.id == inv.party_id))).scalar_one_or_none()
        intra = is_intra_state(co.state_code, party.billing_state_code if party else None)

        items_data = [i.model_dump() for i in payload.items]
        totals = calculate_invoice_totals(
            items=items_data,
            discount_type=inv.discount_type,
            discount_value=inv.discount_value,
            freight=inv.freight,
            tcs_rate=inv.tcs_rate,
            intra_state=intra,
            tax_type=inv.tax_type,
        )
        for k, v in totals.items():
            if k != "computed_items":
                setattr(inv, k, v)

        for i, item_data in enumerate(totals["computed_items"]):
            db.add(InvoiceItem(
                invoice_id=inv.id,
                product_id=item_data["product_id"],
                description=item_data.get("description"),
                hsn_code=item_data.get("hsn_code"),
                quantity=Decimal(str(item_data["quantity"])),
                unit=item_data["unit"],
                rate=Decimal(str(item_data["rate"])),
                amount=item_data["amount"],
                gst_rate=Decimal(str(item_data.get("gst_rate", 0))),
                cgst_amount=item_data["cgst_amount"],
                sgst_amount=item_data["sgst_amount"],
                igst_amount=item_data["igst_amount"],
                total_amount=item_data["total_amount"],
                sort_order=item_data.get("sort_order", i),
            ))

    await db.commit()
    return await _load_invoice(db, invoice_id)


@router.post("/{invoice_id}/finalise", response_model=InvoiceResponse)
async def finalise_invoice(
    invoice_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = await _load_invoice(db, invoice_id)
    if inv.status != "draft":
        raise HTTPException(400, f"Invoice is already {inv.status}")
    if not inv.items:
        raise HTTPException(400, "Cannot finalise an invoice with no items")

    co, fy = await _get_company_fy(db)

    # Assign invoice_no NOW (gap-free: only finalised invoices consume sequence numbers)
    if not inv.invoice_no:
        prefix = "INV" if inv.invoice_type == "sale" else "PUR"
        inv.invoice_no = await _next_invoice_no(db, co.id, fy.id, inv.invoice_type, prefix)

    inv.status = "final"

    from app.routers.audit import log_action
    await log_action(db, co.id, current_user.id, "finalize", "invoice",
                     entity_id=str(invoice_id),
                     details={"invoice_no": inv.invoice_no, "grand_total": str(inv.grand_total)})
    await db.commit()

    # ── Fire invoice_finalized notification (background, non-blocking) ─────────
    _notify_ctx = {
        "invoice_no": inv.invoice_no or "—",
        "invoice_date": inv.invoice_date.strftime("%d-%m-%Y") if inv.invoice_date else "—",
        "grand_total": f"{float(inv.grand_total or 0):,.2f}",
        "party_name": inv.party.name if inv.party else "—",
        "party_email": inv.party.email or "" if inv.party else "",
        "party_phone": inv.party.phone or "" if inv.party else "",
        "company_name": co.name,
    }
    background_tasks.add_task(
        _send_notification_bg,
        co.id, "invoice_finalized", _notify_ctx, "invoice", str(invoice_id),
    )

    return await _load_invoice(db, invoice_id)


async def _send_notification_bg(
    company_id: uuid.UUID,
    event_type: str,
    context: dict,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> None:
    """Background-task wrapper: opens its own DB session and fires a notification."""
    import logging as _logging
    try:
        from app.database import async_session
        from app.integrations.notifications.service import send_notification
        async with async_session() as db:
            await send_notification(db, company_id, event_type, context, entity_type, entity_id)
    except Exception as exc:
        _logging.getLogger(__name__).warning("Background notification failed [%s]: %s", event_type, exc)


@router.post("/{invoice_id}/move-to-supplement", status_code=201)
async def move_to_supplement(
    invoice_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Move a draft invoice (and its linked token data) into the encrypted
    supplementary_entries table. Requires USB authorization.
    Deletes the invoice and items from normal tables after migration.
    """
    from app.services.usb_guard import check_usb_authorized
    usb_status = await check_usb_authorized(db, user_id=str(current_user.id))
    if not usb_status["authorized"]:
        raise HTTPException(403, "USB key required to move invoices to Supplement")

    inv = await _load_invoice(db, invoice_id)
    if inv.status != "draft":
        raise HTTPException(400, f"Only draft invoices can be moved to Supplement (current: {inv.status})")

    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()

    # Fetch linked token (if any)
    token = None
    if inv.token_id:
        token = (await db.execute(select(Token).where(Token.id == inv.token_id))).scalar_one_or_none()

    # Load party name for customer_name field
    party_name = None
    if inv.party_id:
        party = (await db.execute(select(Party).where(Party.id == inv.party_id))).scalar_one_or_none()
        if party:
            party_name = party.name
    customer_name = party_name or inv.customer_name or ""

    # Compute total amount from invoice
    amount = float(inv.grand_total or 0)
    net_weight_val = float(inv.net_weight or 0) if inv.net_weight else None
    # Rate from first line item
    rate_val = None
    if inv.items:
        rate_val = float(inv.items[0].rate)

    # Assign gap-free supplement entry number via DB sequence
    from sqlalchemy import text as _text
    entry_no_row = (await db.execute(_text("SELECT nextval('supplement_seq')"))).scalar()
    entry_no = f"SE/{entry_no_row:05d}"

    # Encrypt all sensitive fields
    from app.utils.crypto import encrypt, encrypt_float
    customer_enc   = encrypt(customer_name)
    vehicle_enc    = encrypt(inv.vehicle_no or (token.vehicle_no if token else None))
    nw_enc         = encrypt_float(net_weight_val)
    rate_enc       = encrypt_float(rate_val)
    amount_enc     = encrypt_float(amount)
    notes_enc      = encrypt(inv.notes)
    pm_enc         = encrypt(inv.payment_mode or "credit")

    # Encrypt token context
    token_no_enc   = encrypt(str(token.token_no) if token and token.token_no else None)
    token_date_enc = encrypt(str(token.token_date) if token else None)
    gross_enc      = encrypt_float(float(token.gross_weight) if token and token.gross_weight else None)
    tare_enc       = encrypt_float(float(token.tare_weight) if token and token.tare_weight else None)

    import hmac as hmac_mod, hashlib, os
    server_secret = os.environ.get("PRIVATE_DATA_KEY", os.environ.get("SECRET_KEY", "fallback"))
    ihash_data = f"{entry_no}|{inv.invoice_date}|{amount_enc}|{str(current_user.id)}"
    ihash = hmac_mod.new(server_secret.encode(), ihash_data.encode(), hashlib.sha256).hexdigest()

    await db.execute(
        _text("""
            INSERT INTO supplementary_entries
              (company_id, invoice_no, invoice_date,
               customer_name_enc, vehicle_no_enc, net_weight_enc,
               rate_enc, amount_enc, notes_enc,
               customer_name, vehicle_no, net_weight, rate, amount, notes,
               payment_mode, created_by, integrity_hash,
               token_id, token_no_enc, token_date_enc, gross_weight_enc, tare_weight_enc)
            VALUES
              (:cid, :no, :dt,
               :cn, :vn, :nw,
               :rt, :am, :nt,
               NULL, NULL, NULL, NULL, 0, NULL,
               :pm, :uid, :ih,
               :tid, :tno, :tdt, :tgw, :ttw)
        """),
        {
            "cid": str(co.id), "no": entry_no, "dt": inv.invoice_date,
            "cn": customer_enc, "vn": vehicle_enc, "nw": nw_enc,
            "rt": rate_enc, "am": amount_enc, "nt": notes_enc,
            "pm": pm_enc, "uid": str(current_user.id), "ih": ihash,
            "tid": str(inv.token_id) if inv.token_id else None,
            "tno": token_no_enc, "tdt": token_date_enc,
            "tgw": gross_enc, "ttw": tare_enc,
        }
    )

    # Mark token as supplement (hides from normal invoice lists)
    if token:
        token.is_supplement = True

    # Delete invoice items and invoice from normal tables
    for item in list(inv.items):
        await db.delete(item)
    await db.flush()
    await db.delete(inv)

    # Deliberately NO audit log for supplement invoices — supplement entries are private.
    # Also purge any prior audit logs generated for this invoice (e.g. the auto-create draft log).
    await db.execute(
        _text("DELETE FROM audit_log WHERE entity_id = :eid AND entity_type = 'invoice'"),
        {"eid": str(invoice_id)}
    )
    await db.commit()

    return {"entry_no": entry_no, "message": f"Invoice migrated to Supplement as {entry_no}"}


@router.get("/{invoice_id}/pdf")
async def download_pdf(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = await _load_invoice(db, invoice_id)
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    ctx = invoice_context(inv, co)
    pdf_bytes = generate_pdf("invoice.html", ctx)
    media_type = "application/pdf" if pdf_bytes[:4] == b"%PDF" else "text/html"
    safe_no = (inv.invoice_no or "draft").replace('/', '-')
    filename = f"invoice_{safe_no}.pdf"
    return Response(
        content=pdf_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{invoice_id}/print", response_class=HTMLResponse)
async def print_invoice(
    invoice_id: uuid.UUID,
    format: str = Query("a4"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return an HTML invoice for printing. format=a4 or thermal."""
    inv = await _load_invoice(db, invoice_id)
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    ctx = invoice_context(inv, co)

    if format == "thermal":
        html = render_html("invoice_thermal.html", ctx)
    else:
        # A4: render the standard invoice template and inject auto-print script
        html = render_html("invoice.html", ctx)
        html = html.replace(
            "</body>",
            "<script>window.onload=function(){window.print();window.onafterprint=function(){window.close();};};</script></body>"
        )
    return HTMLResponse(content=html)


@router.post("/{invoice_id}/cancel", response_model=InvoiceResponse)
async def cancel_invoice(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "accountant")),
):
    inv = await _load_invoice(db, invoice_id)
    if inv.status == "cancelled":
        raise HTTPException(400, "Already cancelled")
    inv.status = "cancelled"
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    from app.routers.audit import log_action
    if co:
        await log_action(db, co.id, current_user.id, "cancel", "invoice",
                         entity_id=str(invoice_id), details={"invoice_no": inv.invoice_no})
    await db.commit()
    return await _load_invoice(db, invoice_id)

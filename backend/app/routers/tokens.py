"""
Token management router — weighbridge token lifecycle.

Token workflow:
  OPEN → (first weight) → FIRST_WEIGHT → (second weight) → SECOND_WEIGHT → COMPLETED
  Any status → CANCELLED

Gap-free numbering:
  token_no is assigned ONLY when a token reaches COMPLETED status (at second-weight).
  In-progress tokens display token_no=None in the UI.

For sale tokens:     truck arrives EMPTY (tare first),  leaves LOADED (gross second).  Net = gross − tare.
For purchase tokens: truck arrives LOADED (gross first), leaves EMPTY  (tare second). Net = gross − tare.
"""
import uuid
import random
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, text
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.token import Token
from app.models.settings import NumberSequence
from app.models.company import Company, FinancialYear
from app.models.party import Party, PartyRate
from app.models.product import Product
from app.models.vehicle import Vehicle, Driver, Transporter
from app.models.user import User
from app.schemas.token import (
    TokenCreate, TokenFirstWeight, TokenSecondWeight, TokenUpdate, TokenResponse, TokenListResponse
)
from app.utils.pdf_generator import render_html

router = APIRouter(prefix="/api/v1/tokens", tags=["Tokens"])


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

async def _get_company_and_fy(db: AsyncSession):
    company_result = await db.execute(select(Company).limit(1))
    company = company_result.scalar_one_or_none()
    if not company:
        raise HTTPException(500, "Company not configured")

    fy_result = await db.execute(
        select(FinancialYear).where(FinancialYear.is_active == True).limit(1)
    )
    fy = fy_result.scalar_one_or_none()
    if not fy:
        raise HTTPException(500, "No active financial year")
    return company, fy


async def _next_token_no(db: AsyncSession, company_id: uuid.UUID, fy_id: uuid.UUID,
                          token_date: date) -> int:
    """
    Generate a random 4-digit token number (1000–9999) that is unique for the day.

    Random numbering is intentional: when tokens are moved to Supplement they are
    removed from the visible list. Sequential numbering would leave obvious gaps
    (e.g. 1, 2, 4, 5 — where did 3 go?). Random numbers make gaps meaningless
    and reveal nothing about hidden entries.

    Collision probability is negligible for typical daily volumes (<100 tokens)
    against a 9000-value space. Falls back to 5-digit range if somehow exhausted.
    """
    for _ in range(50):
        candidate = random.randint(1000, 9999)
        existing = await db.execute(
            select(Token.id).where(
                and_(
                    Token.company_id == company_id,
                    Token.token_date == token_date,
                    Token.token_no == candidate,
                )
            )
        )
        if existing.scalar_one_or_none() is None:
            return candidate

    # Extremely unlikely fallback — 5-digit space
    for _ in range(50):
        candidate = random.randint(10000, 99999)
        existing = await db.execute(
            select(Token.id).where(
                and_(
                    Token.company_id == company_id,
                    Token.token_date == token_date,
                    Token.token_no == candidate,
                )
            )
        )
        if existing.scalar_one_or_none() is None:
            return candidate

    raise HTTPException(500, "Could not generate a unique token number. Please try again.")


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
        async with await get_tenant_session(tenant_slug) as db:
            from app.integrations.notifications.service import send_notification
            await send_notification(db, company_id, event_type, context, entity_type, entity_id)
    except Exception as exc:
        _logging.getLogger(__name__).warning("Background notification failed [%s]: %s", event_type, exc)


async def _load_token(db: AsyncSession, token_id: uuid.UUID) -> Token:
    result = await db.execute(
        select(Token)
        .options(
            selectinload(Token.party),
            selectinload(Token.product),
            selectinload(Token.vehicle),
            selectinload(Token.driver),
            selectinload(Token.transporter),
        )
        .where(Token.id == token_id)
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(404, "Token not found")
    return token


def _compute_weights(token: Token):
    """
    Set gross / tare / net weights based on token_type.

    Sale:     truck arrives EMPTY first  → first  = tare,  second = gross
    Purchase: truck arrives LOADED first → first  = gross, second = tare
    General:  fallback to direction field; default to sale logic if direction unset.

    Uses token_type (never null) as the primary discriminator so that a None
    direction value never silently produces a wrong result.
    """
    if token.first_weight is None or token.second_weight is None:
        return

    if token.token_type == "sale":
        # Empty truck weighed first (tare), loaded truck weighed second (gross)
        token.tare_weight = token.first_weight
        token.gross_weight = token.second_weight
    elif token.token_type == "purchase":
        # Loaded truck weighed first (gross), empty truck weighed second (tare)
        token.gross_weight = token.first_weight
        token.tare_weight = token.second_weight
    else:
        # General token: fall back to direction; default to sale logic if unset
        if token.direction in ("inbound", "in"):
            token.gross_weight = token.first_weight
            token.tare_weight = token.second_weight
        else:
            token.tare_weight = token.first_weight
            token.gross_weight = token.second_weight

    net = token.gross_weight - token.tare_weight
    token.net_weight = max(net, Decimal("0"))


async def _fetch_rate(db: AsyncSession, party_id: uuid.UUID | None,
                      product_id: uuid.UUID | None) -> Decimal:
    """
    Fetch the best applicable rate for a party+product combination.
    Priority: party_rates (most recent effective_from) → product.default_rate → 0
    """
    if party_id and product_id:
        result = await db.execute(
            select(PartyRate)
            .where(
                PartyRate.party_id == party_id,
                PartyRate.product_id == product_id,
                PartyRate.effective_from <= date.today(),
            )
            .order_by(PartyRate.effective_from.desc())
            .limit(1)
        )
        pr = result.scalar_one_or_none()
        if pr:
            return pr.rate

    if product_id:
        product = (await db.execute(select(Product).where(Product.id == product_id))).scalar_one_or_none()
        if product and product.default_rate:
            return product.default_rate

    return Decimal("0")


async def _auto_create_invoice(db: AsyncSession, token: Token, company: Company,
                               fy: FinancialYear, user_id: uuid.UUID,
                               invoice_type: str = "sale"):
    """
    Auto-create a draft Sales or Purchase Invoice from a completed token.
    invoice_no is left NULL — assigned only when the user finalises.
    Skipped if token has no party or product.
    """
    if not token.party_id or not token.product_id:
        return  # Cannot auto-create without party and product

    # Load product for unit and GST details
    product = (await db.execute(select(Product).where(Product.id == token.product_id))).scalar_one_or_none()
    if not product:
        return

    rate = await _fetch_rate(db, token.party_id, token.product_id)

    # Convert weight to MT if unit is MT (weights stored in KG in some systems; here net_weight is in KG from scale)
    # In this system net_weight is stored as-is from the scale (KG). Product unit determines display.
    if product.unit == "MT":
        qty = token.net_weight / Decimal("1000") if token.net_weight else Decimal("0")
    else:
        qty = token.net_weight if token.net_weight else Decimal("0")

    amount = (qty * rate).quantize(Decimal("0.01"))
    gst_rate = product.gst_rate or Decimal("0")

    # GST calculation (intra-state assumed; will be recalculated if party state differs)
    from app.services.gst_service import calculate_invoice_totals, is_intra_state
    from app.models.party import Party as PartyModel
    party = (await db.execute(select(PartyModel).where(PartyModel.id == token.party_id))).scalar_one_or_none()
    intra = is_intra_state(company.state_code, party.billing_state_code if party else company.state_code)

    items_data = [{
        "product_id": str(token.product_id),
        "description": product.name,
        "hsn_code": product.hsn_code,
        "quantity": float(qty),
        "unit": product.unit,
        "rate": float(rate),
        "gst_rate": float(gst_rate),
        "sort_order": 0,
    }]
    totals = calculate_invoice_totals(
        items=items_data,
        discount_type=None,
        discount_value=Decimal("0"),
        freight=Decimal("0"),
        tcs_rate=Decimal("0"),
        intra_state=intra,
        tax_type="gst",
    )

    from app.models.invoice import Invoice, InvoiceItem
    # Auto-fill driver name from token's driver relationship
    driver_name = None
    if token.driver_id:
        from app.models.vehicle import Driver
        driver = (await db.execute(select(Driver).where(Driver.id == token.driver_id))).scalar_one_or_none()
        if driver:
            driver_name = driver.name

    invoice = Invoice(
        company_id=company.id,
        fy_id=fy.id,
        invoice_type=invoice_type,
        tax_type="gst",
        invoice_no=None,          # assigned at finalise (gap-free)
        invoice_date=token.token_date,
        party_id=token.party_id,
        token_id=token.id,
        vehicle_no=token.vehicle_no,
        gross_weight=token.gross_weight,
        tare_weight=token.tare_weight,
        net_weight=token.net_weight,
        # Auto-fill transport metadata
        driver_name=driver_name,
        destination=party.billing_city if party else None,
        status="draft",
        payment_status="unpaid",
        amount_paid=Decimal("0"),
        created_by=user_id,
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
            sort_order=i,
        ))


# ------------------------------------------------------------------ #
# Endpoints
# ------------------------------------------------------------------ #

@router.post("", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def create_token(
    payload: TokenCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company, fy = await _get_company_and_fy(db)
    # token_no is intentionally NOT assigned here — it is assigned at COMPLETED
    # to guarantee gap-free daily sequencing.

    token = Token(
        company_id=company.id,
        fy_id=fy.id,
        token_no=None,            # placeholder; assigned on completion
        token_date=payload.token_date,
        direction=payload.direction,
        token_type=payload.token_type,
        party_id=payload.party_id,
        product_id=payload.product_id,
        vehicle_no=payload.vehicle_no.upper().strip(),
        vehicle_id=payload.vehicle_id,
        vehicle_type=payload.vehicle_type,
        driver_id=payload.driver_id,
        transporter_id=payload.transporter_id,
        remarks=payload.remarks,
        created_by=current_user.id,
        status="OPEN",
    )
    db.add(token)
    await db.commit()

    # Audit log
    try:
        from app.routers.audit import log_action
        await log_action(db, company.id, current_user.id, "create", "token",
                         str(token.id), {"vehicle_no": token.vehicle_no, "type": token.token_type})
    except Exception:
        pass

    return await _load_token(db, token.id)


@router.get("", response_model=TokenListResponse)
async def list_tokens(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    token_type: str | None = None,
    search: str | None = None,   # vehicle_no, token_no, or party/customer name
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company, fy = await _get_company_and_fy(db)

    filters = [Token.company_id == company.id, Token.is_supplement == False]
    if date_from:
        filters.append(Token.token_date >= date_from)
    if date_to:
        filters.append(Token.token_date <= date_to)
    if status:
        filters.append(Token.status == status.upper())
    if token_type:
        filters.append(Token.token_type == token_type.lower())
    if search:
        try:
            no = int(search)
            filters.append(Token.token_no == no)
        except ValueError:
            # Search vehicle_no OR party name via subquery
            party_ids = (await db.execute(
                select(Party.id).where(Party.name.ilike(f"%{search}%"))
            )).scalars().all()
            filters.append(
                or_(
                    Token.vehicle_no.ilike(f"%{search}%"),
                    Token.party_id.in_(party_ids) if party_ids else text("FALSE"),
                )
            )

    count_result = await db.execute(
        select(func.count()).select_from(Token).where(and_(*filters))
    )
    total = count_result.scalar()

    result = await db.execute(
        select(Token)
        .options(selectinload(Token.party), selectinload(Token.product), selectinload(Token.vehicle))
        .where(and_(*filters))
        .order_by(Token.token_date.desc(), Token.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()

    return TokenListResponse(items=list(items), total=total, page=page, page_size=page_size)


@router.get("/today", response_model=list[TokenResponse])
async def today_tokens(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company, fy = await _get_company_and_fy(db)
    today = date.today()

    result = await db.execute(
        select(Token)
        .options(selectinload(Token.party), selectinload(Token.product), selectinload(Token.vehicle))
        .where(and_(Token.company_id == company.id, Token.token_date == today, Token.is_supplement == False))
        .order_by(Token.created_at.asc())
    )
    return list(result.scalars().all())


@router.get("/{token_id}", response_model=TokenResponse)
async def get_token(
    token_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.invoice import Invoice
    from app.schemas.token import LinkedInvoice

    token = await _load_token(db, token_id)
    resp = TokenResponse.model_validate(token)

    inv_row = (await db.execute(
        select(
            Invoice.id,
            Invoice.invoice_no,
            Invoice.grand_total,
            Invoice.status,
            Invoice.payment_status,
        )
        .where(Invoice.token_id == token_id)
        .limit(1)
    )).fetchone()

    if inv_row:
        resp.linked_invoice = LinkedInvoice(**dict(inv_row._mapping))

    return resp


@router.put("/{token_id}", response_model=TokenResponse)
async def update_token(
    token_id: uuid.UUID,
    payload: TokenUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    token = await _load_token(db, token_id)
    if token.status in ("COMPLETED", "CANCELLED"):
        raise HTTPException(400, f"Cannot edit a {token.status} token")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(token, field, value)
    if payload.vehicle_no:
        token.vehicle_no = payload.vehicle_no.upper().strip()

    await db.commit()
    return await _load_token(db, token_id)


@router.post("/{token_id}/first-weight", response_model=TokenResponse)
async def record_first_weight(
    token_id: uuid.UUID,
    payload: TokenFirstWeight,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    token = await _load_token(db, token_id)

    if token.status != "OPEN":
        raise HTTPException(400, f"First weight can only be recorded on OPEN tokens (current: {token.status})")

    token.first_weight = payload.weight_kg
    token.first_weight_at = datetime.now(timezone.utc)
    token.first_weight_by = current_user.id
    token.is_manual_weight = payload.is_manual
    token.status = "FIRST_WEIGHT"

    # Sale: first weight is the empty truck (tare). Purchase: first weight is the loaded truck (gross).
    token.first_weight_type = "tare" if token.token_type == "sale" else "gross"

    await db.commit()

    # Audit log
    try:
        from app.routers.audit import log_action
        company, _ = await _get_company_and_fy(db)
        await log_action(db, company.id, current_user.id, "first_weight", "token",
                         str(token.id), {"vehicle_no": token.vehicle_no, "weight": float(payload.weight_kg)})
    except Exception:
        pass

    # Capture snapshot at 1st weight for ALL token types
    _bg_tenant_1w = None
    try:
        from app.multitenancy.context import current_tenant_slug
        _bg_tenant_1w = current_tenant_slug.get()
    except Exception:
        pass
    from app.routers.cameras import trigger_snapshot_capture
    background_tasks.add_task(trigger_snapshot_capture, token_id, _bg_tenant_1w, "first_weight")

    return await _load_token(db, token_id)


@router.post("/{token_id}/second-weight", response_model=TokenResponse)
async def record_second_weight(
    token_id: uuid.UUID,
    payload: TokenSecondWeight,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    token = await _load_token(db, token_id)

    if token.status not in ("FIRST_WEIGHT", "LOADING"):
        raise HTTPException(400, f"Second weight requires FIRST_WEIGHT or LOADING status (current: {token.status})")

    token.second_weight = payload.weight_kg
    token.second_weight_at = datetime.now(timezone.utc)
    token.second_weight_by = current_user.id
    if payload.is_manual:
        token.is_manual_weight = True
    token.status = "SECOND_WEIGHT"

    _compute_weights(token)
    token.status = "COMPLETED"
    token.completed_at = datetime.now(timezone.utc)

    # Assign gap-free token_no NOW (at completion, not at creation)
    company, fy = await _get_company_and_fy(db)
    token.token_no = await _next_token_no(db, company.id, fy.id, token.token_date)

    # Auto-create a draft invoice for both sale and purchase tokens
    if token.token_type in ("sale", "purchase"):
        await _auto_create_invoice(db, token, company, fy, current_user.id,
                                   invoice_type=token.token_type)

    await db.commit()

    # Audit log — completed
    try:
        from app.routers.audit import log_action
        await log_action(db, company.id, current_user.id, "completed", "token",
                         str(token.id), {"token_no": token.token_no, "vehicle_no": token.vehicle_no,
                                         "net_weight": float(token.net_weight or 0)})
    except Exception:
        pass

    # ── Fire token_completed notification (background, non-blocking) ──────────
    # Capture tenant slug BEFORE dispatching background task
    _bg_tenant = None
    try:
        from app.multitenancy.context import current_tenant_slug
        _bg_tenant = current_tenant_slug.get()
    except Exception:
        pass

    _notify_ctx = {
        "token_no": token.token_no or "PENDING",
        "vehicle_no": token.vehicle_no or "—",
        "net_weight": f"{float(token.net_weight or 0) / 1000:.3f}",
        "completed_at": token.completed_at.strftime("%d-%m-%Y %H:%M") if token.completed_at else "—",
        "party_name": token.party.name if token.party else "—",
        "party_phone": token.party.phone or "" if token.party else "",
        "company_name": company.name,
    }
    background_tasks.add_task(
        _send_notification_bg,
        company.id, "token_completed", _notify_ctx, "token", str(token.id), _bg_tenant,
    )

    # Capture snapshot at 2nd weight for ALL token types
    from app.routers.cameras import trigger_snapshot_capture
    background_tasks.add_task(trigger_snapshot_capture, token_id, _bg_tenant, "second_weight")

    return await _load_token(db, token_id)


@router.post("/{token_id}/cancel", response_model=TokenResponse)
async def cancel_token(
    token_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "operator")),
):
    token = await _load_token(db, token_id)
    if token.status == "COMPLETED":
        raise HTTPException(400, "Cannot cancel a completed token. Create a credit note instead.")
    token.status = "CANCELLED"
    await db.commit()

    # Audit log
    try:
        from app.routers.audit import log_action
        company, _ = await _get_company_and_fy(db)
        await log_action(db, company.id, current_user.id, "cancel", "token",
                         str(token.id), {"vehicle_no": token.vehicle_no})
    except Exception:
        pass

    return await _load_token(db, token_id)


@router.post("/{token_id}/set-loading", response_model=TokenResponse)
async def set_loading(
    token_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark token as vehicle loading/unloading (optional intermediate status)."""
    token = await _load_token(db, token_id)
    if token.status != "FIRST_WEIGHT":
        raise HTTPException(400, "Can only set loading status after first weight")
    token.status = "LOADING"
    await db.commit()
    return await _load_token(db, token_id)


@router.get("/{token_id}/print", response_class=HTMLResponse)
async def print_token(
    token_id: uuid.UUID,
    format: str = Query("a4"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return an HTML weighment slip for printing. format=a4 (default) or thermal."""
    token = await _load_token(db, token_id)
    company, _ = await _get_company_and_fy(db)
    template = "token_thermal.html" if format == "thermal" else "token_a4.html"
    html = render_html(template, {"token": token, "company": company})
    return HTMLResponse(content=html)

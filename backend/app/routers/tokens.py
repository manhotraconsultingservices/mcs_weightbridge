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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from app.services import idempotency
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, text
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, require_role, get_current_branch_id
from app.models.token import Token
from app.models.settings import NumberSequence
from app.models.company import Company, FinancialYear
from app.models.party import Party, PartyRate
from app.models.product import Product
from app.models.vehicle import Vehicle, Driver, Transporter
from app.models.user import User
from app.schemas.token import (
    TokenCreate, TokenFirstWeight, TokenSecondWeight, TokenUpdate, TokenResponse,
    TokenListResponse, TokenVolumeCreate,
)
from app.utils.pdf_generator import render_html
from app.services.numbering import next_gate_pass_no

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


async def _check_royalty_unaccounted_bg(
    company_id: uuid.UUID,
    token_date,
    tenant_slug: str | None,
) -> None:
    """Background task: check unaccounted royalty MT after a purchase token completes."""
    import logging as _logging
    try:
        from app.database import get_tenant_session
        async with await get_tenant_session(tenant_slug) as db:
            from app.routers.royalty import check_royalty_unaccounted
            await check_royalty_unaccounted(db, company_id, token_date)
    except Exception as exc:
        _logging.getLogger(__name__).warning("Royalty unaccounted check failed: %s", exc)


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


async def _auto_consume_royalty_pass(db: AsyncSession, token: Token) -> None:
    """Non-blocking: if token has a transit_pass_id, draw net_weight against it.

    Called after second-weight completion / volume token creation.
    All errors are swallowed so token completion never fails due to a pass issue.
    net_weight is in kg; quantity_mt = net_weight / 1000.
    """
    try:
        if not token.transit_pass_id or not token.net_weight:
            return
        from app.models.royalty import RoyaltyPass, RoyaltyPassConsumption
        from sqlalchemy.orm import selectinload as _sl
        p = (await db.execute(
            select(RoyaltyPass).options(_sl(RoyaltyPass.consumptions))
            .where(RoyaltyPass.id == token.transit_pass_id)
        )).scalar_one_or_none()
        if not p or p.status == "cancelled":
            return
        net_mt = Decimal(str(token.net_weight)) / Decimal("1000")
        consumed_so_far = sum((c.quantity_mt or Decimal("0")) for c in p.consumptions)
        balance = (p.quantity_mt or Decimal("0")) - consumed_so_far
        # authorized = what the pass can still cover; actual = what the truck brought
        auth_mt = min(net_mt, balance) if balance > 0 else Decimal("0")
        variance_mt = net_mt - auth_mt  # >0 means overrun

        db.add(RoyaltyPassConsumption(
            pass_id=p.id,
            company_id=p.company_id,
            token_id=token.id,
            quantity_mt=net_mt,
            authorized_mt=auth_mt,
            actual_mt=net_mt,
            variance_mt=variance_mt,
            vehicle_no=token.vehicle_no,
            consumed_date=token.token_date,
            notes=f"Auto-draw at {'second weight' if token.weight_method == 'weighbridge' else 'volume token'}",
        ))
        new_consumed = consumed_so_far + net_mt
        if p.quantity_mt and new_consumed >= p.quantity_mt and p.status == "active":
            p.status = "exhausted"
    except Exception:
        pass  # never block token completion


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
                      product_id: uuid.UUID | None, unit: str | None = None) -> Decimal:
    """Unit-aware rate for a party+product+unit. Thin wrapper over the shared
    resolver (services/pricing.resolve_rate). `unit=None` → the product's base
    unit (legacy priority: party rate → product.default_rate → 0)."""
    from app.services.pricing import resolve_rate
    return await resolve_rate(db, party_id, product_id, unit)


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

    # Bill in the unit the operator chose for this truck (falls back to the
    # product's own unit for tokens created before per-unit billing).
    from app.services.pricing import token_quantity
    bill_unit = token.billing_unit or product.unit
    rate = await _fetch_rate(db, token.party_id, token.product_id, bill_unit)
    qty = token_quantity(token, bill_unit, product)

    amount = (qty * rate).quantize(Decimal("0.01"))
    gst_rate = product.gst_rate or Decimal("0")

    # GST calculation (intra-state assumed; will be recalculated if party state differs)
    from app.services.gst_service import calculate_invoice_totals, is_intra_state, party_place_of_supply
    from app.models.party import Party as PartyModel
    party = (await db.execute(select(PartyModel).where(PartyModel.id == token.party_id))).scalar_one_or_none()
    intra = is_intra_state(company.state_code, party_place_of_supply(party) if party else company.state_code)

    # Payment-mode drives the tax type (mirrors the manual invoice-create path):
    #   party.default_payment_mode == 'cash'  → non-GST Bill of Supply (no GST)
    #   party.default_payment_mode == 'online' (or unset) → GST invoice
    effective_tax_type = "non_gst" if (party and party.default_payment_mode == "cash") else "gst"

    items_data = [{
        "product_id": str(token.product_id),
        "description": product.name,
        "hsn_code": product.hsn_code,
        "quantity": qty,         # keep as Decimal — float() loses precision on .toFixed() boundary
        "unit": bill_unit,
        "rate": rate,            # Decimal
        "gst_rate": gst_rate,    # Decimal
        "sort_order": 0,
    }]
    totals = calculate_invoice_totals(
        items=items_data,
        discount_type=None,
        discount_value=Decimal("0"),
        freight=Decimal("0"),
        tcs_rate=Decimal("0"),
        intra_state=intra,
        tax_type=effective_tax_type,
    )

    from app.models.invoice import Invoice, InvoiceItem
    # Auto-fill driver name from token's driver relationship
    driver_name = None
    if token.driver_id:
        from app.models.vehicle import Driver
        driver = (await db.execute(select(Driver).where(Driver.id == token.driver_id))).scalar_one_or_none()
        if driver:
            driver_name = driver.name

    # Compute due_date from party's payment_terms_days (same logic as
    # the manual invoice-create path). Drives the overdue-customer alert.
    auto_due_date = token.token_date
    if party and getattr(party, "payment_terms_days", 0) and party.payment_terms_days > 0:
        from datetime import timedelta as _td
        auto_due_date = token.token_date + _td(days=int(party.payment_terms_days))

    invoice = Invoice(
        company_id=company.id,
        fy_id=fy.id,
        invoice_type=invoice_type,
        tax_type=effective_tax_type,
        invoice_no=None,          # assigned at finalise (gap-free)
        invoice_date=token.token_date,
        due_date=auto_due_date,
        party_id=token.party_id,
        token_id=token.id,
        agent_id=token.agent_id,   # carry broker/dalal → invoice for commission
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
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    branch_id=Depends(get_current_branch_id),
):
    company, fy = await _get_company_and_fy(db)

    # Idempotency (P1 #171): if this client op already applied, return the stored
    # token WITHOUT re-running any side effects (no gate-pass number burned, no
    # duplicate guard tripped). Sent online too, so this runs continuously.
    op_id = idempotency.get_op_id(request)
    origin = idempotency.get_origin(request)
    if op_id:
        prior = await idempotency.find_applied(db, company.id, op_id)
        if prior and prior.entity_id:
            return await _load_token(db, uuid.UUID(prior.entity_id))

    # Per-unit billing guard: a weighbridge (weighed) truck can only bill in a
    # weight unit — a volume unit (CFT/CBM/Brass) needs a volume-measured token.
    if payload.billing_unit:
        from app.services.pricing import validate_billing_unit
        validate_billing_unit(payload.billing_unit, "weighbridge")

    # Block if this vehicle already has an active (in-progress) weighbridge token.
    # Prevents 2 trucks with the same plate from being processed simultaneously.
    vno_upper = (payload.vehicle_no or "").upper().strip()
    if vno_upper:
        active_row = await db.execute(
            text("""
                SELECT id, token_no, status FROM tokens
                WHERE UPPER(vehicle_no) = :vno
                AND status NOT IN ('COMPLETED', 'CANCELLED')
                LIMIT 1
            """),
            {"vno": vno_upper},
        )
        active = active_row.fetchone()
        if active:
            label = active.token_no or f"(ID …{str(active.id)[-6:]})"
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Vehicle {vno_upper} already has an active token {label} "
                    f"(status: {active.status}). Complete or cancel it before creating a new one."
                ),
            )

    # Determine gate_pass_no:
    # If a gate_pass_id is supplied (guard pre-created a pass), use that record's GP
    # number and link back. Otherwise auto-generate from number_sequences — this is the
    # backward-compatible path for deployments not using the Gate Register workflow.
    if not payload.gate_pass_id:
        resolved_gate_pass_no = await next_gate_pass_no(db, company.id, fy.id, branch_id)
    else:
        gp_row = await db.execute(
            text("SELECT gate_pass_no, token_id, status FROM gate_passes WHERE id = :id"),
            {"id": str(payload.gate_pass_id)},
        )
        gp = gp_row.fetchone()
        if not gp:
            raise HTTPException(status_code=404, detail="Gate pass not found. Create a gate pass first from the Gate Register.")
        if gp.status == "cancelled":
            raise HTTPException(status_code=409, detail="Gate pass is cancelled. Create a new gate pass for this truck.")
        if gp.token_id:
            # If the linked token was cancelled, auto-unlink so this gate pass can be reused
            linked_row = await db.execute(
                text("SELECT status FROM tokens WHERE id = :tid"),
                {"tid": str(gp.token_id)},
            )
            linked = linked_row.fetchone()
            if linked and linked.status == "CANCELLED":
                await db.execute(
                    text("UPDATE gate_passes SET token_id = NULL, updated_at = NOW() WHERE id = :id"),
                    {"id": str(payload.gate_pass_id)},
                )
            else:
                raise HTTPException(status_code=409, detail="Gate pass already linked to another token. Select a different gate pass.")
        resolved_gate_pass_no = gp.gate_pass_no

    token = Token(
        # A replayed offline token keeps the id it was given locally, so its
        # weighments (which target /tokens/{id}) need no id substitution.
        id=(payload.id if (op_id and payload.id) else uuid.uuid4()),
        client_op_id=op_id,
        origin=origin if op_id else "online",
        company_id=company.id,
        branch_id=branch_id,
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
        tyre_count=payload.tyre_count,
        driver_id=payload.driver_id,
        transporter_id=payload.transporter_id,
        agent_id=payload.agent_id,
        billing_unit=payload.billing_unit,
        gate_pass=payload.gate_pass,
        gate_pass_no=resolved_gate_pass_no,
        transit_pass_id=payload.transit_pass_id,
        vehicle_rent=payload.vehicle_rent,
        remarks=payload.remarks,
        custom_fields=payload.custom_fields,
        created_by=current_user.id,
        status="OPEN",
    )
    db.add(token)
    try:
        await db.flush()  # get token.id before commit; ux_tokens_client_op guards races
    except IntegrityError:
        # A concurrent replay of the same op won the race — return its token.
        await db.rollback()
        if op_id:
            prior = await idempotency.find_applied(db, company.id, op_id)
            if prior and prior.entity_id:
                return await _load_token(db, uuid.UUID(prior.entity_id))
        raise

    # If linked to a gate pass record, stamp token_id on it in the same transaction
    if payload.gate_pass_id:
        await db.execute(
            text("UPDATE gate_passes SET token_id = :tid, updated_at = NOW() WHERE id = :id"),
            {"tid": str(token.id), "id": str(payload.gate_pass_id)},
        )

    # Idempotency ledger, in the SAME transaction as the token row.
    if op_id:
        await idempotency.record_operation(
            db, company_id=company.id, op_id=op_id, op_type="token.create",
            entity_type="token", entity_id=token.id,
            assigned={"id": str(token.id), "gate_pass_no": token.gate_pass_no},
            user_id=current_user.id, origin=origin,
        )

    await db.commit()

    # Audit log
    try:
        from app.routers.audit import log_action
        await log_action(db, company.id, current_user.id, "create", "token",
                         str(token.id), {"vehicle_no": token.vehicle_no, "type": token.token_type})
    except Exception:
        pass

    return await _load_token(db, token.id)


@router.post("/volume", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def create_volume_token(
    payload: TokenVolumeCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    branch_id=Depends(get_current_branch_id),
):
    """
    Volume-based token: load measured by volume (CFT) rather than the weighbridge.

    Truck does not go on the bridge. net_weight is computed from
        weight_kg = volume_cft × bulk_density(kg/CFT)
    and the token jumps directly to COMPLETED. Same auto-invoice + notification
    flow fires as for a normal second-weight completion.
    """
    if payload.volume_cft <= 0:
        raise HTTPException(400, "volume_cft must be greater than zero")

    company, fy = await _get_company_and_fy(db)

    # Block if this vehicle already has an active (in-progress) token.
    vno_upper_v = (payload.vehicle_no or "").upper().strip()
    if vno_upper_v:
        active_row_v = await db.execute(
            text("""
                SELECT id, token_no, status FROM tokens
                WHERE UPPER(vehicle_no) = :vno
                AND status NOT IN ('COMPLETED', 'CANCELLED')
                LIMIT 1
            """),
            {"vno": vno_upper_v},
        )
        active_v = active_row_v.fetchone()
        if active_v:
            label_v = active_v.token_no or f"(ID …{str(active_v.id)[-6:]})"
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Vehicle {vno_upper_v} already has an active token {label_v} "
                    f"(status: {active_v.status}). Complete or cancel it before creating a new one."
                ),
            )

    product = (await db.execute(
        select(Product).where(Product.id == payload.product_id)
    )).scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    if not product.bulk_density or product.bulk_density <= 0:
        raise HTTPException(
            400,
            f"Bulk density (kg/CFT) is not set for product '{product.name}'. "
            f"Set it on the product before using volume-based tokens.",
        )

    # weight_kg = volume_cft × bulk_density(kg/CFT)
    net_kg = (payload.volume_cft * product.bulk_density).quantize(Decimal("0.01"))

    # Resolve gate pass number — link to an existing guard-created pass if supplied,
    # otherwise auto-generate from number_sequences (backward-compat / no Gate Register).
    if not payload.gate_pass_id:
        resolved_vol_gate_pass_no = await next_gate_pass_no(db, company.id, fy.id, branch_id)
    else:
        vgp_row = await db.execute(
            text("SELECT gate_pass_no, token_id, status FROM gate_passes WHERE id = :id AND company_id = :cid"),
            {"id": str(payload.gate_pass_id), "cid": str(company.id)},
        )
        vgp = vgp_row.fetchone()
        if not vgp:
            raise HTTPException(status_code=404, detail="Gate pass not found.")
        if vgp.status == "cancelled":
            raise HTTPException(status_code=409, detail="Gate pass is cancelled. Create a new gate pass for this truck.")
        if vgp.token_id:
            linked_row2 = await db.execute(
                text("SELECT status FROM tokens WHERE id = :tid"),
                {"tid": str(vgp.token_id)},
            )
            linked2 = linked_row2.fetchone()
            if linked2 and linked2.status == "CANCELLED":
                await db.execute(
                    text("UPDATE gate_passes SET token_id = NULL, updated_at = NOW() WHERE id = :id AND company_id = :cid"),
                    {"id": str(payload.gate_pass_id), "cid": str(company.id)},
                )
            else:
                raise HTTPException(status_code=409, detail="Gate pass already linked to another token. Select a different gate pass.")
        resolved_vol_gate_pass_no = vgp.gate_pass_no

    token = Token(
        company_id=company.id,
        branch_id=branch_id,
        fy_id=fy.id,
        token_no=await _next_token_no(db, company.id, fy.id, payload.token_date),
        token_date=payload.token_date,
        direction=payload.direction,
        token_type=payload.token_type,
        party_id=payload.party_id,
        product_id=payload.product_id,
        vehicle_no=payload.vehicle_no.upper().strip(),
        vehicle_id=payload.vehicle_id,
        vehicle_type=payload.vehicle_type,
        tyre_count=payload.tyre_count,
        driver_id=payload.driver_id,
        transporter_id=payload.transporter_id,
        agent_id=payload.agent_id,
        billing_unit=payload.billing_unit,
        gate_pass=payload.gate_pass,
        gate_pass_no=resolved_vol_gate_pass_no,
        transit_pass_id=payload.transit_pass_id,
        vehicle_rent=payload.vehicle_rent,
        remarks=payload.remarks,
        custom_fields=payload.custom_fields,
        created_by=current_user.id,
        status="COMPLETED",
        completed_at=datetime.now(timezone.utc),
        # Weight: only net is recorded (no gross/tare since there's no bridge reading)
        gross_weight=None,
        tare_weight=None,
        net_weight=net_kg,
        weight_method="volume",
        volume_cft=payload.volume_cft,
        is_manual_weight=True,
    )
    db.add(token)
    await db.flush()

    # Link gate pass record if supplied (same-transaction)
    if payload.gate_pass_id:
        await db.execute(
            text("UPDATE gate_passes SET token_id = :tid, updated_at = NOW() WHERE id = :id AND company_id = :cid"),
            {"tid": str(token.id), "id": str(payload.gate_pass_id), "cid": str(company.id)},
        )

    # Auto-create draft invoice — identical flow to second-weight completion
    if token.token_type in ("sale", "purchase"):
        await _auto_create_invoice(db, token, company, fy, current_user.id,
                                   invoice_type=token.token_type)

    # P1: Auto-draw against the linked transit/royalty pass (non-blocking)
    await _auto_consume_royalty_pass(db, token)

    await db.commit()

    # Audit log
    try:
        from app.routers.audit import log_action
        await log_action(db, company.id, current_user.id, "completed", "token",
                         str(token.id), {"token_no": token.token_no, "vehicle_no": token.vehicle_no,
                                         "method": "volume", "volume_cft": float(payload.volume_cft),
                                         "net_kg": float(net_kg)})
    except Exception:
        pass

    # Token-completed notification (background, non-blocking) — same shape as second-weight path
    _bg_tenant = None
    try:
        from app.multitenancy.context import current_tenant_slug
        _bg_tenant = current_tenant_slug.get()
    except Exception:
        pass

    # Fetch party name for the notification context
    party = (await db.execute(select(Party).where(Party.id == token.party_id))).scalar_one_or_none()
    _notify_ctx = {
        "token_no": token.token_no or "PENDING",
        "vehicle_no": token.vehicle_no or "—",
        "net_weight": f"{float(net_kg) / 1000:.3f}",
        "completed_at": token.completed_at.strftime("%d-%m-%Y %H:%M") if token.completed_at else "—",
        "party_name": party.name if party else "—",
        "party_phone": party.phone or "" if party else "",
        "company_name": company.name,
    }
    background_tasks.add_task(
        _send_notification_bg,
        company.id, "token_completed", _notify_ctx, "token", str(token.id), _bg_tenant,
    )

    # Royalty unaccounted-MT alert (purchase volume tokens; non-blocking)
    if payload.token_type == "purchase":
        background_tasks.add_task(
            _check_royalty_unaccounted_bg,
            company.id, token.token_date, _bg_tenant,
        )

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
    branch_id=Depends(get_current_branch_id),
):
    company, fy = await _get_company_and_fy(db)

    filters = [Token.company_id == company.id, Token.is_supplement == False]
    if branch_id is not None:
        filters.append(Token.branch_id == branch_id)   # None = all/default branch
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


@router.get("/last-by-vehicle/{vehicle_no}")
async def last_by_vehicle(
    vehicle_no: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Smart-suggest for kiosk: returns the most recent COMPLETED token for this
    plate so we can offer 'Same as last time?'. Returns null if unseen.

    Response shape (or `null` if no match):
      { token_type, party: {id, name}, product: {id, name, unit, bulk_density},
        vehicle_type, tare_weight, last_seen_date }
    """
    company, _ = await _get_company_and_fy(db)
    plate = vehicle_no.upper().strip()
    if not plate:
        return None

    last = (await db.execute(
        select(Token)
        .options(selectinload(Token.party), selectinload(Token.product))
        .where(
            Token.company_id == company.id,
            Token.vehicle_no == plate,
            Token.status == "COMPLETED",
            Token.is_supplement == False,
        )
        .order_by(Token.completed_at.desc().nulls_last(), Token.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if not last:
        return None

    return {
        "token_type": last.token_type,
        "vehicle_type": last.vehicle_type,
        "tare_weight": float(last.tare_weight) if last.tare_weight is not None else None,
        "party": {
            "id": str(last.party.id),
            "name": last.party.name,
        } if last.party else None,
        "product": {
            "id": str(last.product.id),
            "name": last.product.name,
            "unit": last.product.unit,
            "bulk_density": float(last.product.bulk_density) if last.product.bulk_density is not None else None,
        } if last.product else None,
        "last_seen_date": last.completed_at.date().isoformat() if last.completed_at else last.token_date.isoformat(),
    }


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
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    token = await _load_token(db, token_id)

    # Idempotency (P1 #171): a replayed first-weight returns the token unchanged
    # instead of tripping the OPEN-only guard below (which would otherwise falsely
    # park a successfully-applied weighment as needs_review on the edge). Sent
    # online too, so the dedupe path runs continuously in production.
    op_id = idempotency.get_op_id(request)
    origin = idempotency.get_origin(request)
    company = None
    if op_id:
        company, _ = await _get_company_and_fy(db)
        prior = await idempotency.find_applied(db, company.id, op_id)
        if prior:
            return await _load_token(db, token_id)

    if token.status != "OPEN":
        raise HTTPException(400, f"First weight can only be recorded on OPEN tokens (current: {token.status})")

    token.first_weight = payload.weight_kg
    token.first_weight_at = datetime.now(timezone.utc)
    token.first_weight_by = current_user.id
    token.is_manual_weight = payload.is_manual
    token.status = "FIRST_WEIGHT"

    # Sale: first weight is the empty truck (tare). Purchase: first weight is the loaded truck (gross).
    token.first_weight_type = "tare" if token.token_type == "sale" else "gross"

    # Idempotency ledger, in the SAME transaction as the weight mutation.
    if op_id:
        await idempotency.record_operation(
            db, company_id=company.id, op_id=op_id, op_type="token.first_weight",
            entity_type="token", entity_id=token.id,
            assigned={"id": str(token.id), "status": token.status},
            user_id=current_user.id, origin=origin,
        )

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
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    token = await _load_token(db, token_id)

    # Idempotency (P1 #171): a replayed second-weight returns the already-completed
    # token (with its assigned token_no + auto-invoice intact) instead of tripping
    # the FIRST_WEIGHT/LOADING-only guard or double-creating an invoice.
    op_id = idempotency.get_op_id(request)
    origin = idempotency.get_origin(request)
    if op_id:
        _co, _ = await _get_company_and_fy(db)
        prior = await idempotency.find_applied(db, _co.id, op_id)
        if prior:
            return await _load_token(db, token_id)

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

    # P1: Auto-draw against the linked transit/royalty pass (non-blocking)
    await _auto_consume_royalty_pass(db, token)

    # Idempotency ledger, in the SAME transaction as the completion + auto-invoice.
    if op_id:
        await idempotency.record_operation(
            db, company_id=company.id, op_id=op_id, op_type="token.second_weight",
            entity_type="token", entity_id=token.id,
            assigned={"id": str(token.id), "token_no": token.token_no, "status": token.status},
            user_id=current_user.id, origin=origin,
        )

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

    # Royalty unaccounted-MT alert (purchase tokens only; non-blocking)
    if token.token_type == "purchase":
        background_tasks.add_task(
            _check_royalty_unaccounted_bg,
            company.id, token.token_date, _bg_tenant,
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
    # Unlink any gate pass linked to this token so it becomes available for a new token
    await db.execute(
        text("UPDATE gate_passes SET token_id = NULL, updated_at = NOW() WHERE token_id = :tid"),
        {"tid": str(token_id)},
    )
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
    from app.routers.app_settings import VOLUME_UNIT_KEY, _get_raw
    from app.models.invoice import Invoice, InvoiceItem
    from app.models.royalty import RoyaltyPassConsumption, RoyaltyPass
    token = await _load_token(db, token_id)
    company, _ = await _get_company_and_fy(db)
    volume_unit = (await _get_raw(db, VOLUME_UNIT_KEY)) or "cft"

    # Prefer rate/amount from the linked invoice's line item
    rate: float = 0.0
    amount: float | None = None
    grand_total: float | None = None
    inv_row = (await db.execute(
        select(Invoice.id, Invoice.grand_total)
        .where(Invoice.token_id == token_id, Invoice.status != "cancelled")
        .order_by(Invoice.created_at.desc())
        .limit(1)
    )).first()
    if inv_row:
        grand_total = float(inv_row.grand_total) if inv_row.grand_total else None
        item_row = (await db.execute(
            select(InvoiceItem.rate, InvoiceItem.amount)
            .where(InvoiceItem.invoice_id == inv_row.id)
            .limit(1)
        )).first()
        if item_row:
            rate = float(item_row.rate)
            amount = float(item_row.amount)

    # Fallback: derive from unit-aware party_rates / product.default_rate
    if rate == 0.0:
        from app.models.product import Product as _Prod
        _prod = (await db.execute(select(_Prod).where(_Prod.id == token.product_id))).scalar_one_or_none() if token.product_id else None
        _bunit = token.billing_unit or (_prod.unit if _prod else None)
        fetched = await _fetch_rate(db, token.party_id, token.product_id, _bunit)
        rate = float(fetched)
        if rate > 0 and _prod:
            from app.services.pricing import token_quantity
            amount = rate * float(token_quantity(token, _bunit, _prod))

    # Royalty: look up the consumption linked to this token
    royalty_amount: float = 0.0
    royalty_per_mt: float = 0.0
    royalty_row = (await db.execute(
        select(RoyaltyPassConsumption.quantity_mt, RoyaltyPass.rate)
        .join(RoyaltyPass, RoyaltyPassConsumption.pass_id == RoyaltyPass.id)
        .where(RoyaltyPassConsumption.token_id == token_id)
        .limit(1)
    )).first()
    if royalty_row:
        royalty_per_mt = float(royalty_row.rate)
        royalty_amount = float(royalty_row.quantity_mt) * royalty_per_mt

    vehicle_rent = float(token.vehicle_rent or 0)
    total_amount = (amount or 0) + royalty_amount + vehicle_rent

    # Owner-defined custom attributes flagged to print on the slip (e.g. Moisture %)
    slip_custom_fields: list[dict] = []
    try:
        from app.models.custom_field import CustomFieldDefinition
        defs = (await db.execute(
            select(CustomFieldDefinition)
            .where(
                CustomFieldDefinition.company_id == company.id,
                CustomFieldDefinition.entity_type == "token",
                CustomFieldDefinition.show_on_slip.is_(True),
                CustomFieldDefinition.is_active.is_(True),
            )
            .order_by(CustomFieldDefinition.sort_order, CustomFieldDefinition.label)
        )).scalars().all()
        cf = token.custom_fields or {}
        for d in defs:
            v = cf.get(d.field_key)
            if v is None or v == "":
                continue
            slip_custom_fields.append({
                "label": d.label,
                "value": f"{v}{(' ' + d.unit) if d.unit else ''}",
            })
    except Exception:
        slip_custom_fields = []

    template = "token_thermal.html" if format == "thermal" else "token_a4.html"
    html = render_html(template, {
        "token": token,
        "company": company,
        "volume_unit": volume_unit,
        "rate": rate,
        "amount": amount,
        "grand_total": grand_total,
        "royalty_amount": royalty_amount,
        "royalty_per_mt": royalty_per_mt,
        "vehicle_rent": vehicle_rent,
        "total_amount": total_amount,
        "slip_custom_fields": slip_custom_fields,
    })
    return HTMLResponse(content=html)

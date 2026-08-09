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
from pydantic import BaseModel
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
    Generate a random 4-digit token number (1000–8999) that is unique for the day.

    Random numbering is intentional: when tokens are moved to Supplement they are
    removed from the visible list. Sequential numbering would leave obvious gaps
    (e.g. 1, 2, 4, 5 — where did 3 go?). Random numbers make gaps meaningless
    and reveal nothing about hidden entries.

    The top band **9000–9999 is RESERVED for offline edge terminals** (P1 #172):
    an offline terminal mints its own token_no in that band and prints it on the
    slip, and the server keeps that number verbatim at sync (see
    record_second_weight). Drawing online numbers from 1000–8999 makes the two
    spaces structurally non-overlapping, so no coordination is needed.

    Collision probability is negligible for typical daily volumes (<100 tokens)
    against an 8000-value space. Falls back to 5-digit range if somehow exhausted.
    """
    for _ in range(50):
        candidate = random.randint(1000, 8999)
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


async def _token_no_is_free(db: AsyncSession, company_id: uuid.UUID, token_date: date,
                            token_no: int, self_id: uuid.UUID) -> bool:
    """True if `token_no` is unused for this company+day (ignoring the token
    itself). Backstop for #172 — lets the server keep an offline slip number when
    it doesn't clash, and reassign when it does."""
    row = await db.execute(
        select(Token.id).where(and_(
            Token.company_id == company_id,
            Token.token_date == token_date,
            Token.token_no == token_no,
            Token.id != self_id,
        )).limit(1)
    )
    return row.scalar_one_or_none() is None


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


async def _build_token_notify_ctx(db: AsyncSession, token: Token, company: Company) -> dict:
    """Build the token_completed notification context — material, qty, party, and
    the billed amount (incl royalty + vehicle rent), with the completion time in
    IST. Amount comes from the linked draft invoice's grand_total (which already
    folds in GST + royalty + vehicle_rent); '—' when the token has no invoice."""
    from app.utils.timefmt import fmt_ist
    from app.models.invoice import Invoice, InvoiceItem
    party = (await db.execute(select(Party).where(Party.id == token.party_id))).scalar_one_or_none() if token.party_id else None
    product = (await db.execute(select(Product).where(Product.id == token.product_id))).scalar_one_or_none() if token.product_id else None
    bill_unit = token.billing_unit or (product.unit if product else "MT")
    qty_str = None
    if product:
        try:
            from app.services.pricing import token_quantity
            q = token_quantity(token, bill_unit, product)
            if q is not None:
                qty_str = f"{float(q):g} {bill_unit}"
        except Exception:
            qty_str = None
    if qty_str is None:
        qty_str = f"{float(token.net_weight or 0) / 1000:.3f} MT"
    inv = (await db.execute(
        select(Invoice).where(
            Invoice.token_id == token.id,
            Invoice.invoice_type.in_(("sale", "purchase")),
        ).order_by(Invoice.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    amount = inv.grand_total if inv else None
    # ₹/unit rate — prefer the linked invoice's line rate (authoritative), else the
    # operator-set token.rate; labelled with the billing unit shown in qty.
    rate_val = None
    if inv:
        _r = (await db.execute(
            select(InvoiceItem.rate).where(InvoiceItem.invoice_id == inv.id).limit(1)
        )).scalar_one_or_none()
        if _r is not None:
            rate_val = float(_r)
    if rate_val is None and token.rate is not None:
        rate_val = float(token.rate)
    royalty = float(token.royalty_amount or 0)
    rent = float(token.vehicle_rent or 0)
    # Buy/Sell so the owner can tell inbound (purchase) from outbound (sale) at a
    # glance — same wording as the printed slip (sale→Sell, purchase→Buy).
    _type_label = {"sale": "Sell (Sale)", "purchase": "Buy (Purchase)"}
    token_type_label = _type_label.get(token.token_type, (token.token_type or "—").capitalize())
    return {
        "token_no": token.token_no or "PENDING",
        "token_type": token_type_label,
        "vehicle_no": token.vehicle_no or "—",
        "net_weight": f"{float(token.net_weight or 0) / 1000:.3f}",  # legacy templates
        "completed_at": fmt_ist(token.completed_at),
        "party_name": party.name if party else "—",
        "party_phone": (party.phone or "") if party else "",
        "material": product.name if product else "—",
        "qty": qty_str,
        "rate": f"{rate_val:,.2f}/{bill_unit}" if rate_val is not None and rate_val > 0 else "",
        "amount": f"{float(amount):,.2f}" if amount is not None else "—",
        "royalty": f"{royalty:,.2f}" if royalty > 0 else "",
        "vehicle_rent": f"{rent:,.2f}" if rent > 0 else "",
        "company_name": company.name,
    }


async def _build_vehicle_move_ctx(db: AsyncSession, token: Token, company: Company, direction: str) -> dict:
    """Context for the vehicle_in / vehicle_out movement alerts — vehicle, party,
    material, Buy/Sell, gate pass, and the movement time in IST. Deliberately
    lightweight (no invoice/amount lookup) so it works for a freshly-created OPEN
    token at arrival, not only at completion. `direction`: 'in' → uses created_at,
    'out' → uses completed_at."""
    from app.utils.timefmt import fmt_ist
    party = (await db.execute(select(Party).where(Party.id == token.party_id))).scalar_one_or_none() if token.party_id else None
    product = (await db.execute(select(Product).where(Product.id == token.product_id))).scalar_one_or_none() if token.product_id else None
    _type_label = {"sale": "Sell (Sale)", "purchase": "Buy (Purchase)"}
    when = token.completed_at if direction == "out" else token.created_at
    return {
        "token_no": token.token_no or "PENDING",
        "token_type": _type_label.get(token.token_type, (token.token_type or "").capitalize()),
        "vehicle_no": token.vehicle_no or "—",
        "gate_pass_no": token.gate_pass_no or "",
        "party_name": party.name if party else "—",
        "material": product.name if product else "—",
        "time": fmt_ist(when),
        "company_name": company.name,
    }


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


async def _compute_vehicle_rent(db: AsyncSession, token: Token, net_kg) -> Decimal | None:
    """Auto vehicle rent = rate × distance_km × quantity, where the basis follows the
    load's measurement:
      • volume (CUB) load  → ₹/km/CUM rate × km × CUM (CUM = volume_cft / 35.3147)
      • weighed (MT) load  → ₹/km/MT  rate × km × net_MT
    The rate is the operator's per-token override (prefilled from the vehicle master
    on the token form) and falls back to the vehicle master when the token carries
    none. Returns None (→ leave rent as-is / manual) unless a distance AND an
    applicable rate are present. Net weight is known at completion (weighbridge) or
    at create (volume)."""
    if token.rent_km is None:
        return None
    from app.models.vehicle import Vehicle
    veh = None
    if token.vehicle_id:
        veh = (await db.execute(select(Vehicle).where(Vehicle.id == token.vehicle_id))).scalar_one_or_none()
    km = Decimal(str(token.rent_km))
    if token.weight_method == "volume":
        rate = token.rent_rate_per_km_per_cum
        if rate is None and veh is not None:
            rate = veh.rent_rate_per_km_per_cum
        if rate is None or not token.volume_cft:
            return None
        cum = Decimal(str(token.volume_cft)) / _CFT_PER_CUM
        return (Decimal(str(rate)) * km * cum).quantize(Decimal("0.01"))
    # Weighbridge / MT basis
    rate = token.rent_rate_per_km_per_mt
    if rate is None and veh is not None:
        rate = veh.rent_rate_per_km_per_mt
    if rate is None:
        return None
    net_mt = Decimal(str(net_kg or 0)) / Decimal("1000")
    return (Decimal(str(rate)) * km * net_mt).quantize(Decimal("0.01"))


# 1 cubic metre = 35.3147 cubic feet (canonical volume unit is CFT).
_CFT_PER_CUM = Decimal("35.3147")


async def _compute_royalty(db: AsyncSession, token: Token) -> Decimal | None:
    """Auto royalty, charged either per MT or per CUM depending on the token's
    ``royalty_unit`` (which follows the token's measurement — weighed → 'mt',
    volume → 'cum'):

      • unit='mt'  → product.royalty_per_mt  × net_weight (MT)
      • unit='cum' → product.royalty_per_cum × royalty_cum (cubic metres); the CUM
        is auto-derived from volume_cft for a volume token when not supplied.

    Returns None (→ leave royalty as-is / not applied) unless royalty was opted in
    (royalty_unit set, or a legacy token carrying royalty_cum) AND the product has
    the matching ₹-rate. royalty_cum is stamped for the CUM basis.
    """
    if not token.product_id:
        return None
    # Determine the basis. NULL royalty_unit → infer: legacy royalty_cum ⇒ cum,
    # else the token's measurement (volume ⇒ cum, weighed ⇒ mt). None ⇒ not opted in.
    unit = (token.royalty_unit or "").lower() or None
    if unit is None:
        if token.royalty_cum is not None:
            unit = "cum"
        else:
            return None
    prod = (await db.execute(select(Product).where(Product.id == token.product_id))).scalar_one_or_none()
    if not prod:
        return None
    # Operator's per-unit rate override wins; else the product master rate for the unit.
    if unit == "mt":
        rate = token.royalty_rate if token.royalty_rate is not None else prod.royalty_per_mt
        if rate is None:
            return None
        qty_mt = Decimal(str(token.net_weight or 0)) / Decimal("1000")
        return (Decimal(str(rate)) * qty_mt).quantize(Decimal("0.01"))
    # CUM basis
    rate = token.royalty_rate if token.royalty_rate is not None else prod.royalty_per_cum
    if rate is None:
        return None
    cum = token.royalty_cum
    if cum is None and token.weight_method == "volume" and token.volume_cft:
        cum = (Decimal(str(token.volume_cft)) / _CFT_PER_CUM).quantize(Decimal("0.001"))
        token.royalty_cum = cum
    if cum is None:
        return None
    return (Decimal(str(rate)) * Decimal(str(cum))).quantize(Decimal("0.01"))


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
    # Operator-set price wins (shown/edited on the token); else resolve customer/default rate.
    rate = token.rate if token.rate is not None else await _fetch_rate(db, token.party_id, token.product_id, bill_unit)
    qty = token_quantity(token, bill_unit, product)

    amount = (qty * rate).quantize(Decimal("0.01"))
    gst_rate = product.gst_rate or Decimal("0")

    # GST calculation (intra-state assumed; will be recalculated if party state differs)
    from app.services.gst_service import calculate_invoice_totals, is_intra_state, party_place_of_supply
    from app.models.party import Party as PartyModel
    party = (await db.execute(select(PartyModel).where(PartyModel.id == token.party_id))).scalar_one_or_none()
    intra = is_intra_state(company.state_code, party_place_of_supply(party) if party else company.state_code)

    # Payment mode → tax type. The operator's per-token choice (cash → non-GST
    # Bill of Supply; credit/upi/bank → GST) OVERRIDES the party default; falls
    # back to party.default_payment_mode when the operator didn't pick one.
    tok_mode = (token.payment_mode or "").lower()
    if tok_mode:
        effective_tax_type = "non_gst" if tok_mode == "cash" else "gst"
    else:
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
        vehicle_rent=token.vehicle_rent or Decimal("0"),   # transport rent → billed to customer
        royalty=token.royalty_amount or Decimal("0"),      # govt royalty → billed to customer
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
        payment_mode=token.payment_mode,   # operator-chosen mode carried to the invoice
        created_by=user_id,
        vehicle_rent=token.vehicle_rent or Decimal("0"),   # transport rent → billed (in grand_total)
        royalty_amount=token.royalty_amount or Decimal("0"),  # royalty → billed (in grand_total)
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

    # Baseline snapshot for the draft→final diff (#205) — the finalize Telegram
    # then reports what the operator changed between drafting and finalising.
    # Built inline (the invoice's items/party relationships aren't loaded here)
    # to mirror invoice_to_snapshot()'s shape. Best-effort; never blocks.
    try:
        def _mt(v):
            return round(float(v) / 1000, 3) if v else None
        invoice.draft_snapshot = {
            "tax_type": invoice.tax_type,
            "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "party": {"id": str(party.id), "name": party.name, "gstin": party.gstin} if party else None,
            "customer_name": invoice.customer_name,
            "vehicle_no": invoice.vehicle_no,
            "transporter_name": invoice.transporter_name,
            "gross_weight": _mt(invoice.gross_weight),
            "tare_weight": _mt(invoice.tare_weight),
            "net_weight": _mt(invoice.net_weight),
            "payment_mode": invoice.payment_mode,
            "notes": invoice.notes,
            "subtotal": float(invoice.subtotal or 0),
            "discount_amount": float(invoice.discount_amount or 0),
            "taxable_amount": float(invoice.taxable_amount or 0),
            "cgst_amount": float(invoice.cgst_amount or 0),
            "sgst_amount": float(invoice.sgst_amount or 0),
            "igst_amount": float(invoice.igst_amount or 0),
            "tcs_amount": float(getattr(invoice, "tcs_amount", 0) or 0),
            "freight": float(invoice.freight or 0),
            "round_off": float(invoice.round_off or 0),
            "grand_total": float(invoice.grand_total or 0),
            "items": [
                {
                    "product_id": str(it["product_id"]),
                    "description": it.get("description"),
                    "hsn_code": it.get("hsn_code"),
                    "quantity": float(it["quantity"]),
                    "unit": it["unit"],
                    "rate": float(it["rate"]),
                    "gst_rate": float(it.get("gst_rate", 0)),
                    "total_amount": float(it["total_amount"]),
                }
                for it in totals["computed_items"]
            ],
        }
    except Exception:  # noqa: BLE001 — snapshot is best-effort, never blocks the invoice
        pass


# ------------------------------------------------------------------ #
# Endpoints
# ------------------------------------------------------------------ #

@router.post("", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def create_token(
    payload: TokenCreate,
    request: Request,
    background_tasks: BackgroundTasks,
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
        if op_id and origin == "edge" and payload.gate_pass_no:
            # #172: keep the gate-pass number printed on the offline slip.
            resolved_gate_pass_no = payload.gate_pass_no
        elif payload.token_type == "purchase":
            # Gate pass is OPTIONAL for purchase (inbound) tokens — don't auto-issue
            # one; honour an explicitly-supplied number, else leave it unset.
            resolved_gate_pass_no = payload.gate_pass_no or None
        else:
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
        rate=payload.rate,                    # operator-set material price (₹/unit); NULL → resolver at invoicing
        payment_mode=payload.payment_mode,    # operator-chosen mode → drives invoice tax_type (cash → Bill of Supply)
        gate_pass=payload.gate_pass,
        gate_pass_no=resolved_gate_pass_no,
        transit_pass_id=payload.transit_pass_id,
        vehicle_rent=payload.vehicle_rent,
        rent_km=payload.rent_km,              # distance → vehicle_rent auto-computed (Rate × Km × qty)
        destination=(payload.destination or None),   # trip destination shown with the km
        rent_rate_per_km_per_mt=payload.rent_rate_per_km_per_mt,    # operator override (else vehicle master)
        rent_rate_per_km_per_cum=payload.rent_rate_per_km_per_cum,  # operator override (else vehicle master)
        royalty_cum=payload.royalty_cum,      # CUM for royalty → royalty_amount computed at completion
        royalty_unit=payload.royalty_unit,    # 'mt' (× net weight) | 'cum' (× royalty_cum); NULL = no royalty
        royalty_rate=payload.royalty_rate,    # operator ₹/unit override (else product master rate for the unit)
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

    # Vehicle-In movement alert (background, non-blocking) — the truck has arrived.
    # Only for a real arrival: skip an edge replay (already applied earlier) so a
    # sync doesn't re-announce, and skip the volume path (that fires its own in/out).
    try:
        _bg_tenant = None
        try:
            from app.multitenancy.context import current_tenant_slug
            _bg_tenant = current_tenant_slug.get()
        except Exception:
            pass
        _move_ctx = await _build_vehicle_move_ctx(db, token, company, "in")
        background_tasks.add_task(
            _send_notification_bg,
            company.id, "vehicle_in", _move_ctx, "token", str(token.id), _bg_tenant,
        )
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
        # Gate pass is OPTIONAL for purchase (inbound) tokens — don't auto-issue one.
        resolved_vol_gate_pass_no = None if payload.token_type == "purchase" else await next_gate_pass_no(db, company.id, fy.id, branch_id)
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
        rate=payload.rate,                    # operator-set material price (₹/unit); NULL → resolver at invoicing
        payment_mode=payload.payment_mode,    # operator-chosen mode → drives invoice tax_type (cash → Bill of Supply)
        gate_pass=payload.gate_pass,
        gate_pass_no=resolved_vol_gate_pass_no,
        transit_pass_id=payload.transit_pass_id,
        vehicle_rent=payload.vehicle_rent,
        rent_km=payload.rent_km,              # distance → vehicle_rent auto-computed (Rate × Km × qty)
        destination=(payload.destination or None),   # trip destination shown with the km
        rent_rate_per_km_per_mt=payload.rent_rate_per_km_per_mt,    # operator override (else vehicle master)
        rent_rate_per_km_per_cum=payload.rent_rate_per_km_per_cum,  # operator override (else vehicle master)
        royalty_cum=payload.royalty_cum,      # CUM for royalty (auto-derived from volume if omitted)
        royalty_unit=payload.royalty_unit,    # 'mt' | 'cum' — royalty basis (volume tokens → cum)
        royalty_rate=payload.royalty_rate,    # operator ₹/unit override (else product master rate for the unit)
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

    # Auto vehicle rent (Rate × Km × MT) — net weight is known now (volume token)
    _auto_rent = await _compute_vehicle_rent(db, token, net_kg)
    if _auto_rent is not None:
        token.vehicle_rent = _auto_rent

    # Auto royalty (₹/CUM × CUM) — CUM auto-derived from volume_cft when not supplied
    _auto_royalty = await _compute_royalty(db, token)
    if _auto_royalty is not None:
        token.royalty_amount = _auto_royalty

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

    # Token-completed context: material, qty, party, amount (incl royalty + vehicle
    # rent), completion time in IST. See _build_token_notify_ctx.
    _notify_ctx = await _build_token_notify_ctx(db, token, company)
    background_tasks.add_task(
        _send_notification_bg,
        company.id, "token_completed", _notify_ctx, "token", str(token.id), _bg_tenant,
    )

    # Vehicle In + Out movement alerts (background, non-blocking). A volume token is
    # created AND completed in one call — the truck arrived and left — so both fire.
    try:
        _in_ctx = await _build_vehicle_move_ctx(db, token, company, "in")
        _out_ctx = await _build_vehicle_move_ctx(db, token, company, "out")
        background_tasks.add_task(
            _send_notification_bg,
            company.id, "vehicle_in", _in_ctx, "token", str(token.id), _bg_tenant,
        )
        background_tasks.add_task(
            _send_notification_bg,
            company.id, "vehicle_out", _out_ctx, "token", str(token.id), _bg_tenant,
        )
    except Exception:
        pass

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

    # Operator who created the token (cash accountability)
    if token.created_by:
        from app.models.user import User as _User
        u = (await db.execute(
            select(_User.full_name, _User.username).where(_User.id == token.created_by)
        )).first()
        if u:
            resp.operator_name = u.full_name or u.username

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
    """The ONE token editor — fix anything: vehicle no, party, material, quantity,
    rate, vehicle rent, payment mode, remarks. Allowed even after the token is
    COMPLETED (that is exactly when a typo is noticed, once the slip prints); a
    CANCELLED token stays locked. The linked DRAFT invoice is kept correct:
    party/material change rebuilds it; qty/rate/vehicle-rent/payment-mode change
    re-prices it. If the invoice is already FINALISED, billing fields can't change
    (cancel or revise the bill first) — cosmetic fields still edit freely."""
    from app.models.invoice import Invoice, InvoiceItem
    from app.models.party import Party as PartyModel
    from app.services.gst_service import calculate_invoice_totals, is_intra_state, party_place_of_supply
    from app.services.pricing import token_quantity

    token = await _load_token(db, token_id)
    if token.status == "CANCELLED":
        raise HTTPException(400, "Cannot edit a cancelled token.")

    data = payload.model_dump(exclude_none=True)
    party_changed = "party_id" in data and data["party_id"] != token.party_id
    product_changed = "product_id" in data and data["product_id"] != token.product_id
    _BILLING_KEYS = {"party_id", "product_id", "rate", "net_weight", "volume_cft",
                     "vehicle_rent", "payment_mode", "billing_unit", "royalty_cum",
                     "royalty_unit", "royalty_rate"}
    billing_changed = any(k in data for k in _BILLING_KEYS)

    # Any invoice linked to this token (drives what edits are safe).
    inv = (await db.execute(
        select(Invoice).where(
            Invoice.token_id == token_id,
            Invoice.invoice_type.in_(("sale", "purchase")),
        ).order_by(Invoice.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    if inv and inv.status == "final" and billing_changed:
        raise HTTPException(
            400,
            f"Invoice {inv.invoice_no or ''} is finalised — its quantity/price/party/material "
            f"can't be changed here. Cancel or revise the invoice first.",
        )

    # Clearing the destination arrives as "" (None is dropped by exclude_none, so an
    # empty string is the ONLY way the UI can erase it). Store NULL, not "", so the
    # column keeps one meaning for "not recorded".
    if isinstance(data.get("destination"), str) and not data["destination"].strip():
        data["destination"] = None

    # Apply all edited fields (every key is a real Token column).
    for field, value in data.items():
        setattr(token, field, value)
    if payload.vehicle_no:
        token.vehicle_no = payload.vehicle_no.upper().strip()
    # Volume token: quantity is driven by volume_cft → keep net_weight consistent.
    if token.weight_method == "volume" and "volume_cft" in data:
        vprod = (await db.execute(select(Product).where(Product.id == token.product_id))).scalar_one_or_none() if token.product_id else None
        if vprod and vprod.bulk_density and vprod.bulk_density > 0 and token.volume_cft:
            token.net_weight = (Decimal(str(token.volume_cft)) * vprod.bulk_density).quantize(Decimal("0.01"))
    # A material change invalidates a stale stored rate — unless the caller set one.
    if product_changed and "rate" not in data:
        token.rate = None
    # Royalty basis/volume/material/weight changed → recompute the token's royalty
    # charge (0 when royalty isn't applied / the product has no matching rate).
    if any(k in data for k in ("royalty_cum", "royalty_unit", "royalty_rate", "net_weight", "volume_cft")) or product_changed:
        _r = await _compute_royalty(db, token)
        token.royalty_amount = _r if _r is not None else Decimal("0")

    # Keep the linked invoice consistent with the corrected token.
    if inv and inv.status == "draft":
        if party_changed or product_changed:
            # Rebuild the draft from the corrected token (reuses all the pricing /
            # GST / tax-type logic — picks up the new rate/qty/vehicle_rent/mode).
            for it in (await db.execute(
                select(InvoiceItem).where(InvoiceItem.invoice_id == inv.id)
            )).scalars().all():
                await db.delete(it)
            await db.delete(inv)
            await db.flush()
            company, _active_fy = await _get_company_and_fy(db)
            fy = (await db.execute(
                select(FinancialYear).where(FinancialYear.id == token.fy_id)
            )).scalar_one_or_none() or _active_fy
            if token.party_id and token.product_id and token.token_type in ("sale", "purchase"):
                await _auto_create_invoice(db, token, company, fy, current_user.id,
                                           invoice_type=token.token_type)
        elif billing_changed:
            # Re-price the existing draft from the token's new qty + rate + mode + rent.
            product = (await db.execute(select(Product).where(Product.id == token.product_id))).scalar_one_or_none() if token.product_id else None
            items = (await db.execute(
                select(InvoiceItem).where(InvoiceItem.invoice_id == inv.id).order_by(InvoiceItem.sort_order)
            )).scalars().all()
            if product and items:
                it = items[0]
                bill_unit = token.billing_unit or product.unit
                new_qty = token_quantity(token, bill_unit, product)
                new_rate = token.rate if token.rate is not None else await _fetch_rate(db, token.party_id, token.product_id, bill_unit)
                if "payment_mode" in data:
                    m = (token.payment_mode or "").lower()
                    inv.payment_mode = token.payment_mode
                    inv.tax_type = "non_gst" if m == "cash" else "gst"
                if "vehicle_rent" in data:
                    inv.vehicle_rent = token.vehicle_rent or Decimal("0")
                if any(k in data for k in ("royalty_cum", "royalty_unit", "royalty_rate", "net_weight", "volume_cft")) or product_changed:
                    inv.royalty_amount = token.royalty_amount or Decimal("0")
                party = (await db.execute(select(PartyModel).where(PartyModel.id == inv.party_id))).scalar_one_or_none()
                company, _ = await _get_company_and_fy(db)
                intra = is_intra_state(company.state_code, party_place_of_supply(party) if party else company.state_code)
                totals = calculate_invoice_totals(
                    items=[{
                        "product_id": str(it.product_id), "description": it.description, "hsn_code": it.hsn_code,
                        "quantity": new_qty, "unit": bill_unit, "rate": new_rate,
                        "gst_rate": it.gst_rate or Decimal("0"), "sort_order": 0,
                    }],
                    discount_type=inv.discount_type, discount_value=inv.discount_value or Decimal("0"),
                    freight=inv.freight or Decimal("0"), tcs_rate=inv.tcs_rate or Decimal("0"),
                    intra_state=intra, tax_type=inv.tax_type,
                    vehicle_rent=inv.vehicle_rent or Decimal("0"),
                    royalty=inv.royalty_amount or Decimal("0"),
                )
                for k, v in totals.items():
                    if k != "computed_items" and hasattr(inv, k):
                        setattr(inv, k, v)
                cd = totals["computed_items"][0]
                it.quantity = Decimal(str(cd["quantity"])); it.rate = Decimal(str(cd["rate"]))
                it.unit = bill_unit; it.amount = cd["amount"]; it.gst_rate = Decimal(str(cd.get("gst_rate", 0)))
                it.cgst_amount = cd["cgst_amount"]; it.sgst_amount = cd["sgst_amount"]
                it.igst_amount = cd["igst_amount"]; it.total_amount = cd["total_amount"]
                inv.vehicle_no = token.vehicle_no
                inv.net_weight = token.net_weight
        else:
            # Cosmetic change → keep the invoice's denormalised transport field in step.
            inv.vehicle_no = token.vehicle_no
    elif inv:
        # Non-draft (final): only cosmetic changes reach here (billing blocked above).
        inv.vehicle_no = token.vehicle_no

    await db.commit()

    # Audit trail (best-effort) — who fixed what.
    try:
        from app.routers.audit import log_action
        company, _ = await _get_company_and_fy(db)
        await log_action(db, company.id, current_user.id, "update", "token",
                         str(token.id), {"fields": list(data.keys()), "vehicle_no": token.vehicle_no})
    except Exception:
        pass

    return await get_token(token_id, db, current_user)


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

    # Assign gap-free token_no NOW (at completion, not at creation).
    # #172: an offline edge terminal already minted a token_no in the reserved
    # 9000–9999 band and PRINTED it on the driver's slip — keep that exact number
    # so the slip matches the final record. Honoured only for edge replays, and
    # only if the number is free for the day (a rare cross-terminal clash falls
    # back to a fresh server number; the ux_tokens_no_per_day index is the hard
    # guard). Online second-weights always draw a fresh 1000–8999 number.
    company, fy = await _get_company_and_fy(db)
    edge_no = payload.token_no if (origin == "edge" and payload.token_no) else None
    if edge_no is not None and await _token_no_is_free(db, company.id, token.token_date, edge_no, token.id):
        token.token_no = edge_no
    else:
        token.token_no = await _next_token_no(db, company.id, fy.id, token.token_date)

    # Auto vehicle rent (Rate × Km × MT) — net weight is now known
    _auto_rent = await _compute_vehicle_rent(db, token, token.net_weight)
    if _auto_rent is not None:
        token.vehicle_rent = _auto_rent

    # Auto royalty (₹/CUM × operator-entered CUM) — weighed load carries no volume,
    # so royalty applies only when the operator entered a CUM at token creation.
    _auto_royalty = await _compute_royalty(db, token)
    if _auto_royalty is not None:
        token.royalty_amount = _auto_royalty

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

    _notify_ctx = await _build_token_notify_ctx(db, token, company)
    background_tasks.add_task(
        _send_notification_bg,
        company.id, "token_completed", _notify_ctx, "token", str(token.id), _bg_tenant,
    )

    # Vehicle-Out movement alert (background, non-blocking) — the truck is leaving.
    # Distinct from token_completed (that carries the billing detail); this is the
    # lightweight gate-movement ping. Recipients subscribe to whichever they want.
    try:
        _move_ctx = await _build_vehicle_move_ctx(db, token, company, "out")
        background_tasks.add_task(
            _send_notification_bg,
            company.id, "vehicle_out", _move_ctx, "token", str(token.id), _bg_tenant,
        )
    except Exception:
        pass

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
    token = await _load_token(db, token_id)
    company, _ = await _get_company_and_fy(db)
    volume_unit = (await _get_raw(db, VOLUME_UNIT_KEY)) or "cft"

    # Rate + amount for the cash slip — the bridge operator collects cash against
    # this slip, so it must show Qty × Rate = Amount. Prefer the linked invoice's
    # line item (authoritative once the operator edits/finalises); else derive from
    # the unit-aware party/product rate.
    from app.models.invoice import Invoice, InvoiceItem
    rate: float = 0.0
    amount: float | None = None
    total_amount: float | None = None
    # Royalty + vehicle rent shown on the slip — prefer the linked invoice's values
    # (authoritative: the operator may have edited them on the invoice), else the
    # token's. Sourcing them from the same invoice as total_amount keeps the slip
    # consistent (total already folds these in), so a royalty/rent that's in the
    # total is never dropped from the line breakdown.
    royalty = float(token.royalty_amount) if token.royalty_amount else 0.0
    vrent = float(token.vehicle_rent) if token.vehicle_rent else 0.0
    inv_row = (await db.execute(
        select(Invoice.id, Invoice.grand_total, Invoice.royalty_amount, Invoice.vehicle_rent)
        .where(Invoice.token_id == token_id, Invoice.status.not_in(["cancelled", "superseded"]))
        .order_by(Invoice.created_at.desc()).limit(1)
    )).first()
    if inv_row:
        total_amount = float(inv_row.grand_total) if inv_row.grand_total else None
        if inv_row.royalty_amount is not None:
            royalty = float(inv_row.royalty_amount)
        if inv_row.vehicle_rent is not None:
            vrent = float(inv_row.vehicle_rent)
        item_row = (await db.execute(
            select(InvoiceItem.rate, InvoiceItem.amount)
            .where(InvoiceItem.invoice_id == inv_row.id).limit(1)
        )).first()
        if item_row:
            rate = float(item_row.rate)
            amount = float(item_row.amount)
    if rate == 0.0:
        from app.models.product import Product as _Prod
        _prod = (await db.execute(select(_Prod).where(_Prod.id == token.product_id))).scalar_one_or_none() if token.product_id else None
        _bunit = token.billing_unit or (_prod.unit if _prod else None)
        rate = float(await _fetch_rate(db, token.party_id, token.product_id, _bunit))
        if rate > 0 and _prod:
            from app.services.pricing import token_quantity
            amount = rate * float(token_quantity(token, _bunit, _prod))
    if total_amount is None:
        # No linked invoice — fold vehicle rent + royalty into the slip total so it foots.
        total_amount = (amount or 0.0) + vrent + royalty if (amount or vrent or royalty) else amount

    # Operator who created the token (for the slip + accountability).
    operator_name = None
    if token.created_by:
        from app.models.user import User as _User
        u = (await db.execute(
            select(_User.full_name, _User.username).where(_User.id == token.created_by)
        )).first()
        if u:
            operator_name = (u.full_name or u.username)

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

    # Camera snapshots (Front + Top × 1st + 2nd weight) — embedded in the A4
    # report (format=report) so the owner can print the weighment with photo
    # evidence. The quick A5 slip + thermal slip stay photo-free.
    snapshots = {"first_weight": {}, "second_weight": {}}
    if format == "report":
        try:
            from app.utils.pdf_generator import image_data_uri
            snap_rows = (await db.execute(text("""
                SELECT camera_id, camera_label, weight_stage, file_path
                FROM token_snapshots
                WHERE token_id = :tid AND capture_status = 'captured'
                      AND file_path IS NOT NULL
            """), {"tid": str(token_id)})).fetchall()
            for r in snap_rows:
                stage = (r.weight_stage or "second_weight")
                cam = (r.camera_id or "").strip().lower()
                if stage not in snapshots or not cam:
                    continue
                uri = image_data_uri(r.file_path)
                if uri:
                    snapshots[stage][cam] = {"uri": uri, "label": r.camera_label or cam.title()}
        except Exception:
            snapshots = {"first_weight": {}, "second_weight": {}}
    has_snapshots = bool(snapshots["first_weight"]) or bool(snapshots["second_weight"])

    if format == "thermal":
        template = "token_thermal.html"
    elif format == "report":
        template = "token_report_a4.html"
    else:
        template = "token_a4.html"
    html = render_html(template, {
        "token": token,
        "company": company,
        "volume_unit": volume_unit,
        "slip_custom_fields": slip_custom_fields,
        "rate": rate,
        "amount": amount,
        "royalty": royalty,
        "vehicle_rent": vrent,
        # Trip destination + distance — printed together so the slip carries WHERE
        # the km went, not just how many.
        "destination": token.destination,
        "rent_km": token.rent_km,
        "total_amount": total_amount,
        "operator_name": operator_name,
        "snapshots": snapshots,
        "has_snapshots": has_snapshots,
    })
    return HTMLResponse(content=html)


class CollectCashIn(BaseModel):
    quantity: float | None = None
    rate: float | None = None
    payment_mode: str = "cash"


@router.post("/{token_id}/collect-cash")
async def collect_cash(
    token_id: uuid.UUID,
    payload: CollectCashIn,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Operator cash collection in ONE step: optionally adjust the linked draft
    invoice's qty/rate, finalise it (assign the legal bill number + all the usual
    side-effects) and record the cash payment (settles the bill to PAID). Reuses
    the canonical finalise + receipt endpoints so nothing is re-implemented."""
    from app.models.invoice import Invoice, InvoiceItem
    from app.models.party import Party as PartyModel
    from app.services.gst_service import calculate_invoice_totals, is_intra_state, party_place_of_supply
    from app.schemas.payment import PaymentReceiptCreate, InvoiceAllocation
    from app.routers.invoices import finalise_invoice
    from app.routers.payments import create_receipt

    token = await _load_token(db, token_id)
    inv = (await db.execute(
        select(Invoice).where(
            Invoice.token_id == token_id,
            Invoice.invoice_type == "sale",
            Invoice.status == "draft",
        ).order_by(Invoice.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "No draft invoice for this token — complete the weighment first.")

    items = (await db.execute(
        select(InvoiceItem).where(InvoiceItem.invoice_id == inv.id).order_by(InvoiceItem.sort_order)
    )).scalars().all()
    if not items:
        raise HTTPException(400, "The invoice has no line items.")

    # Optionally adjust qty/rate on the (single) line item, then recompute totals.
    if payload.quantity is not None or payload.rate is not None:
        it = items[0]
        new_qty = Decimal(str(payload.quantity)) if payload.quantity is not None else (it.quantity or Decimal("0"))
        new_rate = Decimal(str(payload.rate)) if payload.rate is not None else (it.rate or Decimal("0"))
        if new_qty <= 0 or new_rate < 0:
            raise HTTPException(400, "Quantity must be greater than zero and rate cannot be negative.")
        party = (await db.execute(select(PartyModel).where(PartyModel.id == inv.party_id))).scalar_one_or_none()
        company, _ = await _get_company_and_fy(db)
        intra = is_intra_state(company.state_code, party_place_of_supply(party) if party else company.state_code)
        totals = calculate_invoice_totals(
            items=[{
                "product_id": str(it.product_id), "description": it.description, "hsn_code": it.hsn_code,
                "quantity": new_qty, "unit": it.unit, "rate": new_rate,
                "gst_rate": it.gst_rate or Decimal("0"), "sort_order": 0,
            }],
            discount_type=inv.discount_type, discount_value=inv.discount_value or Decimal("0"),
            freight=inv.freight or Decimal("0"), tcs_rate=inv.tcs_rate or Decimal("0"),
            intra_state=intra, tax_type=inv.tax_type,
            vehicle_rent=inv.vehicle_rent or Decimal("0"),
        )
        for k, v in totals.items():
            if k != "computed_items" and hasattr(inv, k):
                setattr(inv, k, v)
        cd = totals["computed_items"][0]
        it.quantity = Decimal(str(cd["quantity"])); it.rate = Decimal(str(cd["rate"]))
        it.amount = cd["amount"]; it.gst_rate = Decimal(str(cd.get("gst_rate", 0)))
        it.cgst_amount = cd["cgst_amount"]; it.sgst_amount = cd["sgst_amount"]
        it.igst_amount = cd["igst_amount"]; it.total_amount = cd["total_amount"]
        await db.commit()

    inv_id = inv.id
    party_id = inv.party_id

    # Finalise (assigns the bill number + all side-effects; commits internally).
    await finalise_invoice(inv_id, background_tasks, db, current_user)
    inv = (await db.execute(select(Invoice).where(Invoice.id == inv_id))).scalar_one()
    grand = inv.grand_total or Decimal("0")

    # Record the cash payment → settles the bill to PAID.
    receipt_no = None
    if grand > 0 and inv.payment_status != "paid":
        rec = await create_receipt(
            PaymentReceiptCreate(
                receipt_date=inv.invoice_date or date.today(),
                party_id=party_id, amount=grand,
                payment_mode=(payload.payment_mode or "cash"),
                allocations=[InvoiceAllocation(invoice_id=inv_id, amount=grand)],
            ),
            background_tasks, db, current_user,
        )
        receipt_no = getattr(rec, "receipt_no", None)
        inv = (await db.execute(select(Invoice).where(Invoice.id == inv_id))).scalar_one()

    return {
        "invoice_id": str(inv_id),
        "invoice_no": inv.invoice_no,
        "grand_total": float(grand),
        "receipt_no": receipt_no,
        "payment_status": inv.payment_status,
    }


class TokenPricingIn(BaseModel):
    """Edit a token's billable quantity and/or material price. The frontend sends
    the quantity already converted to the token's storage unit (net_weight in kg
    for a weighbridge token, volume_cft for a volume token)."""
    rate: Decimal | None = None            # ₹ per billing_unit
    net_weight: Decimal | None = None      # kg — weighbridge qty override
    volume_cft: Decimal | None = None      # volume qty override (volume tokens)
    billing_unit: str | None = None        # change the billing unit
    payment_mode: str | None = None        # cash | credit | upi | bank_transfer → invoice tax_type
    rent_km: Decimal | None = None         # trip distance → recompute vehicle_rent (Rate × Km × qty)
    rent_rate_per_km_per_mt: Decimal | None = None    # operator override of the ₹/km/MT rate
    rent_rate_per_km_per_cum: Decimal | None = None   # operator override of the ₹/km/CUM rate
    vehicle_rent: Decimal | None = None    # explicit manual override of the auto rent
    royalty_cum: Decimal | None = None     # CUM volume for royalty → recompute royalty_amount (₹/CUM × CUM)
    royalty_unit: str | None = None        # 'mt' | 'cum' — royalty basis
    royalty_rate: Decimal | None = None    # operator ₹/unit override (else product master rate for the unit)
    royalty_amount: Decimal | None = None  # explicit manual override of the auto royalty
    clear_royalty: bool = False            # remove royalty from the token + invoice


@router.put("/{token_id}/pricing", response_model=TokenResponse)
async def update_token_pricing(
    token_id: uuid.UUID,
    payload: TokenPricingIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a token's quantity and/or material price, and re-sync the linked
    DRAFT invoice so the change flows to billing. Works on COMPLETED tokens (that
    is when the draft invoice exists). If the invoice is already FINALISED it is
    left untouched and the request is rejected — amend it via an invoice revision.
    """
    from app.models.invoice import Invoice, InvoiceItem
    from app.models.party import Party as PartyModel
    from app.services.gst_service import calculate_invoice_totals, is_intra_state, party_place_of_supply
    from app.services.pricing import token_quantity

    token = await _load_token(db, token_id)
    if token.status == "CANCELLED":
        raise HTTPException(400, "Cannot edit a cancelled token.")

    changing_billing = (
        payload.rate is not None or payload.net_weight is not None
        or payload.volume_cft is not None or payload.payment_mode is not None
        or payload.billing_unit is not None
    )

    # Guard: never silently edit a finalised bill's basis.
    finalised = (await db.execute(
        select(Invoice.id, Invoice.invoice_no).where(
            Invoice.token_id == token_id,
            Invoice.invoice_type.in_(("sale", "purchase")),
            Invoice.status == "final",
        ).limit(1)
    )).first()
    if finalised and changing_billing:
        raise HTTPException(
            400,
            f"Invoice {finalised.invoice_no or ''} for this token is already finalised. "
            f"Create a revision on the invoice to change its quantity, rate or payment mode.",
        )

    product = (await db.execute(
        select(Product).where(Product.id == token.product_id)
    )).scalar_one_or_none() if token.product_id else None

    # Apply token field updates.
    if payload.billing_unit is not None:
        token.billing_unit = payload.billing_unit
    if payload.rate is not None:
        token.rate = payload.rate
    if payload.payment_mode is not None:
        token.payment_mode = payload.payment_mode
    if token.weight_method == "volume":
        # Volume token: quantity is driven by volume_cft; keep net_weight consistent.
        if payload.volume_cft is not None:
            if payload.volume_cft <= 0:
                raise HTTPException(400, "Volume must be greater than zero.")
            token.volume_cft = payload.volume_cft
            if product and product.bulk_density and product.bulk_density > 0:
                token.net_weight = (payload.volume_cft * product.bulk_density).quantize(Decimal("0.01"))
    else:
        # Weighbridge token: quantity is driven by net_weight (kg).
        if payload.net_weight is not None:
            if payload.net_weight <= 0:
                raise HTTPException(400, "Weight must be greater than zero.")
            token.net_weight = payload.net_weight

    # Vehicle rent: explicit override wins; else recompute rate × km × qty from the
    # (possibly updated) distance, rate overrides + weight.
    if payload.rent_km is not None:
        token.rent_km = payload.rent_km
    if payload.rent_rate_per_km_per_mt is not None:
        token.rent_rate_per_km_per_mt = payload.rent_rate_per_km_per_mt
    if payload.rent_rate_per_km_per_cum is not None:
        token.rent_rate_per_km_per_cum = payload.rent_rate_per_km_per_cum
    if payload.vehicle_rent is not None:
        token.vehicle_rent = payload.vehicle_rent
    else:
        _auto_rent = await _compute_vehicle_rent(db, token, token.net_weight)
        if _auto_rent is not None:
            token.vehicle_rent = _auto_rent

    # Royalty: clear it, take an explicit override, or recompute rate × qty.
    if payload.clear_royalty:
        token.royalty_cum = None
        token.royalty_unit = None
        token.royalty_rate = None
        token.royalty_amount = Decimal("0")
    else:
        if payload.royalty_unit is not None:
            token.royalty_unit = payload.royalty_unit
        if payload.royalty_cum is not None:
            token.royalty_cum = payload.royalty_cum
        if payload.royalty_rate is not None:
            token.royalty_rate = payload.royalty_rate
        if payload.royalty_amount is not None:
            token.royalty_amount = payload.royalty_amount
        elif payload.royalty_cum is not None or payload.royalty_unit is not None or payload.royalty_rate is not None:
            _auto_roy = await _compute_royalty(db, token)
            if _auto_roy is not None:
                token.royalty_amount = _auto_roy

    # Re-sync the linked DRAFT invoice (if any) from the token's new qty + rate.
    inv = (await db.execute(
        select(Invoice).where(
            Invoice.token_id == token_id,
            Invoice.invoice_type.in_(("sale", "purchase")),
            Invoice.status == "draft",
        ).order_by(Invoice.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    if inv and product:
        bill_unit = token.billing_unit or product.unit
        new_qty = token_quantity(token, bill_unit, product)
        new_rate = token.rate if token.rate is not None else await _fetch_rate(
            db, token.party_id, token.product_id, bill_unit
        )
        # A payment-mode change re-derives the tax basis on the draft:
        #   cash → non-GST Bill of Supply, credit/upi/bank → GST Tax Invoice.
        if payload.payment_mode is not None:
            tok_mode = (token.payment_mode or "").lower()
            inv.payment_mode = token.payment_mode
            inv.tax_type = "non_gst" if tok_mode == "cash" else "gst"
        items = (await db.execute(
            select(InvoiceItem).where(InvoiceItem.invoice_id == inv.id).order_by(InvoiceItem.sort_order)
        )).scalars().all()
        if items:
            it = items[0]
            inv.vehicle_rent = token.vehicle_rent or Decimal("0")
            inv.royalty_amount = token.royalty_amount or Decimal("0")
            party = (await db.execute(select(PartyModel).where(PartyModel.id == inv.party_id))).scalar_one_or_none()
            company, _ = await _get_company_and_fy(db)
            intra = is_intra_state(company.state_code, party_place_of_supply(party) if party else company.state_code)
            totals = calculate_invoice_totals(
                items=[{
                    "product_id": str(it.product_id), "description": it.description, "hsn_code": it.hsn_code,
                    "quantity": new_qty, "unit": bill_unit, "rate": new_rate,
                    "gst_rate": it.gst_rate or Decimal("0"), "sort_order": 0,
                }],
                discount_type=inv.discount_type, discount_value=inv.discount_value or Decimal("0"),
                freight=inv.freight or Decimal("0"), tcs_rate=inv.tcs_rate or Decimal("0"),
                intra_state=intra, tax_type=inv.tax_type,
                vehicle_rent=inv.vehicle_rent or Decimal("0"),
                royalty=inv.royalty_amount or Decimal("0"),
            )
            for k, v in totals.items():
                if k != "computed_items" and hasattr(inv, k):
                    setattr(inv, k, v)
            cd = totals["computed_items"][0]
            it.quantity = Decimal(str(cd["quantity"])); it.rate = Decimal(str(cd["rate"]))
            it.unit = bill_unit
            it.amount = cd["amount"]; it.gst_rate = Decimal(str(cd.get("gst_rate", 0)))
            it.cgst_amount = cd["cgst_amount"]; it.sgst_amount = cd["sgst_amount"]
            it.igst_amount = cd["igst_amount"]; it.total_amount = cd["total_amount"]
            # keep denormalised weight on the invoice in step with the token
            inv.net_weight = token.net_weight

    await db.commit()
    return await get_token(token_id, db, current_user)

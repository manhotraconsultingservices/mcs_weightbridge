import uuid
from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.customer_user import CustomerUser
from app.utils.auth import hash_password
from app.models.party import Party, PartyRate
from app.models.product import Product
from app.models.invoice import Invoice
from app.models.payment import PaymentReceipt, PaymentVoucher
from app.models.token import Token
from app.services.balances import recompute_party_balance, party_advance_remaining
from app.schemas.party import (
    PartyCreate, PartyUpdate, PartyResponse,
    PartyRateCreate, PartyRateResponse,
    Party360Response, Party360Header, Party360Stats, Party360AgingBuckets,
    Party360Invoice, Party360Payment, Party360CustomRate,
)

router = APIRouter()


@router.get("", response_model=dict)
async def list_parties(
    party_type: str | None = None,
    search: str | None = None,
    active_only: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List parties with pagination. Pass page_size=9999 to get all (e.g. for dropdowns)."""
    base_q = select(Party).where(Party.company_id == current_user.company_id)
    if active_only:
        base_q = base_q.where(Party.is_active == True)
    if party_type:
        base_q = base_q.where(Party.party_type.in_([party_type, "both"]))
    if search:
        base_q = base_q.where(Party.name.ilike(f"%{search}%"))

    total = (await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )).scalar() or 0

    query = base_q.order_by(Party.name).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = [PartyResponse.model_validate(p) for p in result.scalars().all()]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=PartyResponse, status_code=201)
async def create_party(
    data: PartyCreate,
    current_user: User = Depends(require_role("admin", "operator", "accountant")),
    db: AsyncSession = Depends(get_db),
):
    party = Party(
        company_id=current_user.company_id,
        current_balance=data.opening_balance,
        **data.model_dump(),
    )
    db.add(party)
    await db.commit()
    await db.refresh(party)
    return PartyResponse.model_validate(party)


@router.get("/{party_id}", response_model=PartyResponse)
async def get_party(
    party_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Party).where(Party.id == party_id, Party.company_id == current_user.company_id)
    )
    party = result.scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")
    return PartyResponse.model_validate(party)


@router.put("/{party_id}", response_model=PartyResponse)
async def update_party(
    party_id: uuid.UUID,
    data: PartyUpdate,
    current_user: User = Depends(require_role("admin", "operator", "accountant")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Party).where(Party.id == party_id, Party.company_id == current_user.company_id)
    )
    party = result.scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(party, field, value)
    await db.commit()
    await db.refresh(party)
    return PartyResponse.model_validate(party)


@router.delete("/{party_id}")
async def delete_party(
    party_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Party).where(Party.id == party_id, Party.company_id == current_user.company_id)
    )
    party = result.scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")
    party.is_active = False
    await db.commit()
    return {"message": "Party deactivated"}


# --- Party Rates ---

@router.get("/{party_id}/rates", response_model=list[PartyRateResponse])
async def list_party_rates(
    party_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PartyRate).where(PartyRate.party_id == party_id).order_by(PartyRate.effective_from.desc())
    )
    return [PartyRateResponse.model_validate(r) for r in result.scalars().all()]


@router.post("/{party_id}/rates", response_model=PartyRateResponse, status_code=201)
async def set_party_rate(
    party_id: uuid.UUID,
    data: PartyRateCreate,
    current_user: User = Depends(require_role("admin", "operator", "accountant")),
    db: AsyncSession = Depends(get_db),
):
    rate = PartyRate(party_id=party_id, **data.model_dump())
    db.add(rate)
    await db.commit()
    await db.refresh(rate)
    return PartyRateResponse.model_validate(rate)


@router.delete("/{party_id}/rates/{product_id}", status_code=204)
async def delete_party_rate(
    party_id: uuid.UUID,
    product_id: uuid.UUID,
    current_user: User = Depends(require_role("admin", "accountant")),
    db: AsyncSession = Depends(get_db),
):
    """Remove all party-specific rates for this product so the default rate applies."""
    result = await db.execute(
        select(PartyRate).where(
            PartyRate.party_id == party_id,
            PartyRate.product_id == product_id,
        )
    )
    for row in result.scalars().all():
        await db.delete(row)
    await db.commit()


# --- Effective rate lookup (used by the invoice creation flow) ---

@router.get("/{party_id}/effective-rate/{product_id}")
async def get_effective_rate(
    party_id: uuid.UUID,
    product_id: uuid.UUID,
    unit: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rate that applies for (party, product, unit) today — unit-aware.

    Priority (services/pricing.resolve_rate): customer rate for this unit →
    customer legacy rate (base unit) → product per-unit default → product
    default_rate (base unit) → 0. `unit` omitted → the product's base unit.
    Returns `source` for the UI badge.
    """
    from app.services.pricing import resolve_rate, norm_unit
    rate = await resolve_rate(db, party_id, product_id, unit)
    prod = (await db.execute(select(Product).where(Product.id == product_id))).scalar_one_or_none()
    eff_u = norm_unit(unit) or (norm_unit(prod.unit) if prod else "")
    base = norm_unit(prod.unit) if prod else ""
    prows = (await db.execute(
        select(PartyRate).where(
            PartyRate.party_id == party_id, PartyRate.product_id == product_id,
            PartyRate.effective_from <= date.today(),
        )
    )).scalars().all()
    is_party = any(norm_unit(pr.unit) == eff_u for pr in prows) or (eff_u == base and any(pr.unit is None for pr in prows))
    source = "party_rate" if (is_party and rate > 0) else ("product_default" if rate > 0 else "none")
    return {"rate": float(rate), "source": source, "unit": eff_u, "effective_from": None}


# --- Bulk matrix view + bulk save (powers /pricing-matrix UI) ---

@router.get("/rates/matrix")
async def get_pricing_matrix(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a flat list of every (party_id, product_id, rate) currently active.

    The frontend turns this into a sparse matrix; cells without a row use
    the product's default_rate.
    """
    # Most-recent rate per (party_id, product_id, unit) where effective_from <= today.
    # unit is included so a party can hold distinct MT/CFT/CBM/Brass rates for the
    # same product; legacy rows (unit NULL) surface as the base-unit cell.
    today = date.today()
    rows = (await db.execute(
        select(
            PartyRate.party_id,
            PartyRate.product_id,
            PartyRate.unit,
            PartyRate.rate,
            PartyRate.effective_from,
        )
        .where(PartyRate.effective_from <= today)
        .order_by(PartyRate.party_id, PartyRate.product_id, PartyRate.effective_from.desc())
    )).all()

    seen: set[tuple] = set()
    result = []
    for r in rows:
        key = (r.party_id, r.product_id, (r.unit or "").upper())
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "party_id": str(r.party_id),
            "product_id": str(r.product_id),
            "unit": r.unit,
            "rate": float(r.rate),
            "effective_from": r.effective_from.isoformat(),
        })
    return {"cells": result}


@router.post("/{party_id}/rates/bulk", status_code=201)
async def bulk_set_party_rates(
    party_id: uuid.UUID,
    payload: dict,
    request: Request,
    current_user: User = Depends(require_role("admin", "accountant")),
    db: AsyncSession = Depends(get_db),
):
    """Set multiple per-unit rates for one party in one call.

    Body shape:
      { "rates": [ { "product_id": "uuid", "unit": "CFT", "rate": 42.00 }, ... ] }

    Each entry creates a new party_rates row (effective_from = today) for that
    (product, unit). `unit` omitted → the legacy base-unit rate (unit NULL).
    `rate: null` clears existing rates for that (party, product, unit).
    """
    rates = payload.get("rates") or []
    today = date.today()
    saved, cleared = 0, 0

    def _norm(u):
        return (u or "").strip().upper() or None

    for entry in rates:
        product_id = entry.get("product_id")
        if not product_id:
            continue
        pid = uuid.UUID(product_id) if isinstance(product_id, str) else product_id
        unit = _norm(entry.get("unit"))
        rate_value = entry.get("rate")
        # Delete existing rows for this (party, product, unit) — unit-scoped so
        # clearing/replacing a CFT rate doesn't touch the MT rate.
        existing = (await db.execute(
            select(PartyRate).where(
                PartyRate.party_id == party_id,
                PartyRate.product_id == pid,
                (func.upper(PartyRate.unit) == unit) if unit is not None else PartyRate.unit.is_(None),
            )
        )).scalars().all()
        for row in existing:
            await db.delete(row)
        if rate_value is None:
            cleared += 1
        else:
            db.add(PartyRate(
                party_id=party_id, product_id=pid,
                rate=Decimal(str(rate_value)), unit=unit, effective_from=today,
            ))
            saved += 1

    # Customer/supplier rates drive every invoice for that party, so who changed
    # them and when has to be traceable — same reason the default rates are audited.
    if saved or cleared:
        from app.routers.audit import log_action
        await log_action(db, current_user.company_id, current_user.id, "update", "pricing",
                         entity_id=str(party_id),
                         details={"scope": "party_rates", "party_id": str(party_id),
                                  "saved": saved, "cleared": cleared},
                         ip_address=(request.client.host if request and request.client else None))
    await db.commit()
    return {"saved": saved, "cleared": cleared}


# --- Customer 360 view ---------------------------------------------------------

@router.get("/{party_id}/360", response_model=Party360Response)
async def party_360(
    party_id: uuid.UUID,
    recent_limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One-shot aggregate view used by the customer/supplier profile page.

    Returns header + KPIs + last N invoices + last N payments + custom rates,
    so the page renders in a single round-trip.
    """
    party = (await db.execute(
        select(Party).where(
            Party.id == party_id, Party.company_id == current_user.company_id,
        )
    )).scalar_one_or_none()
    if not party:
        raise HTTPException(404, "Party not found")

    today = date.today()

    # ── All non-cancelled sale + purchase invoices for lifetime stats ─────
    inv_rows = (await db.execute(
        select(Invoice)
        .where(
            Invoice.company_id == current_user.company_id,
            Invoice.party_id == party_id,
            Invoice.status.not_in(["cancelled", "superseded"]),
        )
        .order_by(Invoice.invoice_date.desc(), Invoice.created_at.desc())
    )).scalars().all()

    # Lifetime metrics — driven by the party's PRIMARY trade direction so the
    # 360 works for both Customers (sales) and Suppliers/Farmers (purchases):
    #   customer → sale invoices · supplier → purchase invoices · both → either.
    # `lifetime_sales` therefore means "lifetime transacted value" — sales for a
    # customer, purchases for a supplier.
    if party.party_type == "supplier":
        primary_types = ("purchase",)
    elif party.party_type == "both":
        primary_types = ("sale", "purchase")
    else:
        primary_types = ("sale",)
    primary_invoices = [i for i in inv_rows if i.invoice_type in primary_types]
    lifetime_sales = sum((i.grand_total or Decimal("0")) for i in primary_invoices)
    lifetime_paid = sum((i.amount_paid or Decimal("0")) for i in primary_invoices)
    lifetime_written_off = sum((i.write_off_amount or Decimal("0")) for i in primary_invoices)
    write_off_count = sum(1 for i in primary_invoices if (i.write_off_amount or Decimal("0")) > 0)
    invoice_count = len(primary_invoices)
    aov = (lifetime_sales / invoice_count) if invoice_count else Decimal("0")
    last_invoice_date = max((i.invoice_date for i in primary_invoices), default=None)
    days_since_last_order = (today - last_invoice_date).days if last_invoice_date else None

    # ── Outstanding + aging buckets (final, unpaid invoices only) ─────────
    aging = Party360AgingBuckets()
    total_outstanding = Decimal("0")
    total_overdue = Decimal("0")
    for inv in inv_rows:
        if inv.status != "final" or inv.payment_status == "paid":
            continue
        if inv.invoice_type not in ("sale", "purchase"):
            continue   # credit/debit notes are not receivable rows (handled separately)
        balance = (inv.grand_total or Decimal("0")) - (inv.amount_paid or Decimal("0"))
        if balance <= 0:
            continue
        total_outstanding += balance
        # Bucket by days-past-due (or due_today=current if no due_date)
        if inv.due_date and inv.due_date < today:
            days = (today - inv.due_date).days
            total_overdue += balance
            if days <= 30:
                aging.bucket_1_30 += balance
            elif days <= 60:
                aging.bucket_31_60 += balance
            elif days <= 90:
                aging.bucket_61_90 += balance
            else:
                aging.bucket_90_plus += balance
        else:
            aging.current += balance

    # ── Recent invoices (limit) ───────────────────────────────────────────
    recent_invoices = [
        Party360Invoice(
            id=i.id,
            invoice_no=i.invoice_no,
            invoice_date=i.invoice_date,
            due_date=i.due_date,
            invoice_type=i.invoice_type,
            grand_total=i.grand_total or Decimal("0"),
            amount_paid=i.amount_paid or Decimal("0"),
            amount_due=i.amount_due or Decimal("0"),
            payment_status=i.payment_status,
            status=i.status,
        )
        for i in inv_rows[:recent_limit]
    ]

    # ── Recent payments — merge receipts + vouchers, sort desc ─────────────
    receipts = (await db.execute(
        select(PaymentReceipt)
        .where(
            PaymentReceipt.company_id == current_user.company_id,
            PaymentReceipt.party_id == party_id,
        )
        .order_by(PaymentReceipt.receipt_date.desc(), PaymentReceipt.created_at.desc())
        .limit(recent_limit)
    )).scalars().all()

    vouchers = (await db.execute(
        select(PaymentVoucher)
        .where(
            PaymentVoucher.company_id == current_user.company_id,
            PaymentVoucher.party_id == party_id,
        )
        .order_by(PaymentVoucher.voucher_date.desc(), PaymentVoucher.created_at.desc())
        .limit(recent_limit)
    )).scalars().all()

    pay_pool: list[tuple[date, Party360Payment]] = []
    for r in receipts:
        pay_pool.append((r.receipt_date, Party360Payment(
            id=r.id, kind="receipt", voucher_no=r.receipt_no,
            payment_date=r.receipt_date, amount=r.amount,
            payment_mode=r.payment_mode, reference_no=r.reference_no,
        )))
    for v in vouchers:
        pay_pool.append((v.voucher_date, Party360Payment(
            id=v.id, kind="voucher", voucher_no=v.voucher_no,
            payment_date=v.voucher_date, amount=v.amount,
            payment_mode=v.payment_mode, reference_no=v.reference_no,
        )))
    pay_pool.sort(key=lambda t: t[0], reverse=True)
    recent_payments = [p for _, p in pay_pool[:recent_limit]]
    last_payment_date = pay_pool[0][0] if pay_pool else None
    days_since_last_payment = (today - last_payment_date).days if last_payment_date else None

    # ── Custom rates (most-recent per product) ─────────────────────────────
    rate_rows = (await db.execute(
        select(PartyRate, Product)
        .join(Product, PartyRate.product_id == Product.id)
        .where(
            PartyRate.party_id == party_id,
            PartyRate.effective_from <= today,
        )
        .order_by(PartyRate.party_id, PartyRate.product_id, PartyRate.effective_from.desc())
    )).all()
    seen: set[uuid.UUID] = set()
    custom_rates: list[Party360CustomRate] = []
    for r, p in rate_rows:
        if r.product_id in seen:
            continue
        seen.add(r.product_id)
        custom_rates.append(Party360CustomRate(
            product_id=r.product_id,
            product_name=p.name,
            product_unit=p.unit,
            default_rate=p.default_rate or Decimal("0"),
            custom_rate=r.rate,
            effective_from=r.effective_from,
        ))

    # ── Operations stats: token count + tonnage ────────────────────────────
    tok_agg = (await db.execute(
        select(
            func.count(Token.id),
            func.coalesce(func.sum(Token.net_weight), 0),
        )
        .where(
            Token.company_id == current_user.company_id,
            Token.party_id == party_id,
            Token.status == "COMPLETED",
        )
    )).one()
    token_count, tonnage_kg = tok_agg[0] or 0, Decimal(str(tok_agg[1] or 0))
    # net_weight stored in kg → MT
    lifetime_tonnage = (tonnage_kg / Decimal("1000")).quantize(Decimal("0.001"))

    # ── Advance / prepayment on account (unallocated receipts/vouchers) ─────
    #   customer → money they've prepaid us (receipt remainder)
    #   supplier → money we've prepaid them (voucher remainder)
    #   both     → either side's remainder
    adv = await party_advance_remaining(db, party_id)
    if party.party_type == "supplier":
        advance_balance = adv["voucher_adv"]
    elif party.party_type == "both":
        advance_balance = adv["receipt_adv"] + adv["voucher_adv"]
    else:
        advance_balance = adv["receipt_adv"]

    stats = Party360Stats(
        lifetime_sales=lifetime_sales,
        lifetime_paid=lifetime_paid,
        lifetime_written_off=lifetime_written_off,
        write_off_count=write_off_count,
        invoice_count=invoice_count,
        avg_order_value=aov,
        last_invoice_date=last_invoice_date,
        days_since_last_order=days_since_last_order,
        last_payment_date=last_payment_date,
        days_since_last_payment=days_since_last_payment,
        total_outstanding=total_outstanding,
        total_overdue=total_overdue,
        advance_balance=advance_balance,
        aging=aging,
        token_count=int(token_count),
        lifetime_tonnage=lifetime_tonnage,
    )

    header = Party360Header(
        id=party.id,
        name=party.name,
        party_type=party.party_type,
        gstin=party.gstin,
        pan=party.pan,
        phone=party.phone,
        email=party.email,
        billing_city=party.billing_city,
        billing_state=party.billing_state,
        credit_limit=party.credit_limit or Decimal("0"),
        payment_terms_days=party.payment_terms_days or 0,
        current_balance=party.current_balance or Decimal("0"),
        opening_balance=party.opening_balance or Decimal("0"),
        is_active=party.is_active,
    )

    return Party360Response(
        party=header,
        stats=stats,
        recent_invoices=recent_invoices,
        recent_payments=recent_payments,
        custom_rates=custom_rates,
    )


@router.post("/recompute-balances")
async def recompute_all_balances(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """One-shot admin backfill: recompute current_balance for EVERY party.

    Safe + idempotent (recompute_party_balance reads from source). Useful once
    after the advance-aware balance change so pre-existing unallocated advances
    are reflected without waiting for each party's next event.
    """
    ids = (await db.execute(
        select(Party.id).where(Party.company_id == current_user.company_id)
    )).scalars().all()
    for pid in ids:
        await recompute_party_balance(db, pid)
    await db.commit()
    return {"recomputed": len(ids)}


# --- Credit status (advisory — never blocks) ----------------------------------

@router.get("/{party_id}/credit-status")
async def party_credit_status(
    party_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lightweight credit exposure for a party — drives advisory banners.

    Warn-only by design (per product decision): this endpoint NEVER blocks an
    action. The UI shows a banner; the operator decides. ``outstanding`` is the
    sum of unpaid balances on FINAL sale invoices; ``overdue`` is the portion
    past its due date. ``credit_limit == 0`` means "no limit set" (unlimited).
    """
    party = (await db.execute(
        select(Party).where(
            Party.id == party_id, Party.company_id == current_user.company_id,
        )
    )).scalar_one_or_none()
    if not party:
        raise HTTPException(404, "Party not found")

    today = date.today()
    inv_rows = (await db.execute(
        select(Invoice).where(
            Invoice.company_id == current_user.company_id,
            Invoice.party_id == party_id,
            Invoice.invoice_type == "sale",
            Invoice.status == "final",
        )
    )).scalars().all()

    outstanding = Decimal("0")
    overdue = Decimal("0")
    overdue_days = 0
    for inv in inv_rows:
        if inv.payment_status == "paid":
            continue
        bal = (inv.grand_total or Decimal("0")) - (inv.amount_paid or Decimal("0"))
        if bal <= 0:
            continue
        outstanding += bal
        if inv.due_date and inv.due_date < today:
            overdue += bal
            overdue_days = max(overdue_days, (today - inv.due_date).days)

    # Net effect of finalised credit/debit notes on the receivable:
    # a sales credit note reduces what the customer owes; a debit note increases it.
    note_rows = (await db.execute(
        select(Invoice.invoice_type, Invoice.grand_total).where(
            Invoice.company_id == current_user.company_id,
            Invoice.party_id == party_id,
            Invoice.invoice_type.in_(("credit_note", "debit_note")),
            Invoice.status == "final",
        )
    )).all()
    for ntype, gt in note_rows:
        amt = gt or Decimal("0")
        outstanding += (-amt if ntype == "credit_note" else amt)
    if outstanding < 0:
        outstanding = Decimal("0")

    credit_limit = party.credit_limit or Decimal("0")
    unlimited = credit_limit <= 0
    available = None if unlimited else (credit_limit - outstanding)

    if not unlimited and outstanding > credit_limit:
        status_ = "over_limit"
        message = (f"Over credit limit by ₹{float(outstanding - credit_limit):,.0f} "
                   f"(₹{float(outstanding):,.0f} outstanding vs ₹{float(credit_limit):,.0f} limit).")
    elif overdue > 0:
        status_ = "overdue"
        message = (f"₹{float(overdue):,.0f} overdue ({overdue_days} days past due).")
    elif not unlimited and outstanding >= credit_limit * Decimal("0.8"):
        status_ = "near_limit"
        message = (f"Near credit limit — ₹{float(available or 0):,.0f} of "
                   f"₹{float(credit_limit):,.0f} remaining.")
    else:
        status_ = "ok"
        message = None

    return {
        "party_id": str(party.id),
        "party_name": party.name,
        "credit_limit": float(credit_limit),
        "unlimited": unlimited,
        "outstanding": float(outstanding),
        "available_credit": None if available is None else float(available),
        "overdue_amount": float(overdue),
        "overdue_days": overdue_days,
        "payment_terms_days": party.payment_terms_days or 0,
        "status": status_,        # ok | near_limit | overdue | over_limit
        "message": message,       # null when status == ok
    }


# --- Customer portal account management (admin) --------------------------------

class PortalAccountRequest(BaseModel):
    email: str
    password: str


class PortalPasswordReset(BaseModel):
    password: str


async def _get_portal_account(db: AsyncSession, company_id, party_id) -> CustomerUser | None:
    return (await db.execute(
        select(CustomerUser).where(
            CustomerUser.company_id == company_id, CustomerUser.party_id == party_id,
        )
    )).scalar_one_or_none()


@router.get("/{party_id}/portal-account")
async def get_portal_account(
    party_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    cu = await _get_portal_account(db, current_user.company_id, party_id)
    if not cu:
        return {"exists": False}
    return {"exists": True, "email": cu.email, "is_active": cu.is_active,
            "last_login_at": cu.last_login_at.isoformat() if cu.last_login_at else None}


@router.post("/{party_id}/portal-account", status_code=201)
async def create_portal_account(
    party_id: uuid.UUID,
    payload: PortalAccountRequest,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    party = (await db.execute(
        select(Party).where(Party.id == party_id, Party.company_id == current_user.company_id)
    )).scalar_one_or_none()
    if not party:
        raise HTTPException(404, "Party not found")
    if len(payload.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    existing = await _get_portal_account(db, current_user.company_id, party_id)
    if existing:
        # Re-enable + update credentials
        existing.email = payload.email.strip().lower()
        existing.password_hash = hash_password(payload.password)
        existing.is_active = True
    else:
        db.add(CustomerUser(
            company_id=current_user.company_id, party_id=party_id,
            email=payload.email.strip().lower(),
            password_hash=hash_password(payload.password),
            is_active=True, created_by=current_user.id,
        ))
    await db.commit()
    return {"ok": True, "email": payload.email.strip().lower()}


@router.post("/{party_id}/portal-account/reset-password")
async def reset_portal_password(
    party_id: uuid.UUID,
    payload: PortalPasswordReset,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    cu = await _get_portal_account(db, current_user.company_id, party_id)
    if not cu:
        raise HTTPException(404, "No portal account for this party")
    if len(payload.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    cu.password_hash = hash_password(payload.password)
    cu.is_active = True
    await db.commit()
    return {"ok": True}


@router.delete("/{party_id}/portal-account")
async def disable_portal_account(
    party_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    cu = await _get_portal_account(db, current_user.company_id, party_id)
    if not cu:
        raise HTTPException(404, "No portal account for this party")
    cu.is_active = False
    await db.commit()
    return {"ok": True}

import uuid
from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.party import Party, PartyRate
from app.models.product import Product
from app.models.invoice import Invoice
from app.models.payment import PaymentReceipt, PaymentVoucher
from app.models.token import Token
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the rate that would apply for this (party, product) combo today.

    Priority: party_rates (most recent effective_from <= today)
              → product.default_rate
              → 0

    Response shape includes the *source* so the UI can render badges like
    "Customer rate" vs "Default rate".
    """
    party_rate = (await db.execute(
        select(PartyRate)
        .where(
            PartyRate.party_id == party_id,
            PartyRate.product_id == product_id,
            PartyRate.effective_from <= date.today(),
        )
        .order_by(PartyRate.effective_from.desc())
        .limit(1)
    )).scalar_one_or_none()

    if party_rate:
        return {
            "rate": float(party_rate.rate),
            "source": "party_rate",
            "effective_from": party_rate.effective_from.isoformat(),
        }

    product = (await db.execute(select(Product).where(Product.id == product_id))).scalar_one_or_none()
    if product:
        return {
            "rate": float(product.default_rate),
            "source": "product_default",
            "effective_from": None,
        }
    return {"rate": 0, "source": "none", "effective_from": None}


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
    # Most-recent rate per (party_id, product_id) where effective_from <= today
    today = date.today()
    rows = (await db.execute(
        select(
            PartyRate.party_id,
            PartyRate.product_id,
            PartyRate.rate,
            PartyRate.effective_from,
            PartyRate.id,
        )
        .where(PartyRate.effective_from <= today)
        .order_by(PartyRate.party_id, PartyRate.product_id, PartyRate.effective_from.desc())
    )).all()

    # Collapse to first row per (party_id, product_id) — that's the most-recent
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    result = []
    for r in rows:
        key = (r.party_id, r.product_id)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "party_id": str(r.party_id),
            "product_id": str(r.product_id),
            "rate": float(r.rate),
            "effective_from": r.effective_from.isoformat(),
        })
    return {"cells": result}


@router.post("/{party_id}/rates/bulk", status_code=201)
async def bulk_set_party_rates(
    party_id: uuid.UUID,
    payload: dict,
    current_user: User = Depends(require_role("admin", "accountant")),
    db: AsyncSession = Depends(get_db),
):
    """Set multiple rates for one party in one call.

    Body shape:
      { "rates": [ { "product_id": "uuid", "rate": 560.00 }, ... ] }

    Each entry creates a new party_rates row with effective_from = today.
    To clear a rate (revert to default), include `rate: null` — that deletes
    all existing rates for that (party, product).
    """
    rates = payload.get("rates") or []
    today = date.today()
    saved, cleared = 0, 0

    for entry in rates:
        product_id = entry.get("product_id")
        if not product_id:
            continue
        rate_value = entry.get("rate")
        if rate_value is None:
            # Clear: delete all existing rates for this product
            existing = (await db.execute(
                select(PartyRate).where(
                    PartyRate.party_id == party_id,
                    PartyRate.product_id == product_id,
                )
            )).scalars().all()
            for row in existing:
                await db.delete(row)
            cleared += 1
        else:
            db.add(PartyRate(
                party_id=party_id,
                product_id=uuid.UUID(product_id) if isinstance(product_id, str) else product_id,
                rate=Decimal(str(rate_value)),
                effective_from=today,
            ))
            saved += 1

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
            Invoice.status != "cancelled",
        )
        .order_by(Invoice.invoice_date.desc(), Invoice.created_at.desc())
    )).scalars().all()

    # Lifetime metrics — sale invoices only define LTV/AOV
    sale_invoices = [i for i in inv_rows if i.invoice_type == "sale"]
    lifetime_sales = sum((i.grand_total or Decimal("0")) for i in sale_invoices)
    lifetime_paid = sum((i.amount_paid or Decimal("0")) for i in sale_invoices)
    lifetime_written_off = sum((i.write_off_amount or Decimal("0")) for i in sale_invoices)
    write_off_count = sum(1 for i in sale_invoices if (i.write_off_amount or Decimal("0")) > 0)
    invoice_count = len(sale_invoices)
    aov = (lifetime_sales / invoice_count) if invoice_count else Decimal("0")
    last_invoice_date = max((i.invoice_date for i in sale_invoices), default=None)
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

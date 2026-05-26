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
from app.schemas.party import (
    PartyCreate, PartyUpdate, PartyResponse,
    PartyRateCreate, PartyRateResponse,
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

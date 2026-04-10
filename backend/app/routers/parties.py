import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.party import Party, PartyRate
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
    current_user: User = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
):
    rate = PartyRate(party_id=party_id, **data.model_dump())
    db.add(rate)
    await db.commit()
    await db.refresh(rate)
    return PartyRateResponse.model_validate(rate)

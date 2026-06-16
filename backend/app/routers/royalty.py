"""Royalty / Mining Transit-Pass router (Horizon 2).

Tracks government royalty / e-transit passes and reconciles authorised quantity
against inbound purchase loads consumed against each pass.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.company import Company, FinancialYear
from app.models.party import Party
from app.models.royalty import RoyaltyPass, RoyaltyPassConsumption
from app.models.token import Token
from app.models.user import User
from app.schemas.royalty import (
    RoyaltyPassCreate, RoyaltyPassUpdate, RoyaltyPassResponse, RoyaltyPassListResponse,
    ConsumeRequest, RoyaltyReconciliation,
)

router = APIRouter(prefix="/api/v1/royalty", tags=["Royalty / Transit Pass"])


async def _company_fy(db: AsyncSession):
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    fy = (await db.execute(
        select(FinancialYear).where(FinancialYear.is_active == True).limit(1)
    )).scalar_one_or_none()
    return co, fy


async def _load(db: AsyncSession, pass_id: uuid.UUID) -> RoyaltyPass:
    p = (await db.execute(
        select(RoyaltyPass).options(selectinload(RoyaltyPass.consumptions))
        .where(RoyaltyPass.id == pass_id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Royalty pass not found")
    return p


async def _to_response(db: AsyncSession, p: RoyaltyPass) -> RoyaltyPassResponse:
    resp = RoyaltyPassResponse.model_validate(p)
    consumed = sum((c.quantity_mt or Decimal("0")) for c in p.consumptions)
    qty = p.quantity_mt or Decimal("0")
    resp.consumed_mt = consumed
    resp.balance_mt = qty - consumed
    resp.utilization_pct = float(round((consumed / qty * 100), 1)) if qty > 0 else 0.0
    if p.valid_till:
        resp.days_to_expiry = (p.valid_till - date.today()).days
    # Reflect derived status without persisting on read
    if p.status == "active" and p.valid_till and p.valid_till < date.today():
        resp.status = "expired"
    if p.party_id:
        resp.party_name = (await db.execute(select(Party.name).where(Party.id == p.party_id))).scalar_one_or_none()
    return resp


@router.post("/passes", response_model=RoyaltyPassResponse, status_code=201)
async def create_pass(
    payload: RoyaltyPassCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co, fy = await _company_fy(db)
    if not co:
        raise HTTPException(500, "Company not configured")
    p = RoyaltyPass(
        company_id=co.id, fy_id=fy.id if fy else None,
        pass_no=payload.pass_no.strip(),
        pass_type=payload.pass_type or "royalty",
        source_name=payload.source_name,
        party_id=payload.party_id,
        mineral=payload.mineral,
        product_id=payload.product_id,
        issue_date=payload.issue_date,
        valid_till=payload.valid_till,
        quantity_mt=Decimal(str(payload.quantity_mt or 0)),
        rate=Decimal(str(payload.rate or 0)),
        amount=Decimal(str(payload.amount or 0)),
        vehicle_no=(payload.vehicle_no or "").upper().strip() or None,
        notes=payload.notes,
        status="active",
        created_by=current_user.id,
    )
    db.add(p)
    await db.commit()
    p = await _load(db, p.id)
    return await _to_response(db, p)


@router.get("/passes", response_model=RoyaltyPassListResponse)
async def list_passes(
    status: str | None = None,
    pass_type: str | None = None,
    party_id: uuid.UUID | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(RoyaltyPass).where(RoyaltyPass.company_id == current_user.company_id)
    if status:
        stmt = stmt.where(RoyaltyPass.status == status)
    if pass_type:
        stmt = stmt.where(RoyaltyPass.pass_type == pass_type)
    if party_id:
        stmt = stmt.where(RoyaltyPass.party_id == party_id)
    if search:
        like = f"%{search.upper()}%"
        stmt = stmt.where(
            func.upper(RoyaltyPass.pass_no).like(like)
            | func.upper(func.coalesce(RoyaltyPass.source_name, "")).like(like)
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (await db.execute(
        stmt.options(selectinload(RoyaltyPass.consumptions))
        .order_by(RoyaltyPass.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    items = [await _to_response(db, p) for p in rows]
    return RoyaltyPassListResponse(items=items, total=int(total))


@router.get("/passes/{pass_id}", response_model=RoyaltyPassResponse)
async def get_pass(pass_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    return await _to_response(db, await _load(db, pass_id))


@router.put("/passes/{pass_id}", response_model=RoyaltyPassResponse)
async def update_pass(
    pass_id: uuid.UUID, payload: RoyaltyPassUpdate,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    p = await _load(db, pass_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    await db.commit()
    return await _to_response(db, await _load(db, pass_id))


@router.post("/passes/{pass_id}/cancel", response_model=RoyaltyPassResponse)
async def cancel_pass(pass_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    p = await _load(db, pass_id)
    p.status = "cancelled"
    await db.commit()
    return await _to_response(db, await _load(db, pass_id))


@router.post("/passes/{pass_id}/consume", response_model=RoyaltyPassResponse)
async def consume(
    pass_id: uuid.UUID, payload: ConsumeRequest,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Record a consumption against a pass (an inbound load drawn from it)."""
    p = await _load(db, pass_id)
    if p.status == "cancelled":
        raise HTTPException(400, "Cannot consume against a cancelled pass")
    qty = Decimal(str(payload.quantity_mt or 0))
    if qty <= 0:
        raise HTTPException(400, "quantity_mt must be greater than zero")
    db.add(RoyaltyPassConsumption(
        pass_id=p.id, company_id=p.company_id,
        token_id=payload.token_id, invoice_id=payload.invoice_id,
        quantity_mt=qty,
        consumed_date=payload.consumed_date or date.today(),
        notes=payload.notes, created_by=current_user.id,
    ))
    await db.flush()
    # Auto-exhaust when balance hits zero (overrun still allowed but flagged)
    consumed = sum((c.quantity_mt or Decimal("0")) for c in p.consumptions) + qty
    if p.quantity_mt and consumed >= p.quantity_mt and p.status == "active":
        p.status = "exhausted"
    await db.commit()
    return await _to_response(db, await _load(db, pass_id))


@router.get("/reconciliation", response_model=RoyaltyReconciliation)
async def reconciliation(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = current_user.company_id
    authorised = (await db.execute(
        select(func.coalesce(func.sum(RoyaltyPass.quantity_mt), 0)).where(
            RoyaltyPass.company_id == cid,
            RoyaltyPass.status != "cancelled",
            RoyaltyPass.issue_date >= date_from, RoyaltyPass.issue_date <= date_to,
        )
    )).scalar() or 0
    consumed = (await db.execute(
        select(func.coalesce(func.sum(RoyaltyPassConsumption.quantity_mt), 0)).where(
            RoyaltyPassConsumption.company_id == cid,
            RoyaltyPassConsumption.consumed_date >= date_from,
            RoyaltyPassConsumption.consumed_date <= date_to,
        )
    )).scalar() or 0
    # Purchase inbound = completed purchase tokens' net weight (kg → MT)
    inbound_kg = (await db.execute(
        select(func.coalesce(func.sum(Token.net_weight), 0)).where(
            Token.company_id == cid,
            Token.token_type == "purchase",
            Token.status == "COMPLETED",
            Token.token_date >= date_from, Token.token_date <= date_to,
        )
    )).scalar() or 0
    inbound_mt = float(inbound_kg) / 1000.0

    from datetime import timedelta
    soon = date.today() + timedelta(days=30)
    counts = (await db.execute(
        select(
            func.count(),
            func.count().filter(RoyaltyPass.status == "active"),
            func.count().filter(
                (RoyaltyPass.valid_till != None)  # noqa: E711
                & (RoyaltyPass.valid_till >= date.today())
                & (RoyaltyPass.valid_till <= soon)
            ),
        ).where(RoyaltyPass.company_id == cid, RoyaltyPass.status != "cancelled")
    )).first()

    return RoyaltyReconciliation(
        date_from=date_from, date_to=date_to,
        authorised_mt=float(authorised), consumed_mt=float(consumed),
        purchase_inbound_mt=round(inbound_mt, 3),
        balance_mt=float(authorised) - float(consumed),
        unaccounted_mt=round(inbound_mt - float(consumed), 3),
        pass_count=int(counts[0] or 0),
        active_count=int(counts[1] or 0),
        expiring_count=int(counts[2] or 0),
    )


@router.get("/alerts", response_model=RoyaltyPassListResponse)
async def alerts(
    within_days: int = Query(15, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Passes expiring within N days (or already expired) and not cancelled/exhausted."""
    from datetime import timedelta
    horizon = date.today() + timedelta(days=within_days)
    rows = (await db.execute(
        select(RoyaltyPass).options(selectinload(RoyaltyPass.consumptions))
        .where(
            RoyaltyPass.company_id == current_user.company_id,
            RoyaltyPass.status == "active",
            RoyaltyPass.valid_till != None,  # noqa: E711
            RoyaltyPass.valid_till <= horizon,
        )
        .order_by(RoyaltyPass.valid_till.asc())
    )).scalars().all()
    items = [await _to_response(db, p) for p in rows]
    return RoyaltyPassListResponse(items=items, total=len(items))

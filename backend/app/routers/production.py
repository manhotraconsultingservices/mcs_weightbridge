"""Production cycle router — yield + wastage tracking.

Workflow per cycle:
  1. Operator creates a cycle with input_kg + per-product outputs (draft).
  2. Optionally records intermediate stage1/2/3 weights to track wastage at each stage.
  3. Finalising the cycle posts each output as a stock-in movement in product_stock.

Endpoints:
  POST   /api/v1/production/cycles           — create draft
  GET    /api/v1/production/cycles           — list (paginated, filterable)
  GET    /api/v1/production/cycles/{id}      — detail
  PUT    /api/v1/production/cycles/{id}      — edit draft (rejected if finalised)
  POST   /api/v1/production/cycles/{id}/finalise  — finalise + post to product stock
  DELETE /api/v1/production/cycles/{id}      — delete (only drafts)
  GET    /api/v1/production/dashboard        — yield trend, wastage by stage, top products
"""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.company import Company
from app.models.product import Product
from app.models.production import ProductionCycle, ProductionCycleOutput
from app.schemas.production import (
    ProductionCycleCreate, ProductionCycleUpdate, ProductionCycleResponse,
    CycleOutputResponse, ProductionCycleListResponse,
    YieldTrendPoint, WastageStagePoint, ProductWastage, ProductionDashboardResponse,
)

router = APIRouter(prefix="/api/v1/production", tags=["Production"])


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _company(db: AsyncSession) -> Company:
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not co:
        raise HTTPException(500, "Company not configured")
    return co


def _compute_metrics(cycle: ProductionCycle, outputs: list[ProductionCycleOutput]) -> dict:
    total_output = sum((o.output_kg or Decimal("0")) for o in outputs) or Decimal("0")
    yield_pct = None
    if cycle.input_kg and cycle.input_kg > 0:
        yield_pct = float(total_output / cycle.input_kg * 100)
    belt_loss_pct = None
    if cycle.stage3_output_kg and cycle.stage3_output_kg > 0 and total_output is not None:
        belt_loss_pct = float((cycle.stage3_output_kg - total_output) / cycle.stage3_output_kg * 100)
    wastage = (cycle.input_kg or Decimal("0")) - total_output
    return {
        "total_output_kg": total_output,
        "yield_pct": yield_pct,
        "belt_loss_pct": belt_loss_pct,
        "wastage_kg": wastage,
    }


async def _load_cycle_response(db: AsyncSession, cycle_id: uuid.UUID) -> ProductionCycleResponse:
    cycle = (await db.execute(
        select(ProductionCycle)
        .options(selectinload(ProductionCycle.outputs))
        .where(ProductionCycle.id == cycle_id)
    )).scalar_one_or_none()
    if not cycle:
        raise HTTPException(404, "Cycle not found")

    # Resolve product names for outputs
    prod_ids = [o.product_id for o in cycle.outputs]
    name_map: dict[uuid.UUID, str] = {}
    if prod_ids:
        rows = (await db.execute(
            select(Product.id, Product.name).where(Product.id.in_(prod_ids))
        )).all()
        name_map = {r.id: r.name for r in rows}

    outputs_resp = [
        CycleOutputResponse(
            id=o.id, product_id=o.product_id,
            product_name=name_map.get(o.product_id, ""),
            output_kg=o.output_kg or Decimal("0"),
        )
        for o in cycle.outputs
    ]
    metrics = _compute_metrics(cycle, cycle.outputs)
    return ProductionCycleResponse(
        id=cycle.id, cycle_no=cycle.cycle_no, cycle_date=cycle.cycle_date,
        input_kg=cycle.input_kg,
        stage1_output_kg=cycle.stage1_output_kg,
        stage2_output_kg=cycle.stage2_output_kg,
        stage3_output_kg=cycle.stage3_output_kg,
        is_finalised=cycle.is_finalised, notes=cycle.notes,
        outputs=outputs_resp,
        created_at=cycle.created_at, updated_at=cycle.updated_at,
        **metrics,
    )


async def _next_cycle_no(db: AsyncSession, company_id: uuid.UUID) -> int:
    """Per-company sequential cycle_no; one cycle per day per CLAUDE.md decision."""
    result = await db.execute(
        select(func.coalesce(func.max(ProductionCycle.cycle_no), 0))
        .where(ProductionCycle.company_id == company_id)
    )
    return int(result.scalar() or 0) + 1


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/cycles", response_model=ProductionCycleResponse, status_code=status.HTTP_201_CREATED)
async def create_cycle(
    payload: ProductionCycleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "operator", "store_manager")),
):
    co = await _company(db)

    # Enforce one cycle per day (per the locked-in design)
    existing = (await db.execute(
        select(ProductionCycle.id).where(
            ProductionCycle.company_id == co.id,
            ProductionCycle.cycle_date == payload.cycle_date,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"A cycle already exists for {payload.cycle_date}. Edit it instead.")

    cycle = ProductionCycle(
        company_id=co.id,
        cycle_no=await _next_cycle_no(db, co.id),
        cycle_date=payload.cycle_date,
        input_kg=payload.input_kg,
        stage1_output_kg=payload.stage1_output_kg,
        stage2_output_kg=payload.stage2_output_kg,
        stage3_output_kg=payload.stage3_output_kg,
        notes=payload.notes,
        is_finalised=False,
        created_by=current_user.id,
    )
    db.add(cycle)
    await db.flush()

    for o in payload.outputs:
        db.add(ProductionCycleOutput(
            cycle_id=cycle.id, product_id=o.product_id, output_kg=o.output_kg,
        ))

    await db.commit()
    return await _load_cycle_response(db, cycle.id)


@router.get("/cycles", response_model=ProductionCycleListResponse)
async def list_cycles(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co = await _company(db)
    filters = [ProductionCycle.company_id == co.id]
    if date_from:
        filters.append(ProductionCycle.cycle_date >= date_from)
    if date_to:
        filters.append(ProductionCycle.cycle_date <= date_to)

    total = (await db.execute(
        select(func.count()).select_from(ProductionCycle).where(and_(*filters))
    )).scalar() or 0

    cycles = (await db.execute(
        select(ProductionCycle)
        .options(selectinload(ProductionCycle.outputs))
        .where(and_(*filters))
        .order_by(ProductionCycle.cycle_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()

    # Resolve product names in one query
    all_prod_ids = {o.product_id for c in cycles for o in c.outputs}
    name_map: dict[uuid.UUID, str] = {}
    if all_prod_ids:
        rows = (await db.execute(
            select(Product.id, Product.name).where(Product.id.in_(all_prod_ids))
        )).all()
        name_map = {r.id: r.name for r in rows}

    items = []
    for c in cycles:
        outputs_resp = [
            CycleOutputResponse(
                id=o.id, product_id=o.product_id,
                product_name=name_map.get(o.product_id, ""),
                output_kg=o.output_kg or Decimal("0"),
            )
            for o in c.outputs
        ]
        metrics = _compute_metrics(c, c.outputs)
        items.append(ProductionCycleResponse(
            id=c.id, cycle_no=c.cycle_no, cycle_date=c.cycle_date,
            input_kg=c.input_kg,
            stage1_output_kg=c.stage1_output_kg,
            stage2_output_kg=c.stage2_output_kg,
            stage3_output_kg=c.stage3_output_kg,
            is_finalised=c.is_finalised, notes=c.notes,
            outputs=outputs_resp,
            created_at=c.created_at, updated_at=c.updated_at,
            **metrics,
        ))

    return ProductionCycleListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/cycles/{cycle_id}", response_model=ProductionCycleResponse)
async def get_cycle(
    cycle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _load_cycle_response(db, cycle_id)


@router.put("/cycles/{cycle_id}", response_model=ProductionCycleResponse)
async def update_cycle(
    cycle_id: uuid.UUID,
    payload: ProductionCycleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "operator", "store_manager")),
):
    cycle = (await db.execute(
        select(ProductionCycle).where(ProductionCycle.id == cycle_id)
    )).scalar_one_or_none()
    if not cycle:
        raise HTTPException(404, "Cycle not found")
    if cycle.is_finalised:
        raise HTTPException(400, "Cannot edit a finalised cycle")

    for field in ("input_kg", "stage1_output_kg", "stage2_output_kg", "stage3_output_kg", "notes"):
        v = getattr(payload, field, None)
        if v is not None:
            setattr(cycle, field, v)

    if payload.outputs is not None:
        # Replace all outputs in one go
        existing = (await db.execute(
            select(ProductionCycleOutput).where(ProductionCycleOutput.cycle_id == cycle_id)
        )).scalars().all()
        for e in existing:
            await db.delete(e)
        await db.flush()
        for o in payload.outputs:
            db.add(ProductionCycleOutput(
                cycle_id=cycle_id, product_id=o.product_id, output_kg=o.output_kg,
            ))

    await db.commit()
    return await _load_cycle_response(db, cycle_id)


@router.post("/cycles/{cycle_id}/finalise", response_model=ProductionCycleResponse)
async def finalise_cycle(
    cycle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "operator", "store_manager")),
):
    cycle = (await db.execute(
        select(ProductionCycle)
        .options(selectinload(ProductionCycle.outputs))
        .where(ProductionCycle.id == cycle_id)
    )).scalar_one_or_none()
    if not cycle:
        raise HTTPException(404, "Cycle not found")
    if cycle.is_finalised:
        raise HTTPException(400, "Already finalised")
    if not cycle.outputs:
        raise HTTPException(400, "Cycle has no per-product outputs to post to stock")

    # Post stock-in movements for each output
    try:
        from app.routers.product_stock import post_cycle_outputs
        await post_cycle_outputs(
            db, cycle, cycle.outputs,
            user_id=current_user.id,
            user_name=current_user.full_name or current_user.username,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Stock post for cycle %s failed: %s", cycle_id, e)
        raise HTTPException(500, f"Failed to post stock movements: {e}")

    cycle.is_finalised = True
    await db.commit()
    return await _load_cycle_response(db, cycle_id)


@router.delete("/cycles/{cycle_id}", status_code=204)
async def delete_cycle(
    cycle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    cycle = (await db.execute(
        select(ProductionCycle).where(ProductionCycle.id == cycle_id)
    )).scalar_one_or_none()
    if not cycle:
        raise HTTPException(404, "Cycle not found")
    if cycle.is_finalised:
        raise HTTPException(400, "Cannot delete a finalised cycle. Create an adjustment instead.")
    await db.delete(cycle)
    await db.commit()


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=ProductionDashboardResponse)
async def get_dashboard(
    days: int = Query(30, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Yield % trend, wastage % by stage, top product outputs, and summary."""
    co = await _company(db)
    today = date.today()
    start = today - timedelta(days=days - 1)

    # Pull cycles in window with outputs loaded
    cycles = (await db.execute(
        select(ProductionCycle)
        .options(selectinload(ProductionCycle.outputs))
        .where(
            ProductionCycle.company_id == co.id,
            ProductionCycle.cycle_date >= start,
            ProductionCycle.cycle_date <= today,
        )
        .order_by(ProductionCycle.cycle_date)
    )).scalars().all()

    by_date: dict[date, ProductionCycle] = {c.cycle_date: c for c in cycles}

    # Yield trend
    yield_trend: list[YieldTrendPoint] = []
    cur = start
    while cur <= today:
        c = by_date.get(cur)
        if c and c.input_kg and c.input_kg > 0:
            total_out = float(sum(o.output_kg or 0 for o in c.outputs))
            yp = (total_out / float(c.input_kg)) * 100
            yield_trend.append(YieldTrendPoint(
                date=cur.strftime("%d %b"),
                yield_pct=round(yp, 2),
                input_kg=float(c.input_kg),
                output_kg=round(total_out, 2),
            ))
        else:
            yield_trend.append(YieldTrendPoint(
                date=cur.strftime("%d %b"), yield_pct=0, input_kg=0, output_kg=0,
            ))
        cur += timedelta(days=1)

    # Wastage by stage (where stage data is available)
    wastage_by_stage: list[WastageStagePoint] = []
    for c in cycles:
        if not c.input_kg or c.input_kg <= 0:
            continue
        inp = float(c.input_kg)
        s1 = float(c.stage1_output_kg or 0)
        s2 = float(c.stage2_output_kg or 0)
        s3 = float(c.stage3_output_kg or 0)
        out = float(sum(o.output_kg or 0 for o in c.outputs))
        wastage_by_stage.append(WastageStagePoint(
            date=c.cycle_date.strftime("%d %b"),
            stage1_loss_pct=round(max(0.0, (inp - s1) / inp * 100), 2) if s1 else 0.0,
            stage2_loss_pct=round(max(0.0, (s1 - s2) / s1 * 100), 2) if s1 and s2 else 0.0,
            stage3_loss_pct=round(max(0.0, (s2 - s3) / s2 * 100), 2) if s2 and s3 else 0.0,
            belt_loss_pct=round(max(0.0, (s3 - out) / s3 * 100), 2) if s3 and out else 0.0,
        ))

    # Top product outputs (by total kg, across the window)
    output_totals: dict[uuid.UUID, float] = {}
    output_counts: dict[uuid.UUID, int] = {}
    for c in cycles:
        for o in c.outputs:
            kg = float(o.output_kg or 0)
            output_totals[o.product_id] = output_totals.get(o.product_id, 0) + kg
            output_counts[o.product_id] = output_counts.get(o.product_id, 0) + 1
    name_rows = []
    if output_totals:
        name_rows = (await db.execute(
            select(Product.id, Product.name).where(Product.id.in_(output_totals.keys()))
        )).all()
    name_map = {r.id: r.name for r in name_rows}
    top_outputs = sorted(
        [
            ProductWastage(
                product_id=pid, product_name=name_map.get(pid, "?"),
                total_output_kg=round(v, 2),
                avg_output_per_cycle=round(v / output_counts.get(pid, 1), 2),
            )
            for pid, v in output_totals.items()
        ],
        key=lambda x: x.total_output_kg,
        reverse=True,
    )[:8]

    # Summary
    input_total = sum(float(c.input_kg or 0) for c in cycles)
    output_total = sum(float(o.output_kg or 0) for c in cycles for o in c.outputs)
    yields = [p.yield_pct for p in yield_trend if p.yield_pct > 0]
    belts = [w.belt_loss_pct for w in wastage_by_stage if w.belt_loss_pct > 0]
    summary = {
        "cycles_count": len(cycles),
        "input_total_kg": round(input_total, 2),
        "output_total_kg": round(output_total, 2),
        "avg_yield_pct": round(sum(yields) / len(yields), 2) if yields else 0,
        "avg_belt_loss_pct": round(sum(belts) / len(belts), 2) if belts else 0,
        "total_wastage_kg": round(input_total - output_total, 2),
    }

    return ProductionDashboardResponse(
        yield_trend=yield_trend,
        wastage_by_stage=wastage_by_stage,
        top_outputs=top_outputs,
        summary=summary,
    )

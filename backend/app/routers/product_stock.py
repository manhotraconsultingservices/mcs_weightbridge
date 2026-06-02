"""Finished-goods inventory router + auto-posting helpers.

Auto-postings (called from other routers):
  post_invoice_movement(db, invoice, action)  — fires on invoice finalise + cancel
  post_cycle_outputs(db, cycle, outputs)      — fires on production cycle finalise

Endpoints:
  GET    /api/v1/product-stock                — list (with status)
  GET    /api/v1/product-stock/movements      — paginated audit log
  PUT    /api/v1/product-stock/{id}/min-level — change reorder threshold
  POST   /api/v1/product-stock/adjust         — admin manual adjustment
  POST   /api/v1/product-stock/opening        — set opening stock (one-time)
  GET    /api/v1/product-stock/low            — low/out-of-stock items only (for dashboard)
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.product import Product
from app.models.product_stock import ProductStock, ProductStockMovement
from app.models.company import Company
from app.schemas.product_stock import (
    ProductStockResponse, ProductStockListResponse,
    UpdateMinStockRequest, StockAdjustmentRequest, OpeningStockRequest,
    MovementResponse, MovementListResponse,
)

router = APIRouter(prefix="/api/v1/product-stock", tags=["Product Stock"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stock_status(current: Decimal, min_level: Decimal) -> str:
    if current <= 0:
        return "out"
    if current <= min_level:
        return "low"
    return "ok"


async def _get_or_create_stock_row(db: AsyncSession, company_id: uuid.UUID,
                                   product_id: uuid.UUID) -> ProductStock:
    """Fetch the stock row for a product, creating it lazily if absent."""
    row = (await db.execute(
        select(ProductStock).where(ProductStock.product_id == product_id)
    )).scalar_one_or_none()
    if row:
        return row
    row = ProductStock(
        company_id=company_id, product_id=product_id,
        current_stock=Decimal("0"), min_stock_level=Decimal("0"),
    )
    db.add(row)
    await db.flush()
    return row


async def _record_movement(
    db: AsyncSession, company_id: uuid.UUID, product_id: uuid.UUID,
    movement_type: str, quantity: Decimal,
    reference_type: Optional[str] = None,
    reference_id: Optional[uuid.UUID] = None,
    reference_no: Optional[str] = None,
    notes: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    user_name: Optional[str] = None,
) -> ProductStockMovement:
    """Atomically apply a signed quantity to product_stock and record the movement."""
    stock = await _get_or_create_stock_row(db, company_id, product_id)
    before = stock.current_stock
    after = before + quantity
    stock.current_stock = after

    mv = ProductStockMovement(
        company_id=company_id, product_id=product_id,
        movement_type=movement_type, quantity=quantity,
        stock_before=before, stock_after=after,
        reference_type=reference_type, reference_id=reference_id,
        reference_no=reference_no, notes=notes,
        created_by=user_id, created_by_name=user_name,
    )
    db.add(mv)
    return mv


# ── Public hooks called from other routers ────────────────────────────────────

async def post_invoice_movement(
    db: AsyncSession, invoice, action: str,
    user_id: Optional[uuid.UUID] = None, user_name: Optional[str] = None,
) -> None:
    """Auto-post movements when an invoice is finalised or cancelled.

    Args:
        invoice: ORM Invoice (with `items` loaded)
        action: 'finalise' | 'cancel'

    Sale finalise   → -quantity  (stock goes down)
    Sale cancel     → +quantity  (stock comes back)
    Purchase finalise → +quantity (stock goes up)
    Purchase cancel   → -quantity
    """
    direction = -1 if invoice.invoice_type == "sale" else 1
    if action == "cancel":
        direction = -direction
        movement_type = f"{invoice.invoice_type}_cancelled"
    else:
        movement_type = invoice.invoice_type   # 'sale' | 'purchase'

    for item in invoice.items:
        # quantity stored on InvoiceItem is in product.unit (typically MT)
        signed = Decimal(str(item.quantity)) * Decimal(direction)
        await _record_movement(
            db, invoice.company_id, item.product_id,
            movement_type=movement_type,
            quantity=signed,
            reference_type="invoice",
            reference_id=invoice.id,
            reference_no=invoice.invoice_no,
            notes=f"Invoice {invoice.invoice_no or '(draft)'} {action}",
            user_id=user_id, user_name=user_name,
        )


async def post_cycle_outputs(
    db: AsyncSession, cycle, outputs: list,
    user_id: Optional[uuid.UUID] = None, user_name: Optional[str] = None,
) -> None:
    """Auto-post stock-in movements from a finalised production cycle.

    Args:
        cycle: ORM ProductionCycle
        outputs: list of ORM ProductionCycleOutput rows
    """
    for out in outputs:
        if not out.output_kg or out.output_kg <= 0:
            continue
        # output_kg is in kg; products are usually in MT — convert
        product = (await db.execute(
            select(Product).where(Product.id == out.product_id)
        )).scalar_one_or_none()
        if not product:
            continue
        qty = Decimal(str(out.output_kg))
        if product.unit == "MT":
            qty = qty / Decimal("1000")
        await _record_movement(
            db, cycle.company_id, out.product_id,
            movement_type="cycle_output",
            quantity=qty,
            reference_type="production_cycle",
            reference_id=cycle.id,
            reference_no=f"CYC/{cycle.cycle_date}/{cycle.cycle_no}",
            notes=f"Production cycle {cycle.cycle_date}",
            user_id=user_id, user_name=user_name,
        )


async def post_cycle_input(
    db: AsyncSession, cycle,
    user_id: Optional[uuid.UUID] = None, user_name: Optional[str] = None,
) -> None:
    """Auto-post a NEGATIVE stock movement for the raw material consumed by a
    finalised cycle. Mirror of post_cycle_outputs but for the input side.

    Skip silently if raw_material_id is None or input_kg is 0/null — keeps
    backward compat with legacy cycles that didn't track raw stock.
    """
    if not cycle.raw_material_id or not cycle.input_kg or cycle.input_kg <= 0:
        return
    product = (await db.execute(
        select(Product).where(Product.id == cycle.raw_material_id)
    )).scalar_one_or_none()
    if not product:
        return
    qty = Decimal(str(cycle.input_kg))
    if product.unit == "MT":
        qty = qty / Decimal("1000")
    await _record_movement(
        db, cycle.company_id, cycle.raw_material_id,
        movement_type="cycle_input",
        # Consumption is a stock-OUT — negate the qty.
        quantity=-qty,
        reference_type="production_cycle",
        reference_id=cycle.id,
        reference_no=f"CYC/{cycle.cycle_date}/{cycle.cycle_no}",
        notes=f"Production cycle {cycle.cycle_date} — raw material consumed",
        user_id=user_id, user_name=user_name,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

async def _company(db: AsyncSession) -> Company:
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not co:
        raise HTTPException(500, "Company not configured")
    return co


@router.get("", response_model=ProductStockListResponse)
async def list_stock(
    only: Optional[str] = Query(None, description="all | low | out"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co = await _company(db)

    # Join product_stock to products and left-join missing rows (products without stock yet)
    rows = (await db.execute(
        text("""
            SELECT p.id AS product_id, p.name, p.unit,
                   COALESCE(ps.id, gen_random_uuid()) AS id,
                   COALESCE(ps.current_stock, 0)    AS current_stock,
                   COALESCE(ps.min_stock_level, 0)  AS min_stock_level,
                   ps.last_alerted_at,
                   COALESCE(ps.updated_at, p.updated_at) AS updated_at
            FROM products p
            LEFT JOIN product_stock ps ON ps.product_id = p.id
            WHERE p.is_active = TRUE
              AND p.company_id = :cid
            ORDER BY p.name
        """),
        {"cid": str(co.id)},
    )).fetchall()

    items = []
    for r in rows:
        status = _stock_status(Decimal(str(r.current_stock)), Decimal(str(r.min_stock_level)))
        if only == "low" and status != "low":
            continue
        if only == "out" and status != "out":
            continue
        items.append(ProductStockResponse(
            id=r.id, product_id=r.product_id,
            product_name=r.name, unit=r.unit,
            current_stock=r.current_stock,
            min_stock_level=r.min_stock_level,
            stock_status=status,
            last_alerted_at=r.last_alerted_at,
            updated_at=r.updated_at,
        ))
    return ProductStockListResponse(items=items, total=len(items))


@router.get("/low", response_model=ProductStockListResponse)
async def list_low_stock(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Just the products that are low or out — for the dashboard widget."""
    co = await _company(db)
    rows = (await db.execute(
        text("""
            SELECT p.id AS product_id, p.name, p.unit,
                   ps.id, ps.current_stock, ps.min_stock_level,
                   ps.last_alerted_at, ps.updated_at
            FROM product_stock ps
            JOIN products p ON p.id = ps.product_id
            WHERE p.is_active = TRUE
              AND p.company_id = :cid
              AND ps.current_stock <= ps.min_stock_level
            ORDER BY (ps.current_stock - ps.min_stock_level), p.name
        """),
        {"cid": str(co.id)},
    )).fetchall()
    items = [
        ProductStockResponse(
            id=r.id, product_id=r.product_id,
            product_name=r.name, unit=r.unit,
            current_stock=r.current_stock,
            min_stock_level=r.min_stock_level,
            stock_status=_stock_status(Decimal(str(r.current_stock)), Decimal(str(r.min_stock_level))),
            last_alerted_at=r.last_alerted_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    return ProductStockListResponse(items=items, total=len(items))


@router.put("/{product_id}/min-level", response_model=ProductStockResponse)
async def update_min_level(
    product_id: uuid.UUID,
    payload: UpdateMinStockRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "store_manager", "accountant")),
):
    co = await _company(db)
    stock = await _get_or_create_stock_row(db, co.id, product_id)
    stock.min_stock_level = payload.min_stock_level
    await db.commit()
    # Re-load with attributes alive (commit expired them) — fetch product + stock fresh
    product = (await db.execute(select(Product).where(Product.id == product_id))).scalar_one()
    stock = (await db.execute(
        select(ProductStock).where(ProductStock.product_id == product_id)
    )).scalar_one()
    return ProductStockResponse(
        id=stock.id, product_id=product_id,
        product_name=product.name, unit=product.unit,
        current_stock=stock.current_stock,
        min_stock_level=stock.min_stock_level,
        stock_status=_stock_status(stock.current_stock, stock.min_stock_level),
        last_alerted_at=stock.last_alerted_at,
        updated_at=stock.updated_at,
    )


@router.post("/adjust", status_code=201)
async def adjust_stock(
    payload: StockAdjustmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "store_manager")),
):
    """Admin/store_manager manual adjustment (e.g. shrinkage, recount)."""
    if payload.quantity == 0:
        raise HTTPException(400, "Quantity must not be zero")
    co = await _company(db)
    stock = await _get_or_create_stock_row(db, co.id, payload.product_id)
    if stock.current_stock + payload.quantity < 0:
        raise HTTPException(400, f"Adjustment would make stock negative ({stock.current_stock} + {payload.quantity})")

    await _record_movement(
        db, co.id, payload.product_id,
        movement_type="adjustment",
        quantity=payload.quantity,
        notes=payload.reason,
        user_id=current_user.id, user_name=current_user.full_name or current_user.username,
    )
    await db.commit()
    return {"ok": True, "new_stock": float(stock.current_stock + payload.quantity)}


@router.post("/opening", status_code=201)
async def set_opening_stock(
    payload: OpeningStockRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "store_manager")),
):
    """Set the opening (initial) stock for a product.  Only allowed when
    current_stock = 0 — otherwise use /adjust to change it."""
    co = await _company(db)
    stock = await _get_or_create_stock_row(db, co.id, payload.product_id)
    if stock.current_stock != 0:
        raise HTTPException(
            400,
            f"Opening stock can only be set when current_stock is 0 (currently {stock.current_stock}). "
            f"Use /adjust to change non-zero stock.",
        )
    await _record_movement(
        db, co.id, payload.product_id,
        movement_type="opening",
        quantity=payload.opening_quantity,
        notes=payload.notes or "Opening stock",
        user_id=current_user.id, user_name=current_user.full_name or current_user.username,
    )
    await db.commit()
    return {"ok": True, "new_stock": float(payload.opening_quantity)}


@router.get("/movements", response_model=MovementListResponse)
async def list_movements(
    product_id: Optional[uuid.UUID] = None,
    movement_type: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co = await _company(db)
    filters = [ProductStockMovement.company_id == co.id]
    if product_id:
        filters.append(ProductStockMovement.product_id == product_id)
    if movement_type:
        filters.append(ProductStockMovement.movement_type == movement_type)
    if date_from:
        filters.append(func.date(ProductStockMovement.created_at) >= date_from)
    if date_to:
        filters.append(func.date(ProductStockMovement.created_at) <= date_to)

    total = (await db.execute(
        select(func.count()).select_from(ProductStockMovement).where(and_(*filters))
    )).scalar() or 0

    rows = (await db.execute(
        select(ProductStockMovement, Product.name)
        .join(Product, Product.id == ProductStockMovement.product_id)
        .where(and_(*filters))
        .order_by(ProductStockMovement.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).all()

    items = []
    for mv, pname in rows:
        items.append(MovementResponse(
            id=mv.id, product_id=mv.product_id, product_name=pname,
            movement_type=mv.movement_type, quantity=mv.quantity,
            stock_before=mv.stock_before, stock_after=mv.stock_after,
            reference_type=mv.reference_type, reference_id=mv.reference_id,
            reference_no=mv.reference_no, notes=mv.notes,
            created_by_name=mv.created_by_name, created_at=mv.created_at,
        ))
    return MovementListResponse(items=items, total=total, page=page, page_size=page_size)

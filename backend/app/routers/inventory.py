"""
Inventory Management — Raw materials (Fuel, Electricity, Parts, Tools).
Tracks stock levels, purchase orders, receipts, and consumption.
Daily Telegram report is handled by the background loop in main.py.
"""
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.company import Company, FinancialYear
from app.models.inventory import InventoryItem, InventoryTransaction, InventoryPurchaseOrder, InventoryPOItem, InventoryItemSupplier, InventorySupplier
from app.models.settings import NumberSequence
from app.models.user import User
from app.schemas.inventory import (
    AdjustStockRequest,
    CategoryListResponse,
    CategoryUpdateRequest,
    InventoryDashboardResponse,
    InventoryItemCreate,
    InventoryItemResponse,
    InventoryItemUpdate,
    InventoryTransactionResponse,
    IssueStockRequest,
    ItemSupplierCreate,
    ItemSupplierResponse,
    ItemSupplierUpdate,
    MasterSupplierCreate,
    MasterSupplierUpdate,
    MasterSupplierResponse,
    POItemResponse,
    PurchaseOrderCreate,
    PurchaseOrderListResponse,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
    ReceiveGoodsRequest,
    RejectPORequest,
    TelegramSettings,
    TelegramSettingsSave,
    TransactionListResponse,
)

# Roles that can manage inventory (admin + store_manager)
_INV_MANAGERS = ("admin", "store_manager")

router = APIRouter(prefix="/api/v1/inventory", tags=["Inventory"])

# ── app_settings keys ─────────────────────────────────────────────────────────
_TG_TOKEN_KEY    = "inventory.telegram_bot_token"
_TG_CHAT_KEY     = "inventory.telegram_chat_id"
_TG_TIME_KEY     = "inventory.telegram_report_time"
_TG_ENABLED_KEY  = "inventory.telegram_enabled"
_CATEGORIES_KEY  = "inventory.categories"

DEFAULT_CATEGORIES = ["fuel", "electricity", "parts", "tools", "other"]

# PO statuses that are considered "open" (block item deletion)
_OPEN_PO_STATUSES = ("pending_approval", "approved", "partially_received")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_company(db: AsyncSession) -> Company:
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not co:
        raise HTTPException(500, "Company not configured")
    return co


async def _get_active_fy(db: AsyncSession, company_id: uuid.UUID) -> Optional[FinancialYear]:
    result = await db.execute(
        select(FinancialYear)
        .where(FinancialYear.company_id == company_id, FinancialYear.is_active == True)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _upsert_setting(db: AsyncSession, key: str, value: str) -> None:
    await db.execute(
        text("""
            INSERT INTO app_settings (key, value)
            VALUES (:key, :value)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """),
        {"key": key, "value": value},
    )


async def _get_raw(db: AsyncSession, key: str) -> Optional[str]:
    row = (await db.execute(
        text("SELECT value FROM app_settings WHERE key = :k"), {"k": key}
    )).fetchone()
    return row[0] if row else None


async def _get_categories(db: AsyncSession) -> List[str]:
    try:
        raw = await _get_raw(db, _CATEGORIES_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return DEFAULT_CATEGORIES


def _compute_stock_status(current: Decimal, min_level: Decimal) -> str:
    if current <= 0:
        return "out"
    if current <= min_level:
        return "low"
    return "ok"


def _to_item_response(
    item: InventoryItem,
    suppliers: Optional[List[InventoryItemSupplier]] = None,
) -> InventoryItemResponse:
    status = _compute_stock_status(item.current_stock, item.min_stock_level)
    return InventoryItemResponse(
        id=item.id,
        name=item.name,
        category=item.category,
        unit=item.unit,
        current_stock=item.current_stock,
        min_stock_level=item.min_stock_level,
        reorder_quantity=getattr(item, "reorder_quantity", Decimal("0")) or Decimal("0"),
        auto_po_enabled=getattr(item, "auto_po_enabled", False) or False,
        description=item.description,
        is_active=item.is_active,
        stock_status=status,
        suppliers=[
            ItemSupplierResponse(
                id=s.id,
                item_id=s.item_id,
                master_supplier_id=getattr(s, 'master_supplier_id', None),
                supplier_name=s.supplier_name,
                is_preferred=s.is_preferred,
                lead_time_days=s.lead_time_days,
                agreed_unit_price=s.agreed_unit_price,
                moq=s.moq,
                notes=s.notes,
                is_active=s.is_active,
            )
            for s in (suppliers or [])
        ],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _fetch_suppliers_map(
    db: AsyncSession,
    item_ids: List[uuid.UUID],
) -> dict:
    """Bulk-fetch active suppliers for multiple items. Returns {str(item_id): [supplier, ...]}."""
    if not item_ids:
        return {}
    rows = (await db.execute(
        select(InventoryItemSupplier)
        .where(
            InventoryItemSupplier.item_id.in_(item_ids),
            InventoryItemSupplier.is_active == True,
        )
        .order_by(InventoryItemSupplier.is_preferred.desc(), InventoryItemSupplier.supplier_name)
    )).scalars().all()
    result: dict = {}
    for s in rows:
        result.setdefault(str(s.item_id), []).append(s)
    return result


async def _next_po_number(db: AsyncSession, company_id: uuid.UUID, fy_id: uuid.UUID) -> str:
    """Gap-free PO numbering reusing the NumberSequence table with row-level locking."""
    result = await db.execute(
        select(NumberSequence)
        .where(
            NumberSequence.company_id == company_id,
            NumberSequence.fy_id == fy_id,
            NumberSequence.sequence_type == "inventory_po",
        )
        .with_for_update()
    )
    seq = result.scalar_one_or_none()
    if not seq:
        seq = NumberSequence(
            company_id=company_id,
            fy_id=fy_id,
            sequence_type="inventory_po",
            prefix="PO",
            last_number=0,
            reset_daily=False,
        )
        db.add(seq)
    seq.last_number += 1
    await db.flush()
    fy_row = await db.get(FinancialYear, fy_id)
    fy_label = fy_row.label if fy_row else "25-26"
    short_fy = fy_label[-5:] if fy_label else "25-26"
    return f"PO/{short_fy}/{seq.last_number:04d}"


def _po_to_response(po: InventoryPurchaseOrder, po_items: List[InventoryPOItem]) -> PurchaseOrderResponse:
    items = [
        POItemResponse(
            id=pi.id,
            item_id=pi.item_id,
            item_name=pi.item_name,
            unit=pi.unit,
            quantity_ordered=pi.quantity_ordered,
            quantity_received=pi.quantity_received,
            unit_price=pi.unit_price,
        )
        for pi in po_items
    ]
    return PurchaseOrderResponse(
        id=po.id,
        po_no=po.po_no,
        status=po.status,
        supplier_name=po.supplier_name,
        expected_date=po.expected_date,
        notes=po.notes,
        requested_by_name=po.requested_by_name,
        approved_by_name=po.approved_by_name,
        approved_at=po.approved_at,
        rejection_reason=po.rejection_reason,
        is_auto_generated=getattr(po, "is_auto_generated", False) or False,
        created_at=po.created_at,
        updated_at=po.updated_at,
        items=items,
    )


def _txn_to_response(txn: InventoryTransaction, item_name: str) -> InventoryTransactionResponse:
    return InventoryTransactionResponse(
        id=txn.id,
        item_id=txn.item_id,
        item_name=item_name,
        transaction_type=txn.transaction_type,
        quantity=txn.quantity,
        stock_before=txn.stock_before,
        stock_after=txn.stock_after,
        reference_no=txn.reference_no,
        notes=txn.notes,
        created_by_name=txn.created_by_name,
        used_by_name=getattr(txn, "used_by_name", None),
        used_on=getattr(txn, "used_on", None),
        created_at=txn.created_at,
    )


async def _maybe_trigger_auto_po(
    db: AsyncSession,
    item: InventoryItem,
    co: Company,
) -> None:
    """
    Best-effort auto-PO creation:
    If auto_po_enabled, reorder_quantity > 0, stock just hit/crossed min_stock_level,
    AND no open PO already exists for this item → create a pending_approval PO automatically.
    Silently swallows all errors so the stock movement always succeeds.
    Must NOT call db.commit() — the caller owns the transaction.
    """
    try:
        if not getattr(item, "auto_po_enabled", False):
            return
        reorder_qty = getattr(item, "reorder_quantity", Decimal("0")) or Decimal("0")
        if reorder_qty <= 0:
            return
        if item.current_stock > item.min_stock_level:
            return  # Stock still above minimum — no reorder needed

        # Check whether an open PO already covers this item
        existing = (await db.execute(
            text("""
                SELECT COUNT(*) FROM inventory_po_items pi
                JOIN inventory_purchase_orders po ON po.id = pi.po_id
                WHERE pi.item_id = :iid AND po.company_id = :cid
                  AND po.status IN ('pending_approval', 'approved', 'partially_received')
            """),
            {"iid": str(item.id), "cid": str(co.id)},
        )).scalar() or 0

        if existing > 0:
            return  # Duplicate guard — an open PO for this item already exists

        fy = await _get_active_fy(db, co.id)
        if not fy:
            return  # No active financial year; skip silently

        po_no = await _next_po_number(db, co.id, fy.id)
        notes = (
            f"⚠️ Auto-generated reorder: {item.name} stock dropped to "
            f"{item.current_stock} {item.unit} (minimum: {item.min_stock_level} {item.unit}). "
            f"Reorder quantity: {reorder_qty} {item.unit}."
        )
        po = InventoryPurchaseOrder(
            company_id=co.id,
            po_no=po_no,
            status="pending_approval",
            notes=notes,
            requested_by=None,
            requested_by_name="System (Auto-reorder)",
            is_auto_generated=True,
        )
        db.add(po)
        await db.flush()  # get po.id without committing

        pi = InventoryPOItem(
            po_id=po.id,
            item_id=item.id,
            item_name=item.name,
            unit=item.unit,
            quantity_ordered=reorder_qty,
            quantity_received=Decimal("0"),
        )
        db.add(pi)
        # Caller will commit — both the stock movement and this PO land in one transaction
    except Exception:
        pass  # Best-effort: stock movement must not fail because of auto-PO logic


# ── Item endpoints ─────────────────────────────────────────────────────────────

@router.get("/items", response_model=List[InventoryItemResponse])
async def list_items(
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="ok|low|out"),
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co = await _get_company(db)
    q = select(InventoryItem).where(InventoryItem.company_id == co.id)
    if not include_inactive:
        q = q.where(InventoryItem.is_active == True)
    if category:
        q = q.where(InventoryItem.category == category)
    q = q.order_by(InventoryItem.category, InventoryItem.name)
    rows = (await db.execute(q)).scalars().all()
    supplier_map = await _fetch_suppliers_map(db, [r.id for r in rows])
    results = [_to_item_response(r, supplier_map.get(str(r.id), [])) for r in rows]
    if status:
        results = [r for r in results if r.stock_status == status]
    return results


@router.post("/items", response_model=InventoryItemResponse, status_code=201)
async def create_item(
    payload: InventoryItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    co = await _get_company(db)
    categories = await _get_categories(db)
    if payload.category not in categories:
        raise HTTPException(400, f"Invalid category '{payload.category}'. Valid: {categories}")

    item = InventoryItem(
        company_id=co.id,
        name=payload.name.strip(),
        category=payload.category,
        unit=payload.unit.strip(),
        current_stock=Decimal("0"),
        min_stock_level=payload.min_stock_level,
        reorder_quantity=payload.reorder_quantity,
        auto_po_enabled=payload.auto_po_enabled,
        description=payload.description,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _to_item_response(item, [])


@router.put("/items/{item_id}", response_model=InventoryItemResponse)
async def update_item(
    item_id: uuid.UUID,
    payload: InventoryItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(404, "Item not found")

    if payload.category is not None:
        categories = await _get_categories(db)
        if payload.category not in categories:
            raise HTTPException(400, f"Invalid category '{payload.category}'. Valid: {categories}")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(item, field, value)

    await db.commit()
    await db.refresh(item)
    sups = (await _fetch_suppliers_map(db, [item.id])).get(str(item.id), [])
    return _to_item_response(item, sups)


# ── Master supplier endpoints ──────────────────────────────────────────────────

@router.get("/suppliers", response_model=List[MasterSupplierResponse])
async def list_master_suppliers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all active master suppliers."""
    co = await _get_company(db)
    rows = (await db.execute(
        select(InventorySupplier)
        .where(InventorySupplier.is_active == True)
        .order_by(InventorySupplier.name)
    )).scalars().all()
    return list(rows)


@router.post("/suppliers", response_model=MasterSupplierResponse, status_code=201)
async def create_master_supplier(
    payload: MasterSupplierCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    """Add a new supplier to the master list."""
    co = await _get_company(db)
    sup = InventorySupplier(
        company_id=co.id,
        name=payload.name.strip(),
        contact_person=payload.contact_person,
        phone=payload.phone,
        email=payload.email,
        notes=payload.notes,
    )
    db.add(sup)
    await db.commit()
    await db.refresh(sup)
    return sup


@router.put("/suppliers/{supplier_id}", response_model=MasterSupplierResponse)
async def update_master_supplier(
    supplier_id: uuid.UUID,
    payload: MasterSupplierUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    sup = await db.get(InventorySupplier, supplier_id)
    if not sup:
        raise HTTPException(404, "Supplier not found")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(sup, k, v)
    await db.commit()
    await db.refresh(sup)
    return sup


@router.delete("/suppliers/{supplier_id}", status_code=204)
async def delete_master_supplier(
    supplier_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    sup = await db.get(InventorySupplier, supplier_id)
    if not sup:
        raise HTTPException(404, "Supplier not found")
    sup.is_active = False
    await db.commit()


# ── Item supplier endpoints ────────────────────────────────────────────────────

@router.get("/items/supplier-names")
async def list_all_supplier_names(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Master supplier names for PO autocomplete."""
    rows = (await db.execute(
        text("SELECT id, name FROM inventory_suppliers WHERE is_active=TRUE ORDER BY name")
    )).fetchall()
    return {"suppliers": [{"id": str(r[0]), "name": r[1]} for r in rows]}


@router.get("/items/{item_id}/suppliers", response_model=List[ItemSupplierResponse])
async def list_item_suppliers(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    rows = (await db.execute(
        select(InventoryItemSupplier)
        .where(InventoryItemSupplier.item_id == item_id)
        .order_by(InventoryItemSupplier.is_preferred.desc(), InventoryItemSupplier.supplier_name)
    )).scalars().all()
    return list(rows)


@router.post("/items/{item_id}/suppliers", response_model=ItemSupplierResponse, status_code=201)
async def add_item_supplier(
    item_id: uuid.UUID,
    payload: ItemSupplierCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    if payload.is_preferred:
        # Unset preferred flag on all other suppliers for this item
        await db.execute(
            text("UPDATE inventory_item_suppliers SET is_preferred=FALSE WHERE item_id=:iid"),
            {"iid": str(item_id)},
        )
    supplier = InventoryItemSupplier(
        item_id=item_id,
        master_supplier_id=payload.master_supplier_id,
        supplier_name=payload.supplier_name.strip(),
        is_preferred=payload.is_preferred,
        lead_time_days=payload.lead_time_days,
        agreed_unit_price=payload.agreed_unit_price,
        moq=payload.moq,
        notes=payload.notes,
    )
    db.add(supplier)
    await db.commit()
    await db.refresh(supplier)
    return ItemSupplierResponse(
        id=supplier.id,
        item_id=supplier.item_id,
        master_supplier_id=getattr(supplier, 'master_supplier_id', None),
        supplier_name=supplier.supplier_name,
        is_preferred=supplier.is_preferred,
        lead_time_days=supplier.lead_time_days,
        agreed_unit_price=supplier.agreed_unit_price,
        moq=supplier.moq,
        notes=supplier.notes,
        is_active=supplier.is_active,
    )


@router.put("/items/{item_id}/suppliers/{supplier_id}", response_model=ItemSupplierResponse)
async def update_item_supplier(
    item_id: uuid.UUID,
    supplier_id: uuid.UUID,
    payload: ItemSupplierUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    s = await db.get(InventoryItemSupplier, supplier_id)
    if not s or s.item_id != item_id:
        raise HTTPException(404, "Supplier not found")
    if payload.is_preferred:
        await db.execute(
            text("UPDATE inventory_item_suppliers SET is_preferred=FALSE WHERE item_id=:iid AND id != :sid"),
            {"iid": str(item_id), "sid": str(supplier_id)},
        )
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(s, k, v)
    await db.commit()
    await db.refresh(s)
    return s


@router.delete("/items/{item_id}/suppliers/{supplier_id}", status_code=204)
async def delete_item_supplier(
    item_id: uuid.UUID,
    supplier_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    s = await db.get(InventoryItemSupplier, supplier_id)
    if not s or s.item_id != item_id:
        raise HTTPException(404, "Supplier not found")
    s.is_active = False
    await db.commit()


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(404, "Item not found")

    # Block deletion if there are open POs for this item
    open_po_count = (await db.execute(
        text("""
            SELECT COUNT(*) FROM inventory_po_items pi
            JOIN inventory_purchase_orders po ON po.id = pi.po_id
            WHERE pi.item_id = :iid AND po.status IN ('pending_approval','approved','partially_received')
        """),
        {"iid": str(item_id)},
    )).scalar()
    if open_po_count and open_po_count > 0:
        raise HTTPException(400, "Cannot delete item with open purchase orders")

    item.is_active = False
    await db.commit()


# ── Stock movement endpoints ──────────────────────────────────────────────────

@router.post("/issue", response_model=InventoryTransactionResponse, status_code=201)
async def issue_stock(
    payload: IssueStockRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Consume (issue) stock — atomically locked to prevent overshooting."""
    # Lock the row before reading stock level
    result = await db.execute(
        select(InventoryItem)
        .where(InventoryItem.id == payload.item_id, InventoryItem.is_active == True)
        .with_for_update()
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found or inactive")

    if item.current_stock < payload.quantity:
        raise HTTPException(
            400,
            f"Insufficient stock. Available: {item.current_stock} {item.unit}",
        )

    co = await _get_company(db)
    stock_before = item.current_stock
    item.current_stock = item.current_stock - payload.quantity

    from datetime import date as _date
    txn = InventoryTransaction(
        company_id=co.id,
        item_id=item.id,
        transaction_type="issue",
        quantity=-payload.quantity,   # negative = out
        stock_before=stock_before,
        stock_after=item.current_stock,
        notes=payload.notes,
        created_by=current_user.id,
        created_by_name=getattr(current_user, "full_name", None) or current_user.username,
        used_by_name=payload.used_by_name or None,
        used_on=payload.used_on or _date.today(),
    )
    db.add(txn)
    # Auto-PO: if stock just hit/crossed the minimum level, create a draft PO for admin approval
    await _maybe_trigger_auto_po(db, item, co)
    await db.commit()
    await db.refresh(txn)
    return _txn_to_response(txn, item.name)


@router.post("/adjust", response_model=InventoryTransactionResponse, status_code=201)
async def adjust_stock(
    payload: AdjustStockRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    """Manual stock adjustment (positive = add, negative = remove). Admin only."""
    result = await db.execute(
        select(InventoryItem)
        .where(InventoryItem.id == payload.item_id, InventoryItem.is_active == True)
        .with_for_update()
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found or inactive")

    new_stock = item.current_stock + payload.quantity
    if new_stock < 0:
        raise HTTPException(400, f"Adjustment would result in negative stock ({new_stock})")

    co = await _get_company(db)
    stock_before = item.current_stock
    item.current_stock = new_stock

    txn = InventoryTransaction(
        company_id=co.id,
        item_id=item.id,
        transaction_type="adjustment",
        quantity=payload.quantity,
        stock_before=stock_before,
        stock_after=item.current_stock,
        notes=payload.reason,
        created_by=current_user.id,
        created_by_name=getattr(current_user, "full_name", None) or current_user.username,
    )
    db.add(txn)
    # Auto-PO check only when adjustment reduced stock (negative quantity)
    if payload.quantity < 0:
        await _maybe_trigger_auto_po(db, item, co)
    await db.commit()
    await db.refresh(txn)
    return _txn_to_response(txn, item.name)


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(
    item_id: Optional[uuid.UUID] = Query(None),
    transaction_type: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co = await _get_company(db)

    # Build WHERE clauses for raw SQL (simpler for JOIN + filters)
    conditions = ["t.company_id = :cid"]
    params: dict = {"cid": str(co.id)}

    if item_id:
        conditions.append("t.item_id = :iid")
        params["iid"] = str(item_id)
    if transaction_type:
        conditions.append("t.transaction_type = :ttype")
        params["ttype"] = transaction_type
    if date_from:
        conditions.append("DATE(t.created_at) >= :df")
        params["df"] = str(date_from)
    if date_to:
        conditions.append("DATE(t.created_at) <= :dt")
        params["dt"] = str(date_to)

    where = " AND ".join(conditions)

    total_row = (await db.execute(
        text(f"SELECT COUNT(*) FROM inventory_transactions t WHERE {where}"), params
    )).scalar() or 0

    offset = (page - 1) * page_size
    rows = (await db.execute(
        text(f"""
            SELECT t.id, t.item_id, i.name AS item_name,
                   t.transaction_type, t.quantity, t.stock_before, t.stock_after,
                   t.reference_no, t.notes, t.created_by_name,
                   t.used_by_name, t.used_on, t.created_at
            FROM inventory_transactions t
            JOIN inventory_items i ON i.id = t.item_id
            WHERE {where}
            ORDER BY t.created_at DESC
            LIMIT :lim OFFSET :off
        """),
        {**params, "lim": page_size, "off": offset},
    )).fetchall()

    txns = [
        InventoryTransactionResponse(
            id=r[0],
            item_id=r[1],
            item_name=r[2],
            transaction_type=r[3],
            quantity=r[4],
            stock_before=r[5],
            stock_after=r[6],
            reference_no=r[7],
            notes=r[8],
            created_by_name=r[9],
            used_by_name=r[10],
            used_on=r[11],
            created_at=r[12],
        )
        for r in rows
    ]
    return TransactionListResponse(items=txns, total=total_row, page=page, page_size=page_size)


# ── Purchase Order endpoints ───────────────────────────────────────────────────

@router.post("/purchase-orders", response_model=PurchaseOrderResponse, status_code=201)
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co = await _get_company(db)
    fy = await _get_active_fy(db, co.id)
    if not fy:
        raise HTTPException(400, "No active financial year configured")

    # Validate all item_ids exist and are active; collect names+units
    po_items_data = []
    for line in payload.items:
        item = await db.get(InventoryItem, line.item_id)
        if not item or not item.is_active:
            raise HTTPException(400, f"Item {line.item_id} not found or inactive")
        po_items_data.append({
            "item": item,
            "quantity_ordered": line.quantity_ordered,
            "unit_price": line.unit_price,
        })

    po_no = await _next_po_number(db, co.id, fy.id)
    by_name = getattr(current_user, "full_name", None) or current_user.username

    po = InventoryPurchaseOrder(
        company_id=co.id,
        po_no=po_no,
        status="pending_approval",
        supplier_name=payload.supplier_name,
        expected_date=payload.expected_date,
        notes=payload.notes,
        requested_by=current_user.id,
        requested_by_name=by_name,
    )
    db.add(po)
    await db.flush()  # get po.id

    po_items = []
    for d in po_items_data:
        pi = InventoryPOItem(
            po_id=po.id,
            item_id=d["item"].id,
            item_name=d["item"].name,
            unit=d["item"].unit,
            quantity_ordered=d["quantity_ordered"],
            quantity_received=Decimal("0"),
            unit_price=d["unit_price"],
        )
        db.add(pi)
        po_items.append(pi)

    await db.commit()
    await db.refresh(po)
    for pi in po_items:
        await db.refresh(pi)

    return _po_to_response(po, po_items)


@router.put("/purchase-orders/{po_id}", response_model=PurchaseOrderResponse)
async def edit_purchase_order(
    po_id: uuid.UUID,
    payload: PurchaseOrderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    """Edit a purchase order that is still pending approval. Replaces line items if provided."""
    co = await _get_company(db)
    po = await db.get(InventoryPurchaseOrder, po_id)
    if not po or po.company_id != co.id:
        raise HTTPException(404, "Purchase order not found")
    if po.status != "pending_approval":
        raise HTTPException(400, f"Cannot edit a PO with status '{po.status}' — only pending_approval POs can be edited")

    # Update header fields
    if payload.supplier_name is not None:
        po.supplier_name = payload.supplier_name or None
    if payload.expected_date is not None:
        po.expected_date = payload.expected_date
    if payload.notes is not None:
        po.notes = payload.notes or None

    # Replace line items if provided
    if payload.items is not None:
        if len(payload.items) == 0:
            raise HTTPException(400, "At least one item is required")
        # Delete existing items
        await db.execute(
            text("DELETE FROM inventory_po_items WHERE po_id = :pid"),
            {"pid": str(po_id)},
        )
        # Validate and insert new items
        new_po_items = []
        for line in payload.items:
            item = await db.get(InventoryItem, line.item_id)
            if not item or not item.is_active:
                raise HTTPException(400, f"Item {line.item_id} not found or inactive")
            pi = InventoryPOItem(
                po_id=po.id,
                item_id=item.id,
                item_name=item.name,
                unit=item.unit,
                quantity_ordered=line.quantity_ordered,
                quantity_received=Decimal("0"),
                unit_price=line.unit_price,
            )
            db.add(pi)
            new_po_items.append(pi)
        await db.flush()
        await db.commit()
        await db.refresh(po)
        for pi in new_po_items:
            await db.refresh(pi)
        return _po_to_response(po, new_po_items)

    await db.commit()
    await db.refresh(po)
    # Re-fetch line items
    pi_rows = (await db.execute(
        select(InventoryPOItem).where(InventoryPOItem.po_id == po.id)
    )).scalars().all()
    return _po_to_response(po, list(pi_rows))


@router.get("/purchase-orders", response_model=PurchaseOrderListResponse)
async def list_purchase_orders(
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co = await _get_company(db)
    q = select(InventoryPurchaseOrder).where(InventoryPurchaseOrder.company_id == co.id)
    if status and status != "all":
        q = q.where(InventoryPurchaseOrder.status == status)
    q = q.order_by(InventoryPurchaseOrder.created_at.desc())
    pos = (await db.execute(q)).scalars().all()

    results = []
    for po in pos:
        items_rows = (await db.execute(
            select(InventoryPOItem).where(InventoryPOItem.po_id == po.id)
        )).scalars().all()
        results.append(_po_to_response(po, list(items_rows)))

    return PurchaseOrderListResponse(items=results, total=len(results))


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderResponse)
async def get_purchase_order(
    po_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    po = await db.get(InventoryPurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    items_rows = (await db.execute(
        select(InventoryPOItem).where(InventoryPOItem.po_id == po.id)
    )).scalars().all()
    return _po_to_response(po, list(items_rows))


@router.post("/purchase-orders/{po_id}/approve", response_model=PurchaseOrderResponse)
async def approve_purchase_order(
    po_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    po = await db.get(InventoryPurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    if po.status != "pending_approval":
        raise HTTPException(400, f"Cannot approve a PO with status '{po.status}'")

    po.status = "approved"
    po.approved_by = current_user.id
    po.approved_by_name = getattr(current_user, "full_name", None) or current_user.username
    po.approved_at = datetime.utcnow()

    await db.commit()
    await db.refresh(po)
    items_rows = (await db.execute(
        select(InventoryPOItem).where(InventoryPOItem.po_id == po.id)
    )).scalars().all()
    return _po_to_response(po, list(items_rows))


@router.post("/purchase-orders/{po_id}/reject", response_model=PurchaseOrderResponse)
async def reject_purchase_order(
    po_id: uuid.UUID,
    payload: RejectPORequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    po = await db.get(InventoryPurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    if po.status != "pending_approval":
        raise HTTPException(400, f"Cannot reject a PO with status '{po.status}'")
    if not payload.reason.strip():
        raise HTTPException(400, "Rejection reason is required")

    po.status = "rejected"
    po.rejection_reason = payload.reason.strip()

    await db.commit()
    await db.refresh(po)
    items_rows = (await db.execute(
        select(InventoryPOItem).where(InventoryPOItem.po_id == po.id)
    )).scalars().all()
    return _po_to_response(po, list(items_rows))


@router.post("/purchase-orders/{po_id}/receive", response_model=PurchaseOrderResponse)
async def receive_goods(
    po_id: uuid.UUID,
    payload: ReceiveGoodsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    """Receive goods against an approved PO — adds stock atomically."""
    po = await db.get(InventoryPurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    if po.status not in ("approved", "partially_received"):
        raise HTTPException(400, f"Cannot receive goods for a PO with status '{po.status}'")

    co = await _get_company(db)
    by_name = getattr(current_user, "full_name", None) or current_user.username

    for line in payload.items:
        # Lock PO item
        pi_result = await db.execute(
            select(InventoryPOItem)
            .where(InventoryPOItem.id == line.po_item_id, InventoryPOItem.po_id == po_id)
            .with_for_update()
        )
        pi = pi_result.scalar_one_or_none()
        if not pi:
            raise HTTPException(404, f"PO item {line.po_item_id} not found")

        # Lock the inventory item
        inv_result = await db.execute(
            select(InventoryItem)
            .where(InventoryItem.id == pi.item_id)
            .with_for_update()
        )
        inv_item = inv_result.scalar_one_or_none()
        if not inv_item:
            raise HTTPException(404, f"Inventory item for PO item {line.po_item_id} not found")

        stock_before = inv_item.current_stock
        inv_item.current_stock = inv_item.current_stock + line.quantity_received
        pi.quantity_received = pi.quantity_received + line.quantity_received

        txn = InventoryTransaction(
            company_id=co.id,
            item_id=inv_item.id,
            transaction_type="receipt",
            quantity=line.quantity_received,   # positive = in
            stock_before=stock_before,
            stock_after=inv_item.current_stock,
            reference_id=po.id,
            reference_no=po.po_no,
            notes=f"Received against {po.po_no}",
            created_by=current_user.id,
            created_by_name=by_name,
        )
        db.add(txn)

    await db.flush()

    # Determine new PO status — check if all items are fully received
    all_items = (await db.execute(
        select(InventoryPOItem).where(InventoryPOItem.po_id == po_id)
    )).scalars().all()
    all_received = all(pi.quantity_received >= pi.quantity_ordered for pi in all_items)
    po.status = "received" if all_received else "partially_received"

    await db.commit()
    await db.refresh(po)
    return _po_to_response(po, list(all_items))


# ── Dashboard endpoint ─────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=InventoryDashboardResponse)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co = await _get_company(db)

    # All active items
    items_rows = (await db.execute(
        select(InventoryItem)
        .where(InventoryItem.company_id == co.id, InventoryItem.is_active == True)
        .order_by(InventoryItem.category, InventoryItem.name)
    )).scalars().all()
    supplier_map = await _fetch_suppliers_map(db, [r.id for r in items_rows])
    items = [_to_item_response(r, supplier_map.get(str(r.id), [])) for r in items_rows]

    # Pending PO count
    pending_count = (await db.execute(
        text("""
            SELECT COUNT(*) FROM inventory_purchase_orders
            WHERE company_id = :cid AND status = 'pending_approval'
        """),
        {"cid": str(co.id)},
    )).scalar() or 0

    # Last 10 transactions
    txn_rows = (await db.execute(
        text("""
            SELECT t.id, t.item_id, i.name AS item_name,
                   t.transaction_type, t.quantity, t.stock_before, t.stock_after,
                   t.reference_no, t.notes, t.created_by_name,
                   t.used_by_name, t.used_on, t.created_at
            FROM inventory_transactions t
            JOIN inventory_items i ON i.id = t.item_id
            WHERE t.company_id = :cid
            ORDER BY t.created_at DESC
            LIMIT 10
        """),
        {"cid": str(co.id)},
    )).fetchall()

    recent = [
        InventoryTransactionResponse(
            id=r[0], item_id=r[1], item_name=r[2],
            transaction_type=r[3], quantity=r[4],
            stock_before=r[5], stock_after=r[6],
            reference_no=r[7], notes=r[8],
            created_by_name=r[9],
            used_by_name=r[10], used_on=r[11],
            created_at=r[12],
        )
        for r in txn_rows
    ]

    return InventoryDashboardResponse(
        items=items,
        pending_po_count=int(pending_count),
        recent_transactions=recent,
    )


# ── Telegram settings endpoints ────────────────────────────────────────────────

@router.get("/settings", response_model=TelegramSettings)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    token = (await _get_raw(db, _TG_TOKEN_KEY)) or ""
    chat  = (await _get_raw(db, _TG_CHAT_KEY)) or ""
    time_ = (await _get_raw(db, _TG_TIME_KEY)) or "20:00"
    enab  = (await _get_raw(db, _TG_ENABLED_KEY)) or "false"

    # Mask token
    masked = ("****" + token[-4:]) if len(token) > 4 else "****"

    return TelegramSettings(
        bot_token=masked,
        chat_id=chat,
        report_time=time_,
        enabled=(enab == "true"),
    )


@router.put("/settings", response_model=TelegramSettings)
async def save_settings(
    payload: TelegramSettingsSave,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    # Only update token if user provided a real (unmasked) value
    if not payload.bot_token.startswith("****"):
        await _upsert_setting(db, _TG_TOKEN_KEY, payload.bot_token)

    await _upsert_setting(db, _TG_CHAT_KEY, payload.chat_id)
    await _upsert_setting(db, _TG_TIME_KEY, payload.report_time)
    await _upsert_setting(db, _TG_ENABLED_KEY, "true" if payload.enabled else "false")
    await db.commit()

    # Return masked version
    token = (await _get_raw(db, _TG_TOKEN_KEY)) or ""
    masked = ("****" + token[-4:]) if len(token) > 4 else "****"
    return TelegramSettings(
        bot_token=masked,
        chat_id=payload.chat_id,
        report_time=payload.report_time,
        enabled=payload.enabled,
    )


@router.post("/settings/test")
async def test_telegram(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    """Send a test message to the configured Telegram chat."""
    from app.integrations.notifications.telegram import send_telegram_message

    token = (await _get_raw(db, _TG_TOKEN_KEY)) or ""
    chat  = (await _get_raw(db, _TG_CHAT_KEY)) or ""

    if not token or not chat:
        raise HTTPException(400, "Telegram bot token and chat ID must be configured first")

    try:
        await send_telegram_message(
            token, chat,
            "✅ *WeighBridge Pro — Test Message*\n\nYour Telegram notifications are working correctly!"
        )
        return {"success": True, "message": "Test message sent successfully"}
    except Exception as exc:
        raise HTTPException(400, f"Failed to send message: {exc}")


@router.post("/daily-report/send")
async def send_daily_report_now(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    """Manually trigger the daily inventory report to Telegram."""
    from app.integrations.notifications.telegram import send_telegram_message, build_daily_report

    token   = (await _get_raw(db, _TG_TOKEN_KEY)) or ""
    chat    = (await _get_raw(db, _TG_CHAT_KEY)) or ""
    if not token or not chat:
        raise HTTPException(400, "Telegram bot token and chat ID must be configured first")

    co = await _get_company(db)

    items_rows = (await db.execute(
        text("SELECT name, unit, current_stock, min_stock_level FROM inventory_items WHERE is_active = TRUE ORDER BY category, name")
    )).fetchall()
    items = [
        {
            "name": r[0], "unit": r[1],
            "current_stock": float(r[2]),
            "min_stock_level": float(r[3]),
            "stock_status": "out" if float(r[2]) <= 0 else ("low" if float(r[2]) <= float(r[3]) else "ok"),
        }
        for r in items_rows
    ]

    today_str = date.today().isoformat()
    today_issues = (await db.execute(
        text("SELECT COUNT(*) FROM inventory_transactions WHERE transaction_type='issue' AND DATE(created_at)=:d"),
        {"d": today_str},
    )).scalar() or 0
    today_receipts = (await db.execute(
        text("SELECT COUNT(DISTINCT reference_id) FROM inventory_transactions WHERE transaction_type='receipt' AND DATE(created_at)=:d AND reference_id IS NOT NULL"),
        {"d": today_str},
    )).scalar() or 0

    report_date = date.today().strftime("%d %b %Y")
    msg = build_daily_report(items, int(today_issues), int(today_receipts), co.name, report_date)

    try:
        await send_telegram_message(token, chat, msg)
        return {"success": True, "message": "Daily report sent successfully"}
    except Exception as exc:
        raise HTTPException(400, f"Failed to send report: {exc}")


# ── Category settings endpoints ────────────────────────────────────────────────

@router.get("/settings/categories", response_model=CategoryListResponse)
async def get_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    cats = await _get_categories(db)
    return CategoryListResponse(categories=cats)


@router.put("/settings/categories", response_model=CategoryListResponse)
async def update_categories(
    payload: CategoryUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*_INV_MANAGERS)),
):
    if not payload.categories:
        raise HTTPException(400, "At least one category is required")
    # Normalize
    cats = [c.strip().lower() for c in payload.categories if c.strip()]
    cats = list(dict.fromkeys(cats))  # deduplicate, preserve order
    await _upsert_setting(db, _CATEGORIES_KEY, json.dumps(cats))
    await db.commit()
    return CategoryListResponse(categories=cats)


# ── Analytics endpoint ─────────────────────────────────────────────────────────

@router.get("/analytics")
async def get_analytics(
    date_from: date = Query(...),
    date_to: date = Query(...),
    granularity: str = Query("daily"),       # daily | weekly | monthly
    item_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Consumption analytics: trend, top-consumed items, category breakdown, summary totals."""
    co = await _get_company(db)
    cid = str(co.id)
    # Pass date objects directly — asyncpg infers DATE type from DATE(created_at) expression
    # and requires a Python date object (not a string) for the parameter binding.
    df = date_from   # datetime.date object
    dt = date_to     # datetime.date object

    trunc_map = {"daily": "day", "weekly": "week", "monthly": "month"}
    trunc = trunc_map.get(granularity, "day")

    base_params: dict = {"cid": cid, "df": df, "dt": dt}
    item_clause = ""
    if item_id:
        item_clause = "AND t.item_id = :iid"
        base_params["iid"] = str(item_id)

    # -- Trend: consumption (issues) + receipts grouped by period
    trend_rows = (await db.execute(text(f"""
        SELECT
            DATE_TRUNC('{trunc}', t.created_at)::date AS period,
            COALESCE(SUM(CASE WHEN t.transaction_type = 'issue'   THEN ABS(t.quantity) ELSE 0 END), 0) AS issues,
            COALESCE(SUM(CASE WHEN t.transaction_type = 'receipt' THEN     t.quantity  ELSE 0 END), 0) AS receipts
        FROM inventory_transactions t
        WHERE t.company_id = :cid
          AND DATE(t.created_at) >= :df
          AND DATE(t.created_at) <= :dt
          {item_clause}
        GROUP BY period
        ORDER BY period
    """), base_params)).fetchall()

    # -- Top 10 consumed items
    top_rows = (await db.execute(text("""
        SELECT i.id::text, i.name, i.unit,
               COALESCE(SUM(ABS(t.quantity)), 0) AS total_qty
        FROM inventory_transactions t
        JOIN inventory_items i ON i.id = t.item_id
        WHERE t.company_id = :cid
          AND t.transaction_type = 'issue'
          AND DATE(t.created_at) >= :df
          AND DATE(t.created_at) <= :dt
        GROUP BY i.id, i.name, i.unit
        ORDER BY total_qty DESC
        LIMIT 10
    """), {"cid": cid, "df": df, "dt": dt})).fetchall()

    # -- Category breakdown
    cat_rows = (await db.execute(text("""
        SELECT i.category,
               COALESCE(SUM(ABS(t.quantity)), 0) AS total_issues
        FROM inventory_transactions t
        JOIN inventory_items i ON i.id = t.item_id
        WHERE t.company_id = :cid
          AND t.transaction_type = 'issue'
          AND DATE(t.created_at) >= :df
          AND DATE(t.created_at) <= :dt
        GROUP BY i.category
        ORDER BY total_issues DESC
    """), {"cid": cid, "df": df, "dt": dt})).fetchall()

    # -- Summary totals (respects item filter)
    tot = (await db.execute(text(f"""
        SELECT
            COALESCE(SUM(CASE WHEN transaction_type = 'issue'   THEN ABS(quantity) ELSE 0 END), 0) AS total_issues,
            COALESCE(SUM(CASE WHEN transaction_type = 'receipt' THEN     quantity   ELSE 0 END), 0) AS total_receipts,
            COUNT(CASE WHEN transaction_type = 'issue'   THEN 1 END) AS issue_count,
            COUNT(CASE WHEN transaction_type = 'receipt' THEN 1 END) AS receipt_count
        FROM inventory_transactions t
        WHERE t.company_id = :cid
          AND DATE(t.created_at) >= :df
          AND DATE(t.created_at) <= :dt
          {item_clause}
    """), base_params)).fetchone()

    return {
        "trend": [
            {"date": str(r[0]), "issues": float(r[1]), "receipts": float(r[2])}
            for r in trend_rows
        ],
        "top_consumed": [
            {"item_id": r[0], "item_name": r[1], "unit": r[2], "total_qty": float(r[3])}
            for r in top_rows
        ],
        "category_breakdown": [
            {"category": r[0], "total": float(r[1])}
            for r in cat_rows
        ],
        "summary": {
            "total_issues":    float(tot[0]) if tot else 0,
            "total_receipts":  float(tot[1]) if tot else 0,
            "issue_count":     int(tot[2])   if tot else 0,
            "receipt_count":   int(tot[3])   if tot else 0,
        },
    }

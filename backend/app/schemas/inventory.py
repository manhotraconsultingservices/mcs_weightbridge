import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, field_validator


# ── Item schemas ──────────────────────────────────────────────────────────────

class InventoryItemCreate(BaseModel):
    name: str
    category: str
    unit: str
    min_stock_level: Decimal = Decimal("0")
    reorder_quantity: Decimal = Decimal("0")
    auto_po_enabled: bool = False
    description: Optional[str] = None


class InventoryItemUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    min_stock_level: Optional[Decimal] = None
    reorder_quantity: Optional[Decimal] = None
    auto_po_enabled: Optional[bool] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class MasterSupplierCreate(BaseModel):
    name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


class MasterSupplierUpdate(BaseModel):
    name: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class MasterSupplierResponse(BaseModel):
    id: uuid.UUID
    name: str
    contact_person: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    notes: Optional[str]
    is_active: bool
    model_config = {"from_attributes": True}


class ItemSupplierCreate(BaseModel):
    supplier_name: str
    master_supplier_id: Optional[uuid.UUID] = None
    is_preferred: bool = False
    lead_time_days: Optional[int] = None
    agreed_unit_price: Optional[Decimal] = None
    moq: Optional[Decimal] = None
    notes: Optional[str] = None


class ItemSupplierUpdate(BaseModel):
    supplier_name: Optional[str] = None
    is_preferred: Optional[bool] = None
    lead_time_days: Optional[int] = None
    agreed_unit_price: Optional[Decimal] = None
    moq: Optional[Decimal] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ItemSupplierResponse(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    master_supplier_id: Optional[uuid.UUID]
    supplier_name: str
    is_preferred: bool
    lead_time_days: Optional[int]
    agreed_unit_price: Optional[Decimal]
    moq: Optional[Decimal]
    notes: Optional[str]
    is_active: bool
    model_config = {"from_attributes": True}


class InventoryItemResponse(BaseModel):
    id: uuid.UUID
    name: str
    category: str
    unit: str
    current_stock: Decimal
    min_stock_level: Decimal
    reorder_quantity: Decimal
    auto_po_enabled: bool
    description: Optional[str]
    is_active: bool
    stock_status: str = "ok"   # injected by router — not a DB column
    suppliers: List[ItemSupplierResponse] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ── Stock movement schemas ────────────────────────────────────────────────────

class IssueStockRequest(BaseModel):
    item_id: uuid.UUID
    quantity: Decimal
    notes: Optional[str] = None
    used_by_name: Optional[str] = None   # who actually consumed the material
    used_on: Optional[date] = None       # date of consumption (defaults to today on backend)

    @field_validator("quantity")
    @classmethod
    def qty_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Quantity must be greater than zero")
        return v


class AdjustStockRequest(BaseModel):
    item_id: uuid.UUID
    quantity: Decimal   # positive = add, negative = remove
    reason: str


class InventoryTransactionResponse(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    item_name: str      # populated via join in router
    transaction_type: str
    quantity: Decimal
    stock_before: Decimal
    stock_after: Decimal
    reference_no: Optional[str]
    notes: Optional[str]
    created_by_name: Optional[str]
    used_by_name: Optional[str] = None
    used_on: Optional[date] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    items: List[InventoryTransactionResponse]
    total: int
    page: int
    page_size: int


# ── Purchase Order schemas ────────────────────────────────────────────────────

class POItemCreate(BaseModel):
    item_id: uuid.UUID
    quantity_ordered: Decimal
    unit_price: Optional[Decimal] = None

    @field_validator("quantity_ordered")
    @classmethod
    def qty_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Quantity must be greater than zero")
        return v


class POItemResponse(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    item_name: str
    unit: str
    quantity_ordered: Decimal
    quantity_received: Decimal
    unit_price: Optional[Decimal]
    model_config = {"from_attributes": True}


class PurchaseOrderUpdate(BaseModel):
    """Edit a PO that is still in pending_approval status."""
    supplier_name: Optional[str] = None
    expected_date: Optional[date] = None
    notes: Optional[str] = None
    items: Optional[List["POItemCreate"]] = None   # if provided, replaces all line items


class PurchaseOrderCreate(BaseModel):
    supplier_name: Optional[str] = None
    expected_date: Optional[date] = None
    notes: Optional[str] = None
    items: List[POItemCreate]

    @field_validator("items")
    @classmethod
    def items_not_empty(cls, v):
        if not v:
            raise ValueError("Purchase order must have at least one item")
        return v


class PurchaseOrderResponse(BaseModel):
    id: uuid.UUID
    po_no: str
    status: str
    supplier_name: Optional[str]
    expected_date: Optional[date]
    notes: Optional[str]
    requested_by_name: str
    approved_by_name: Optional[str]
    approved_at: Optional[datetime]
    rejection_reason: Optional[str]
    is_auto_generated: bool = False
    created_at: datetime
    updated_at: datetime
    items: List[POItemResponse] = []
    model_config = {"from_attributes": True}


class PurchaseOrderListResponse(BaseModel):
    items: List[PurchaseOrderResponse]
    total: int


class ReceiveItemLine(BaseModel):
    po_item_id: uuid.UUID
    quantity_received: Decimal

    @field_validator("quantity_received")
    @classmethod
    def qty_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Quantity received must be greater than zero")
        return v


class ReceiveGoodsRequest(BaseModel):
    items: List[ReceiveItemLine]

    @field_validator("items")
    @classmethod
    def items_not_empty(cls, v):
        if not v:
            raise ValueError("Must specify at least one item to receive")
        return v


class RejectPORequest(BaseModel):
    reason: str


# ── Dashboard schema ──────────────────────────────────────────────────────────

class InventoryDashboardResponse(BaseModel):
    items: List[InventoryItemResponse]
    pending_po_count: int
    recent_transactions: List[InventoryTransactionResponse]


# ── Telegram settings schemas ─────────────────────────────────────────────────

class TelegramSettings(BaseModel):
    """Returned on GET — bot_token is masked."""
    bot_token: str
    chat_id: str
    report_time: str   # HH:MM 24-hour
    enabled: bool


class TelegramSettingsSave(BaseModel):
    """Accepted on PUT — full bot_token; if starts with '****' preserve existing."""
    bot_token: str
    chat_id: str
    report_time: str
    enabled: bool


# ── Category schemas ──────────────────────────────────────────────────────────

class CategoryListResponse(BaseModel):
    categories: List[str]


class CategoryUpdateRequest(BaseModel):
    categories: List[str]

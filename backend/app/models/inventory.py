import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, Text, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class InventoryItem(Base):
    """Master list of raw material items tracked in inventory."""
    __tablename__ = "inventory_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))

    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50))          # fuel|electricity|parts|tools|other
    unit: Mapped[str] = mapped_column(String(30))              # litre|kg|unit|set|pair|roll
    current_stock: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    min_stock_level: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    reorder_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    auto_po_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class InventoryTransaction(Base):
    """Immutable audit log of every stock movement (in, out, or adjustment)."""
    __tablename__ = "inventory_transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"))

    transaction_type: Mapped[str] = mapped_column(String(20))  # receipt|issue|adjustment
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))  # positive=in, negative=out
    stock_before: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    stock_after: Mapped[Decimal] = mapped_column(Numeric(14, 3))

    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)   # PO id for receipts
    reference_no: Mapped[str | None] = mapped_column(String(50))            # PO number for receipts
    notes: Mapped[str | None] = mapped_column(Text)

    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(200))        # denormalized (logged-in user)
    used_by_name: Mapped[str | None] = mapped_column(String(200))           # who actually consumed the material
    used_on: Mapped[date | None] = mapped_column(Date)                      # date the material was consumed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryPurchaseOrder(Base):
    """Purchase Order lifecycle — raised by any user, approved by admin, goods received."""
    __tablename__ = "inventory_purchase_orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))

    po_no: Mapped[str] = mapped_column(String(30))             # PO/25-26/0001
    status: Mapped[str] = mapped_column(String(30), default="pending_approval")
    # pending_approval | approved | rejected | partially_received | received

    supplier_name: Mapped[str | None] = mapped_column(String(200))
    expected_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    requested_by_name: Mapped[str] = mapped_column(String(200))

    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by_name: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    is_auto_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    tally_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    tally_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class InventoryPOItem(Base):
    """Line items belonging to a Purchase Order."""
    __tablename__ = "inventory_po_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_purchase_orders.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"))

    item_name: Mapped[str] = mapped_column(String(200))        # denormalized at PO creation
    unit: Mapped[str] = mapped_column(String(30))              # denormalized at PO creation
    quantity_ordered: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))


class InventorySupplier(Base):
    """Master supplier registry for inventory purchasing."""
    __tablename__ = "inventory_suppliers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"), nullable=True)

    name: Mapped[str] = mapped_column(String(200))
    contact_person: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryItemSupplier(Base):
    """Approved suppliers for a given inventory item, with agreed pricing and lead-time."""
    __tablename__ = "inventory_item_suppliers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"))
    master_supplier_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    supplier_name: Mapped[str] = mapped_column(String(200))
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False)
    lead_time_days: Mapped[int | None] = mapped_column(nullable=True)   # ETA in days
    agreed_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    moq: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))          # Minimum Order Quantity
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

"""ORM models for finished-goods inventory.

ProductStock — one row per product, holds current_stock + min level.
ProductStockMovement — append-only audit of every change to current_stock.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Text, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ProductStock(Base):
    __tablename__ = "product_stock"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), unique=True)
    current_stock: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    min_stock_level: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    last_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProductStockMovement(Base):
    __tablename__ = "product_stock_movements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    movement_type: Mapped[str] = mapped_column(String(30))
    # opening | sale | purchase | adjustment | cycle_output | sale_cancelled | purchase_cancelled
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))   # signed: + in, − out
    stock_before: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    stock_after: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    reference_type: Mapped[str | None] = mapped_column(String(30))
    reference_id: Mapped[uuid.UUID | None] = mapped_column()
    reference_no: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_by_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

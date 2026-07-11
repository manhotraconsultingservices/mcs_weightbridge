"""Per-unit default rate for a product.

A product can be sold by several units (₹/MT, ₹/CFT, ₹/CBM, ₹/Brass). This
table holds the DEFAULT rate for each (product, unit). The product's own
`default_rate` remains the rate for its base `unit` (kept in sync when that
unit is edited), so legacy single-rate readers still work.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Numeric, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ProductUnitRate(Base):
    __tablename__ = "product_unit_rates"
    __table_args__ = (UniqueConstraint("product_id", "unit", name="uq_product_unit_rate"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    unit: Mapped[str] = mapped_column(String(20))
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

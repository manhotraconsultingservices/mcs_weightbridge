"""Production cycle ORM models for yield + wastage tracking.

Stone-crusher 4-stage process per cycle (one cycle per day):
  raw boulder → stage1 (primary) → stage2 (secondary) → stage3 (screening)
  → stage4 (wash on conveyor belt) → finished products per category.

Stage 4 is multi-product, so per-product outputs are in a child table.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import (
    String, Boolean, Integer, Text, DateTime, Date, ForeignKey, Numeric,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ProductionCycle(Base):
    __tablename__ = "production_cycles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    cycle_no: Mapped[int] = mapped_column(Integer)
    cycle_date: Mapped[date] = mapped_column(Date)
    # Optional FK to the raw material consumed by this cycle. NULL = legacy
    # cycles that didn't track raw stock. On finalise, a negative cycle_input
    # movement is posted to product_stock for this product.
    raw_material_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    input_kg: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    stage1_output_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    stage2_output_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    stage3_output_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_finalised: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    outputs: Mapped[list["ProductionCycleOutput"]] = relationship(
        back_populates="cycle", cascade="all, delete-orphan", lazy="selectin",
    )

    __table_args__ = (UniqueConstraint("company_id", "cycle_date", name="uq_cycle_per_day"),)


class ProductionCycleOutput(Base):
    __tablename__ = "production_cycle_outputs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_cycles.id", ondelete="CASCADE"),
    )
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    output_kg: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)

    cycle: Mapped["ProductionCycle"] = relationship(back_populates="outputs")

    __table_args__ = (UniqueConstraint("cycle_id", "product_id", name="uq_output_per_product"),)

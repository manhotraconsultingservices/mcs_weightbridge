"""Royalty / Mining Transit-Pass tracking (Horizon 2).

Stone crushers buy boulders against government mineral royalty / e-transit
passes. Each pass authorises a quantity; inbound purchase loads are consumed
against it. The reconciliation answers "how much royalty quantity is left,
and does it match what we actually received + crushed?".
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, DateTime, Date, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class RoyaltyPass(Base):
    __tablename__ = "royalty_passes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    fy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_years.id"), nullable=True)

    pass_no: Mapped[str] = mapped_column(String(60))         # govt pass / permit number (external)
    pass_type: Mapped[str] = mapped_column(String(20), default="royalty")  # royalty|e_transit|mineral_permit
    source_name: Mapped[str | None] = mapped_column(String(200))           # mine / quarry / lease holder
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id"), nullable=True)  # supplier
    mineral: Mapped[str | None] = mapped_column(String(120))               # material (free text)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), nullable=True)

    issue_date: Mapped[date | None] = mapped_column(Date)
    valid_till: Mapped[date | None] = mapped_column(Date)

    quantity_mt: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)   # authorised qty (MT)
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)          # royalty rate / MT
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)        # royalty amount paid

    vehicle_no: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(15), default="active")         # active|exhausted|expired|cancelled
    notes: Mapped[str | None] = mapped_column(Text)

    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    consumptions: Mapped[list["RoyaltyPassConsumption"]] = relationship(
        back_populates="royalty_pass", cascade="all, delete-orphan"
    )


class RoyaltyPassConsumption(Base):
    __tablename__ = "royalty_pass_consumptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pass_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("royalty_passes.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tokens.id"), nullable=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    quantity_mt: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    consumed_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    royalty_pass: Mapped["RoyaltyPass"] = relationship(back_populates="consumptions")

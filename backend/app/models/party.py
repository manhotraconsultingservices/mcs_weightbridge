import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, Numeric, Text, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Party(Base):
    __tablename__ = "parties"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    party_type: Mapped[str] = mapped_column(String(10))  # customer, supplier, both
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15))
    pan: Mapped[str | None] = mapped_column(String(10))
    phone: Mapped[str | None] = mapped_column(String(15))
    alt_phone: Mapped[str | None] = mapped_column(String(15))
    email: Mapped[str | None] = mapped_column(String(100))
    contact_person: Mapped[str | None] = mapped_column(String(100))

    billing_address: Mapped[str | None] = mapped_column(Text)
    billing_city: Mapped[str | None] = mapped_column(String(100))
    billing_state: Mapped[str | None] = mapped_column(String(100))
    billing_state_code: Mapped[str | None] = mapped_column(String(2))
    billing_pincode: Mapped[str | None] = mapped_column(String(6))

    shipping_address: Mapped[str | None] = mapped_column(Text)
    shipping_city: Mapped[str | None] = mapped_column(String(100))
    shipping_state: Mapped[str | None] = mapped_column(String(100))
    shipping_state_code: Mapped[str | None] = mapped_column(String(2))
    shipping_pincode: Mapped[str | None] = mapped_column(String(6))

    credit_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=0)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    current_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tally_ledger_name: Mapped[str | None] = mapped_column(String(200))

    tally_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    tally_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    rates: Mapped[list["PartyRate"]] = relationship(back_populates="party")


class PartyRate(Base):
    __tablename__ = "party_rates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    party: Mapped["Party"] = relationship(back_populates="rates")

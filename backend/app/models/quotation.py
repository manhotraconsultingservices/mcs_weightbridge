import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, Numeric, Text, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Quotation(Base):
    __tablename__ = "quotations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    fy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_years.id"))
    quotation_no: Mapped[str] = mapped_column(String(30))
    quotation_date: Mapped[date] = mapped_column(Date)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id"))
    status: Mapped[str] = mapped_column(String(15), default="draft")
    # draft, sent, accepted, rejected, expired, converted

    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    discount_type: Mapped[str | None] = mapped_column(String(10))
    discount_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    round_off: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)

    tally_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    tally_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text)
    terms_and_conditions: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    items: Mapped[list["QuotationItem"]] = relationship(back_populates="quotation", cascade="all, delete-orphan")
    party: Mapped["Party"] = relationship("Party", foreign_keys=[party_id], lazy="noload")


class QuotationItem(Base):
    __tablename__ = "quotation_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    quotation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quotations.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    description: Mapped[str | None] = mapped_column(String(300))
    hsn_code: Mapped[str | None] = mapped_column(String(8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit: Mapped[str] = mapped_column(String(10))
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    quotation: Mapped["Quotation"] = relationship(back_populates="items")

import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, Numeric, Text, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    fy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_years.id"))

    invoice_type: Mapped[str] = mapped_column(String(20))  # sale, purchase
    tax_type: Mapped[str] = mapped_column(String(20), default="gst")  # gst, non_gst
    invoice_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)

    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id"), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(200))  # for B2C walk-in
    token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tokens.id"))
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("quotations.id"))

    # Vehicle/transport info (denormalized from token for quick access)
    vehicle_no: Mapped[str | None] = mapped_column(String(20))
    transporter_name: Mapped[str | None] = mapped_column(String(200))
    eway_bill_no: Mapped[str | None] = mapped_column(String(20))

    # Weight info (denormalized from token)
    gross_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    tare_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    net_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    # Amounts
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    discount_type: Mapped[str | None] = mapped_column(String(10))  # percentage, flat
    discount_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tcs_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=0)
    tcs_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    freight: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    round_off: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)

    # Payment
    payment_mode: Mapped[str | None] = mapped_column(String(20))  # cash, credit, upi, cheque, bank_transfer
    payment_status: Mapped[str] = mapped_column(String(15), default="unpaid")  # unpaid, partial, paid
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    amount_due: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)

    status: Mapped[str] = mapped_column(String(15), default="draft")  # draft, final, cancelled
    notes: Mapped[str | None] = mapped_column(Text)

    # Tally sync
    tally_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    tally_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Revision / amendment tracking
    revision_no: Mapped[int] = mapped_column(Integer, default=1)
    original_invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)

    # eInvoice (GST IRN)
    irn: Mapped[str | None] = mapped_column(String(64), nullable=True)
    irn_ack_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    irn_ack_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    irn_qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    irn_signed_invoice: Mapped[str | None] = mapped_column(Text, nullable=True)
    einvoice_status: Mapped[str] = mapped_column(String(20), default="none")  # none, success, failed, cancelled
    einvoice_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    irn_cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    items: Mapped[list["InvoiceItem"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    party: Mapped["Party"] = relationship("Party", foreign_keys=[party_id], lazy="noload")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    description: Mapped[str | None] = mapped_column(String(300))
    hsn_code: Mapped[str | None] = mapped_column(String(8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit: Mapped[str] = mapped_column(String(10))
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    invoice: Mapped["Invoice"] = relationship(back_populates="items")

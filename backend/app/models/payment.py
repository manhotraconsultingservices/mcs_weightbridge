import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PaymentReceipt(Base):
    """Incoming payments from customers"""
    __tablename__ = "payment_receipts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    fy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_years.id"))
    receipt_no: Mapped[str] = mapped_column(String(30))
    receipt_date: Mapped[date] = mapped_column(Date)
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    payment_mode: Mapped[str] = mapped_column(String(20))  # cash, cheque, upi, bank_transfer
    reference_no: Mapped[str | None] = mapped_column(String(50))  # cheque no, UTR, etc.
    bank_name: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    tally_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentVoucher(Base):
    """Outgoing payments to suppliers"""
    __tablename__ = "payment_vouchers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    fy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_years.id"))
    voucher_no: Mapped[str] = mapped_column(String(30))
    voucher_date: Mapped[date] = mapped_column(Date)
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    payment_mode: Mapped[str] = mapped_column(String(20))
    reference_no: Mapped[str | None] = mapped_column(String(50))
    bank_name: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    tally_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvoicePayment(Base):
    """Links payments to invoices for settlement tracking"""
    __tablename__ = "invoice_payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"))
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_receipts.id"))
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_vouchers.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

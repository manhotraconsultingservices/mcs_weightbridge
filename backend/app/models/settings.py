import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class NumberSequence(Base):
    __tablename__ = "number_sequences"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    fy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_years.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"), nullable=True)  # NULL = default branch
    sequence_type: Mapped[str] = mapped_column(String(30))  # token, sale_invoice, purchase_invoice, quotation, receipt, voucher
    prefix: Mapped[str] = mapped_column(String(10), default="")
    last_number: Mapped[int] = mapped_column(Integer, default=0)
    reset_daily: Mapped[bool] = mapped_column(Boolean, default=False)  # tokens reset daily
    last_reset_date: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD for daily reset


class SerialPortConfig(Base):
    __tablename__ = "serial_port_config"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    port_name: Mapped[str] = mapped_column(String(20), default="COM1")
    baud_rate: Mapped[int] = mapped_column(Integer, default=9600)
    data_bits: Mapped[int] = mapped_column(Integer, default=8)
    stop_bits: Mapped[int] = mapped_column(Integer, default=1)
    parity: Mapped[str] = mapped_column(String(1), default="N")
    protocol: Mapped[str] = mapped_column(String(30), default="generic")
    # Protocol-specific settings stored as JSON string
    protocol_config: Mapped[str | None] = mapped_column(Text)
    stability_readings: Mapped[int] = mapped_column(Integer, default=5)
    stability_tolerance_kg: Mapped[int] = mapped_column(Integer, default=20)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class TallyConfig(Base):
    __tablename__ = "tally_config"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    host: Mapped[str] = mapped_column(String(100), default="localhost")
    port: Mapped[int] = mapped_column(Integer, default=9002)
    tally_company_name: Mapped[str | None] = mapped_column(String(200))
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Ledger name mappings — must match ledger names in Tally exactly
    ledger_sales: Mapped[str] = mapped_column(String(100), default="Sales")
    ledger_purchase: Mapped[str] = mapped_column(String(100), default="Purchase")
    ledger_cgst: Mapped[str] = mapped_column(String(100), default="CGST")
    ledger_sgst: Mapped[str] = mapped_column(String(100), default="SGST")
    ledger_igst: Mapped[str] = mapped_column(String(100), default="IGST")
    ledger_freight: Mapped[str] = mapped_column(String(100), default="Freight Outward")
    ledger_discount: Mapped[str] = mapped_column(String(100), default="Trade Discount")
    ledger_tcs: Mapped[str] = mapped_column(String(100), default="TCS Payable")
    ledger_roundoff: Mapped[str] = mapped_column(String(100), default="Round Off")

    # Narration options — control what appears in the voucher narration field
    narration_vehicle: Mapped[bool] = mapped_column(Boolean, default=True)
    narration_token: Mapped[bool] = mapped_column(Boolean, default=True)
    narration_weight: Mapped[bool] = mapped_column(Boolean, default=True)

    # Invoice-number prefix filter — only invoices whose number starts with one
    # of these prefixes are sent to Tally (comma-separated; blank/NULL = all).
    # E.g. "INV,PUR" syncs GST sales + purchases but excludes any other series.
    sync_invoice_prefix: Mapped[str | None] = mapped_column(String(200))

    # Sync transport mode. NULL = derive from MULTI_TENANT (cloud → 'relay',
    # on-prem → 'direct'). 'direct' = backend pushes XML to Tally on the LAN;
    # 'relay' = enqueue into tally_sync_jobs for the LAN-side Tally Connector.
    mode: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Accounting-only / no-GST export. When TRUE, invoices are built as plain
    # accounting vouchers (party + Sales/Purchase ledger only — no stock item,
    # no GST, "Accounting Voucher View"). Needed for legacy Tally (e.g. Tally 9)
    # that crashes on inventory/GST vouchers, and for non-GST demo companies.
    accounting_only: Mapped[bool] = mapped_column(Boolean, default=False)
    # When True, non-GST invoices (Bill of Supply, tax_type='non_gst') are ALSO
    # eligible for Tally sync (pending list / auto-sync / manual). Default False
    # keeps the historical GST-only behaviour (cash sales stay out of the books).
    sync_non_gst: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(20))  # create, update, delete
    entity_type: Mapped[str] = mapped_column(String(50))  # invoice, token, party, etc.
    entity_id: Mapped[str | None] = mapped_column(String(50))
    details: Mapped[str | None] = mapped_column(Text)  # JSON of changed fields
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

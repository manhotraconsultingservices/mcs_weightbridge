"""Delivery Challan — a dispatch document (GST Rule 55).

Goods move out of the plant on a challan; the tax invoice follows (often
monthly-billed). Kept in its OWN tables (not the invoices table) so a challan
can never leak into GSTR-1 / P&L / receivables. ``convert-to-invoice`` clones
the challan into a real sale invoice and links them.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, DateTime, Date, ForeignKey, Numeric, Text, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class DeliveryChallan(Base):
    __tablename__ = "delivery_challans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    fy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_years.id"))

    # Assigned at create (gap-free via next_doc_no, prefix DC). A challan is
    # issued the instant goods dispatch, so the number is allocated immediately
    # (gaps on cancel are acceptable — same rationale as the gate pass).
    challan_no: Mapped[str | None] = mapped_column(String(30))
    challan_date: Mapped[date] = mapped_column(Date)
    purpose: Mapped[str] = mapped_column(String(30), default="supply")  # supply|job_work|sample|line_sales|other

    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id"), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(200))  # B2C walk-in
    token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tokens.id"), nullable=True)

    vehicle_no: Mapped[str | None] = mapped_column(String(20))
    transporter_name: Mapped[str | None] = mapped_column(String(200))
    driver_name: Mapped[str | None] = mapped_column(String(100))
    distance_km: Mapped[int | None] = mapped_column(Integer)
    destination: Mapped[str | None] = mapped_column(String(200))

    tax_type: Mapped[str] = mapped_column(String(20), default="gst")  # gst|non_gst (informational)
    sub_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)

    # Lifecycle: open (issued) → invoiced (converted) | cancelled
    status: Mapped[str] = mapped_column(String(15), default="open")
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text)

    # ── E-Way Bill (generated via standalone NIC EWB API for challan movements) ─
    ewb_no: Mapped[str | None] = mapped_column(String(20))
    ewb_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ewb_valid_till: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ewb_status: Mapped[str] = mapped_column(String(20), default="none")  # none|generated|cancelled|failed
    ewb_error: Mapped[str | None] = mapped_column(Text)

    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    items: Mapped[list["DeliveryChallanItem"]] = relationship(
        back_populates="challan", cascade="all, delete-orphan"
    )
    party: Mapped["Party"] = relationship("Party", foreign_keys=[party_id], lazy="noload")


class DeliveryChallanItem(Base):
    __tablename__ = "delivery_challan_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    challan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("delivery_challans.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    description: Mapped[str | None] = mapped_column(String(300))
    hsn_code: Mapped[str | None] = mapped_column(String(8))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit: Mapped[str] = mapped_column(String(10))
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    challan: Mapped["DeliveryChallan"] = relationship(back_populates="items")

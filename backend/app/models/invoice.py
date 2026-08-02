import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, Numeric, Text, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    fy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_years.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"), nullable=True)  # NULL = default branch

    invoice_type: Mapped[str] = mapped_column(String(20))  # sale, purchase, credit_note, debit_note
    tax_type: Mapped[str] = mapped_column(String(20), default="gst")  # gst, non_gst
    # Credit/Debit note linkage (GST CDNR). reference_invoice_id points at the
    # original invoice the note adjusts; note_reason is the statutory reason.
    reference_invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    note_reason: Mapped[str | None] = mapped_column(String(200))
    invoice_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)

    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id"), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(200))  # for B2C walk-in
    token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tokens.id"))
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("quotations.id"))
    # Agent (broker) association + commission snapshot (computed at finalise)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    commission_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    # Vehicle/transport info (denormalized from token for quick access)
    vehicle_no: Mapped[str | None] = mapped_column(String(20))
    transporter_name: Mapped[str | None] = mapped_column(String(200))
    eway_bill_no: Mapped[str | None] = mapped_column(String(20))
    # E-Way Bill lifecycle (IRN-integrated capture + standalone NIC EWB API)
    ewb_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ewb_valid_till: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ewb_status: Mapped[str] = mapped_column(String(20), default="none")  # none|generated|cancelled|failed
    ewb_error: Mapped[str | None] = mapped_column(Text)
    ewb_distance_km: Mapped[int | None] = mapped_column(Integer)

    # Transport & dispatch metadata (Tally-compatible fields)
    royalty_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    delivery_note: Mapped[str | None] = mapped_column(String(100), nullable=True)
    supplier_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    buyer_order_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    buyer_order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dispatch_doc_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dispatch_through: Mapped[str | None] = mapped_column(String(200), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lr_rr_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    terms_of_delivery: Mapped[str | None] = mapped_column(String(200), nullable=True)
    driver_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

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
    vehicle_rent: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)  # transport/vehicle rent charge
    royalty_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)  # govt mineral royalty charge
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    round_off: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)

    # Payment
    payment_mode: Mapped[str | None] = mapped_column(String(20))  # cash, credit, upi, cheque, bank_transfer
    payment_status: Mapped[str] = mapped_column(String(15), default="unpaid")  # unpaid, partial, paid
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    amount_due: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    # ── Write-off tracking ────────────────────────────────────────────────
    # Recorded when admin/accountant writes off uncollectable balance. Closes
    # the invoice (payment_status -> paid). Audit log captures the change.
    write_off_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    write_off_reason: Mapped[str | None] = mapped_column(String(500))
    write_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    write_off_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    status: Mapped[str] = mapped_column(String(15), default="draft")  # draft, final, cancelled
    notes: Mapped[str | None] = mapped_column(Text)

    # Offline approve-then-number (P1 #175). A manager APPROVES the amount during
    # an outage; the legal GST number is still assigned by the SERVER at sync
    # (finalise). approved=True means "reviewed, ready to number" — set offline
    # and replayed as an intent keyed by token_id.
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Tally sync
    tally_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    tally_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Revision / amendment tracking
    revision_no: Mapped[int] = mapped_column(Integer, default=1)
    original_invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    # Baseline snapshot captured when the invoice is first drafted, so finalise can
    # diff draft→final (what the operator changed) for the finalize notification.
    draft_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # eInvoice (GST IRN)
    irn: Mapped[str | None] = mapped_column(String(64), nullable=True)
    irn_ack_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    irn_ack_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    irn_qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    irn_signed_invoice: Mapped[str | None] = mapped_column(Text, nullable=True)
    einvoice_status: Mapped[str] = mapped_column(String(20), default="none")  # none, success, failed, cancelled
    einvoice_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    irn_cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Offline replay (P1 #171): the client op id that produced this invoice
    # (deduped via ux_invoices_client_op) + origin. Invoice NUMBERS are never
    # minted offline — the server assigns them at sync — so these only tag which
    # invoices came in from an edge terminal.
    client_op_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    origin: Mapped[str] = mapped_column(String(10), default="online")
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
    # noload by default (never lazy-load in async); eager-loaded where the product
    # name/HSN is needed (e.g. the PDF query) so the invoice "Particulars" column
    # falls back to the product name when the line has no explicit description.
    product: Mapped["Product"] = relationship("Product", lazy="noload")

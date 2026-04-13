from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID
from pydantic import BaseModel, model_validator


class InvoiceItemCreate(BaseModel):
    product_id: UUID
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    quantity: Decimal
    unit: str
    rate: Decimal
    gst_rate: Decimal = Decimal("0")
    sort_order: int = 0


class InvoiceCreate(BaseModel):
    invoice_type: str = "sale"          # sale | purchase
    tax_type: str = "gst"               # gst | non_gst
    invoice_date: date
    party_id: Optional[UUID] = None     # None for B2C walk-in customers
    customer_name: Optional[str] = None # used when party_id is None
    token_id: Optional[UUID] = None
    quotation_id: Optional[UUID] = None
    vehicle_no: Optional[str] = None
    transporter_name: Optional[str] = None
    eway_bill_no: Optional[str] = None
    gross_weight: Optional[Decimal] = None
    tare_weight: Optional[Decimal] = None
    net_weight: Optional[Decimal] = None
    discount_type: Optional[str] = None   # percentage | flat
    discount_value: Decimal = Decimal("0")
    freight: Decimal = Decimal("0")
    tcs_rate: Decimal = Decimal("0")
    payment_mode: Optional[str] = None
    notes: Optional[str] = None
    items: list[InvoiceItemCreate]


class InvoiceUpdate(BaseModel):
    # Draft-editable header fields
    party_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    invoice_date: Optional[date] = None
    tax_type: Optional[str] = None
    # Common editable fields
    vehicle_no: Optional[str] = None
    transporter_name: Optional[str] = None
    eway_bill_no: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[Decimal] = None
    freight: Optional[Decimal] = None
    tcs_rate: Optional[Decimal] = None
    payment_mode: Optional[str] = None
    notes: Optional[str] = None
    items: Optional[list[InvoiceItemCreate]] = None


class ItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    description: Optional[str]
    hsn_code: Optional[str]
    quantity: Decimal
    unit: str
    rate: Decimal
    amount: Decimal
    gst_rate: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_amount: Decimal
    sort_order: int
    model_config = {"from_attributes": True}


class PartyBrief(BaseModel):
    id: UUID
    name: str
    gstin: Optional[str]
    billing_city: Optional[str]
    billing_state: Optional[str]
    billing_state_code: Optional[str]
    model_config = {"from_attributes": True}


class InvoiceResponse(BaseModel):
    id: UUID
    invoice_type: str
    tax_type: str
    invoice_no: Optional[str]
    invoice_date: date
    due_date: Optional[date]
    party: Optional[PartyBrief]
    customer_name: Optional[str]
    token_id: Optional[UUID]
    token_no: Optional[int] = None       # denormalized from linked token
    token_date: Optional[date] = None    # denormalized from linked token
    vehicle_no: Optional[str]
    transporter_name: Optional[str]
    eway_bill_no: Optional[str]
    gross_weight: Optional[Decimal]
    tare_weight: Optional[Decimal]
    net_weight: Optional[Decimal]
    subtotal: Decimal
    discount_type: Optional[str]
    discount_value: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    tcs_rate: Decimal
    tcs_amount: Decimal
    freight: Decimal
    total_amount: Decimal
    round_off: Decimal
    grand_total: Decimal
    payment_mode: Optional[str]
    payment_status: str
    amount_paid: Decimal
    amount_due: Decimal
    status: str
    notes: Optional[str]
    tally_synced: bool
    tally_sync_at: Optional[datetime]
    tally_needs_sync: bool = False   # computed: True when not yet synced or modified after last sync
    # eInvoice (GST IRN)
    irn: Optional[str] = None
    irn_ack_no: Optional[str] = None
    irn_ack_date: Optional[datetime] = None
    einvoice_status: str = "none"    # none, success, failed, cancelled
    einvoice_error: Optional[str] = None
    irn_cancelled_at: Optional[datetime] = None
    # Revision tracking
    revision_no: int = 1
    original_invoice_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    items: list[ItemResponse]
    model_config = {"from_attributes": True}

    @model_validator(mode='after')
    def compute_tally_needs_sync(self) -> 'InvoiceResponse':
        """An invoice needs (re)sync when: never synced, OR updated after last sync."""
        if not self.tally_synced:
            self.tally_needs_sync = True
        elif self.tally_sync_at is not None and self.updated_at > self.tally_sync_at:
            self.tally_needs_sync = True
        else:
            self.tally_needs_sync = False
        return self


class InvoiceListResponse(BaseModel):
    items: list[InvoiceResponse]
    total: int
    page: int
    page_size: int


# ── Revision / amendment schemas ──────────────────────────────────────────────

class CreateRevisionRequest(BaseModel):
    reason: Optional[str] = None  # Optional reason/notes for this revision


class RevisionHistoryItem(BaseModel):
    id: UUID
    original_invoice_id: UUID
    from_revision_no: int
    to_revision_no: int
    from_invoice_id: UUID
    to_invoice_id: UUID
    change_summary: Optional[str]
    revised_by_name: Optional[str] = None
    created_at: datetime
    finalized_at: Optional[datetime]
    model_config = {"from_attributes": True}


class InvoiceRevisionChain(BaseModel):
    """All revisions for an invoice, plus metadata about the chain."""
    original_invoice_id: UUID
    current_revision_no: int
    invoices: list[InvoiceResponse]       # all versions, oldest first
    history: list[RevisionHistoryItem]    # revision events


class InvoiceCompare(BaseModel):
    """Side-by-side comparison of two invoice versions."""
    invoice_a: InvoiceResponse
    invoice_b: InvoiceResponse
    diff: Any                              # structured diff from invoice_diff.compute_invoice_diff
    revision_record: Optional[RevisionHistoryItem] = None

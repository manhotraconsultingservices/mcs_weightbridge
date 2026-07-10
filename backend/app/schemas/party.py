import uuid
from datetime import date
from decimal import Decimal
from pydantic import BaseModel


class PartyCreate(BaseModel):
    party_type: str  # customer, supplier, both
    name: str
    legal_name: str | None = None
    gstin: str | None = None
    pan: str | None = None
    phone: str | None = None
    alt_phone: str | None = None
    email: str | None = None
    contact_person: str | None = None
    billing_address: str | None = None
    billing_city: str | None = None
    billing_state: str | None = None
    billing_state_code: str | None = None
    billing_pincode: str | None = None
    shipping_address: str | None = None
    shipping_city: str | None = None
    shipping_state: str | None = None
    shipping_state_code: str | None = None
    shipping_pincode: str | None = None
    credit_limit: Decimal = Decimal("0")
    payment_terms_days: int = 0
    opening_balance: Decimal = Decimal("0")
    default_payment_mode: str = "cash"     # 'cash' (Bill of Supply, default) | 'online' (GST + Tally)
    tally_ledger_name: str | None = None


class PartyUpdate(BaseModel):
    party_type: str | None = None
    name: str | None = None
    legal_name: str | None = None
    gstin: str | None = None
    pan: str | None = None
    phone: str | None = None
    alt_phone: str | None = None
    email: str | None = None
    contact_person: str | None = None
    billing_address: str | None = None
    billing_city: str | None = None
    billing_state: str | None = None
    billing_state_code: str | None = None
    billing_pincode: str | None = None
    shipping_address: str | None = None
    shipping_city: str | None = None
    shipping_state: str | None = None
    shipping_state_code: str | None = None
    shipping_pincode: str | None = None
    credit_limit: Decimal | None = None
    payment_terms_days: int | None = None
    default_payment_mode: str | None = None
    tally_ledger_name: str | None = None
    is_active: bool | None = None


class PartyResponse(BaseModel):
    id: uuid.UUID
    party_type: str
    name: str
    legal_name: str | None
    gstin: str | None
    pan: str | None
    phone: str | None
    email: str | None
    contact_person: str | None
    billing_city: str | None
    billing_state: str | None
    billing_state_code: str | None
    credit_limit: Decimal
    payment_terms_days: int
    opening_balance: Decimal
    current_balance: Decimal
    default_payment_mode: str = "cash"
    tally_ledger_name: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class PartyRateCreate(BaseModel):
    product_id: uuid.UUID
    rate: Decimal
    effective_from: date
    effective_to: date | None = None


class PartyRateResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    rate: Decimal
    effective_from: date
    effective_to: date | None

    model_config = {"from_attributes": True}


# ── Customer 360 view ───────────────────────────────────────────────────────

class Party360Invoice(BaseModel):
    id: uuid.UUID
    invoice_no: str | None
    invoice_date: date
    due_date: date | None
    invoice_type: str
    grand_total: Decimal
    amount_paid: Decimal
    amount_due: Decimal
    payment_status: str
    status: str


class Party360Payment(BaseModel):
    id: uuid.UUID
    kind: str                 # "receipt" | "voucher"
    voucher_no: str
    payment_date: date
    amount: Decimal
    payment_mode: str
    reference_no: str | None


class Party360AgingBuckets(BaseModel):
    current: Decimal = Decimal("0")
    bucket_1_30: Decimal = Decimal("0")
    bucket_31_60: Decimal = Decimal("0")
    bucket_61_90: Decimal = Decimal("0")
    bucket_90_plus: Decimal = Decimal("0")


class Party360CustomRate(BaseModel):
    product_id: uuid.UUID
    product_name: str
    product_unit: str
    default_rate: Decimal
    custom_rate: Decimal
    effective_from: date


class Party360Header(BaseModel):
    id: uuid.UUID
    name: str
    party_type: str
    gstin: str | None
    pan: str | None
    phone: str | None
    email: str | None
    billing_city: str | None
    billing_state: str | None
    credit_limit: Decimal
    payment_terms_days: int
    current_balance: Decimal
    opening_balance: Decimal
    is_active: bool


class Party360Stats(BaseModel):
    # Lifetime sale metrics
    lifetime_sales: Decimal = Decimal("0")       # sum of grand_total for all non-cancelled sale invoices
    lifetime_paid: Decimal = Decimal("0")        # sum of amount_paid on those invoices
    lifetime_written_off: Decimal = Decimal("0") # sum of write_off_amount on those invoices
    write_off_count: int = 0                     # how many invoices have been written off for this party
    invoice_count: int = 0                       # non-cancelled sale invoices only
    avg_order_value: Decimal = Decimal("0")      # lifetime_sales / invoice_count
    last_invoice_date: date | None = None
    days_since_last_order: int | None = None
    last_payment_date: date | None = None
    days_since_last_payment: int | None = None
    # Outstanding snapshot
    total_outstanding: Decimal = Decimal("0")
    total_overdue: Decimal = Decimal("0")
    advance_balance: Decimal = Decimal("0")      # unallocated advance the party has on account (credit)
    aging: Party360AgingBuckets = Party360AgingBuckets()
    # Operations
    token_count: int = 0
    lifetime_tonnage: Decimal = Decimal("0")     # sum of net_weight in MT (kg/1000) on completed tokens


class Party360Response(BaseModel):
    party: Party360Header
    stats: Party360Stats
    recent_invoices: list[Party360Invoice]
    recent_payments: list[Party360Payment]
    custom_rates: list[Party360CustomRate]

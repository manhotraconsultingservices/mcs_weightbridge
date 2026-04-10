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

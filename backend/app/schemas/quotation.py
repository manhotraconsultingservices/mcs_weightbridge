from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class QuotationItemCreate(BaseModel):
    product_id: UUID
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    quantity: Decimal
    unit: str
    rate: Decimal
    gst_rate: Decimal = Decimal("0")
    sort_order: int = 0


class QuotationCreate(BaseModel):
    quotation_date: date
    valid_to: Optional[date] = None
    party_id: UUID
    tax_type: str = "gst"
    discount_type: Optional[str] = None
    discount_value: Decimal = Decimal("0")
    notes: Optional[str] = None
    terms_and_conditions: Optional[str] = None
    items: list[QuotationItemCreate]


class QuotationUpdate(BaseModel):
    valid_to: Optional[date] = None
    discount_type: Optional[str] = None
    discount_value: Optional[Decimal] = None
    notes: Optional[str] = None
    terms_and_conditions: Optional[str] = None
    items: Optional[list[QuotationItemCreate]] = None


class QuotationItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    description: Optional[str]
    hsn_code: Optional[str]
    quantity: Decimal
    unit: str
    rate: Decimal
    amount: Decimal
    gst_rate: Decimal
    total_amount: Decimal
    sort_order: int
    model_config = {"from_attributes": True}


class PartyBrief(BaseModel):
    id: UUID
    name: str
    gstin: Optional[str]
    model_config = {"from_attributes": True}


class QuotationResponse(BaseModel):
    id: UUID
    quotation_no: str
    quotation_date: date
    valid_to: Optional[date]
    party: Optional[PartyBrief]
    status: str
    subtotal: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_amount: Decimal
    round_off: Decimal
    grand_total: Decimal
    notes: Optional[str]
    terms_and_conditions: Optional[str]
    created_at: datetime
    items: list[QuotationItemResponse]
    model_config = {"from_attributes": True}


class QuotationListResponse(BaseModel):
    items: list[QuotationResponse]
    total: int
    page: int
    page_size: int

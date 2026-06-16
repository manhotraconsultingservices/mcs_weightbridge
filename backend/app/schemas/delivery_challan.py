from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class ChallanItemCreate(BaseModel):
    product_id: UUID
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    quantity: Decimal
    unit: str = "MT"
    rate: Decimal = Decimal("0")
    gst_rate: Decimal = Decimal("0")
    sort_order: int = 0


class DeliveryChallanCreate(BaseModel):
    challan_date: date
    purpose: str = "supply"
    party_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    token_id: Optional[UUID] = None
    vehicle_no: Optional[str] = None
    transporter_name: Optional[str] = None
    driver_name: Optional[str] = None
    distance_km: Optional[int] = None
    destination: Optional[str] = None
    tax_type: str = "gst"
    notes: Optional[str] = None
    items: list[ChallanItemCreate]


class ChallanItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    description: Optional[str]
    hsn_code: Optional[str]
    quantity: Decimal
    unit: str
    rate: Decimal
    amount: Decimal
    gst_rate: Decimal
    sort_order: int
    model_config = {"from_attributes": True}


class DeliveryChallanResponse(BaseModel):
    id: UUID
    challan_no: Optional[str]
    challan_date: date
    purpose: str
    party_id: Optional[UUID]
    customer_name: Optional[str]
    party_name: Optional[str] = None
    token_id: Optional[UUID]
    token_no: Optional[int] = None
    vehicle_no: Optional[str]
    transporter_name: Optional[str]
    driver_name: Optional[str]
    distance_km: Optional[int]
    destination: Optional[str]
    tax_type: str
    sub_total: Decimal
    total_amount: Decimal
    status: str
    invoice_id: Optional[UUID]
    invoice_no: Optional[str] = None
    notes: Optional[str]
    ewb_no: Optional[str]
    ewb_date: Optional[datetime]
    ewb_valid_till: Optional[datetime]
    ewb_status: str
    created_at: datetime
    items: list[ChallanItemResponse] = []
    model_config = {"from_attributes": True}


class DeliveryChallanListResponse(BaseModel):
    items: list[DeliveryChallanResponse]
    total: int


class ConvertToInvoiceRequest(BaseModel):
    invoice_date: Optional[date] = None   # defaults to today

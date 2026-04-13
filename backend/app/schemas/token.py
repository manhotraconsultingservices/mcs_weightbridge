from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class TokenCreate(BaseModel):
    token_date: date
    direction: str = "outbound"          # inbound | outbound
    token_type: str = "sale"             # sale | purchase | general
    party_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    vehicle_no: str
    vehicle_id: Optional[UUID] = None
    vehicle_type: Optional[str] = None
    driver_id: Optional[UUID] = None
    transporter_id: Optional[UUID] = None
    gate_pass: Optional[str] = None
    remarks: Optional[str] = None


class TokenFirstWeight(BaseModel):
    weight_kg: Decimal
    is_manual: bool = False


class TokenSecondWeight(BaseModel):
    weight_kg: Decimal
    is_manual: bool = False


class TokenUpdate(BaseModel):
    party_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    vehicle_no: Optional[str] = None
    vehicle_id: Optional[UUID] = None
    vehicle_type: Optional[str] = None
    driver_id: Optional[UUID] = None
    transporter_id: Optional[UUID] = None
    remarks: Optional[str] = None


class PartyBrief(BaseModel):
    id: UUID
    name: str
    model_config = {"from_attributes": True}


class ProductBrief(BaseModel):
    id: UUID
    name: str
    unit: str
    model_config = {"from_attributes": True}


class VehicleBrief(BaseModel):
    id: UUID
    registration_no: str
    default_tare_weight: Optional[Decimal] = None
    model_config = {"from_attributes": True}


class DriverBrief(BaseModel):
    id: UUID
    name: str
    phone: Optional[str] = None
    license_no: Optional[str] = None
    model_config = {"from_attributes": True}


class TransporterBrief(BaseModel):
    id: UUID
    name: str
    phone: Optional[str] = None
    model_config = {"from_attributes": True}


class LinkedInvoice(BaseModel):
    id: UUID
    invoice_no: Optional[str] = None
    grand_total: Optional[Decimal] = None
    status: Optional[str] = None
    payment_status: Optional[str] = None


class TokenResponse(BaseModel):
    id: UUID
    token_no: Optional[int]
    token_date: date
    status: str
    direction: str
    token_type: str
    vehicle_no: str
    vehicle_type: Optional[str] = None
    party: Optional[PartyBrief] = None
    product: Optional[ProductBrief] = None
    vehicle: Optional[VehicleBrief] = None
    driver: Optional[DriverBrief] = None
    transporter: Optional[TransporterBrief] = None
    linked_invoice: Optional[LinkedInvoice] = None
    gross_weight: Optional[Decimal] = None
    tare_weight: Optional[Decimal] = None
    net_weight: Optional[Decimal] = None
    first_weight: Optional[Decimal] = None
    second_weight: Optional[Decimal] = None
    first_weight_type: Optional[str] = None
    is_manual_weight: bool = False
    is_supplement: bool = False
    gate_pass: Optional[str] = None
    remarks: Optional[str] = None
    created_at: datetime
    first_weight_at: Optional[datetime] = None
    second_weight_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TokenListResponse(BaseModel):
    items: list[TokenResponse]
    total: int
    page: int
    page_size: int

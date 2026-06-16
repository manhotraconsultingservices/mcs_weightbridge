from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class RoyaltyPassCreate(BaseModel):
    pass_no: str
    pass_type: str = "royalty"
    source_name: Optional[str] = None
    party_id: Optional[UUID] = None
    mineral: Optional[str] = None
    product_id: Optional[UUID] = None
    issue_date: Optional[date] = None
    valid_till: Optional[date] = None
    quantity_mt: Decimal = Decimal("0")
    rate: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    vehicle_no: Optional[str] = None
    notes: Optional[str] = None


class RoyaltyPassUpdate(BaseModel):
    pass_no: Optional[str] = None
    pass_type: Optional[str] = None
    source_name: Optional[str] = None
    party_id: Optional[UUID] = None
    mineral: Optional[str] = None
    product_id: Optional[UUID] = None
    issue_date: Optional[date] = None
    valid_till: Optional[date] = None
    quantity_mt: Optional[Decimal] = None
    rate: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    vehicle_no: Optional[str] = None
    notes: Optional[str] = None


class ConsumeRequest(BaseModel):
    quantity_mt: Decimal
    token_id: Optional[UUID] = None
    invoice_id: Optional[UUID] = None
    consumed_date: Optional[date] = None
    notes: Optional[str] = None
    # P1: variance tracking — populated by auto-draw; manual consume uses quantity_mt for both
    authorized_mt: Optional[Decimal] = None
    actual_mt: Optional[Decimal] = None
    vehicle_no: Optional[str] = None


class ConsumptionResponse(BaseModel):
    id: UUID
    quantity_mt: Decimal
    authorized_mt: Optional[Decimal] = None
    actual_mt: Optional[Decimal] = None
    variance_mt: Optional[Decimal] = None
    vehicle_no: Optional[str] = None
    token_id: Optional[UUID]
    token_no: Optional[int] = None          # joined from tokens table in detail endpoint
    invoice_id: Optional[UUID]
    consumed_date: date
    notes: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}


class RoyaltyPassResponse(BaseModel):
    id: UUID
    pass_no: str
    pass_type: str
    source_name: Optional[str]
    party_id: Optional[UUID]
    party_name: Optional[str] = None
    mineral: Optional[str]
    product_id: Optional[UUID]
    issue_date: Optional[date]
    valid_till: Optional[date]
    quantity_mt: Decimal
    rate: Decimal
    amount: Decimal
    vehicle_no: Optional[str]
    status: str
    notes: Optional[str]
    created_at: datetime
    # computed
    consumed_mt: Decimal = Decimal("0")
    balance_mt: Decimal = Decimal("0")
    utilization_pct: float = 0.0
    days_to_expiry: Optional[int] = None
    consumptions: list[ConsumptionResponse] = []
    model_config = {"from_attributes": True}


class RoyaltyPassListResponse(BaseModel):
    items: list[RoyaltyPassResponse]
    total: int


class RoyaltyReconciliation(BaseModel):
    date_from: date
    date_to: date
    authorised_mt: float
    consumed_mt: float
    purchase_inbound_mt: float
    balance_mt: float
    unaccounted_mt: float
    total_royalty_amount: float      # P3: sum of pass.amount (royalty ₹ paid)
    pass_count: int
    active_count: int
    expiring_count: int

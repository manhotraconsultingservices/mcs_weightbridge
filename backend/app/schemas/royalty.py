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


class ConsumptionResponse(BaseModel):
    id: UUID
    quantity_mt: Decimal
    token_id: Optional[UUID]
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
    authorised_mt: float      # sum of pass quantities (issued in range)
    consumed_mt: float        # sum of consumptions in range
    purchase_inbound_mt: float  # sum of completed purchase-token net weight in range
    balance_mt: float         # authorised - consumed
    unaccounted_mt: float     # purchase_inbound - consumed (loads received without a pass)
    pass_count: int
    active_count: int
    expiring_count: int

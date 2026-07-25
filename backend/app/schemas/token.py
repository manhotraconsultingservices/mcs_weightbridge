from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
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
    tyre_count: Optional[int] = None     # 4/6/8/10/12 — for slip + truck-class label
    driver_id: Optional[UUID] = None
    transporter_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None      # broker/dalal — carried to the invoice for commission
    billing_unit: Optional[str] = None   # operator-chosen unit to bill this truck (MT/CFT/CBM/BRASS…)
    gate_pass: Optional[str] = None
    gate_pass_id: Optional[UUID] = None  # link to gate_passes record (uses its GP number)
    remarks: Optional[str] = None
    transit_pass_id: Optional[UUID] = None   # links purchase token to its transit/royalty pass
    vehicle_rent: Optional[Decimal] = None   # payment to truck owner per trip
    custom_fields: Optional[dict[str, Any]] = None   # owner-defined attributes (moisture, quality…)
    # Offline replay (P1 #171): when an edge terminal replays a token it captured
    # offline, it sends the id it already assigned locally so the token has the
    # SAME id on both sides (no dependency substitution for the weighments).
    # Ignored unless X-Client-Op-Id is present. Online creates omit both.
    id: Optional[UUID] = None
    client_op_id: Optional[UUID] = None
    # #172: the gate-pass number the edge minted (GP/<date>/B1-NNN) and printed on
    # the slip. Kept verbatim at sync (gate passes tolerate gaps → no rewind).
    # Honoured only for X-Op-Origin: edge replays.
    gate_pass_no: Optional[str] = None


class TokenFirstWeight(BaseModel):
    weight_kg: Decimal
    is_manual: bool = False


class TokenSecondWeight(BaseModel):
    weight_kg: Decimal
    is_manual: bool = False
    # Offline replay (P1 #172): an edge terminal mints its own token_no in the
    # reserved 9000–9999 band and prints it on the slip; it sends that number
    # here so the server keeps it verbatim at sync (slip == final number).
    # Honoured only for X-Op-Origin: edge replays; online second-weights ignore it.
    token_no: Optional[int] = None


class TokenVolumeCreate(BaseModel):
    """Volume-based load: skip the bridge, compute weight from volume × bulk_density.

    Calculation: weight_kg = volume_cft × bulk_density(kg/CFT).
    """
    token_date: date
    direction: str = "outbound"
    token_type: str = "sale"             # sale | purchase
    party_id: UUID                       # required — auto-invoice needs a party
    product_id: UUID                     # required — bulk_density must be on product
    vehicle_no: str
    vehicle_id: Optional[UUID] = None
    vehicle_type: Optional[str] = None
    tyre_count: Optional[int] = None     # 4/6/8/10/12 — also drives default volume in UI
    driver_id: Optional[UUID] = None
    transporter_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None      # broker/dalal — carried to the invoice for commission
    billing_unit: Optional[str] = None   # operator-chosen unit to bill this truck (CFT/CBM/BRASS/MT…)
    volume_cft: Decimal                  # cubic feet — canonical unit stored in DB
    gate_pass: Optional[str] = None
    gate_pass_id: Optional[UUID] = None  # link to gate_passes record
    remarks: Optional[str] = None
    transit_pass_id: Optional[UUID] = None
    vehicle_rent: Optional[Decimal] = None
    custom_fields: Optional[dict[str, Any]] = None


class TokenUpdate(BaseModel):
    party_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    vehicle_no: Optional[str] = None
    vehicle_id: Optional[UUID] = None
    vehicle_type: Optional[str] = None
    tyre_count: Optional[int] = None
    driver_id: Optional[UUID] = None
    transporter_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    remarks: Optional[str] = None
    custom_fields: Optional[dict[str, Any]] = None


class PartyBrief(BaseModel):
    id: UUID
    name: str
    model_config = {"from_attributes": True}


class ProductBrief(BaseModel):
    id: UUID
    name: str
    unit: str
    bulk_density: Decimal | None = None    # kg/CFT — for client-side weight/volume display
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
    tyre_count: Optional[int] = None
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
    weight_method: str = "weighbridge"   # 'weighbridge' | 'volume'
    volume_cft: Optional[Decimal] = None     # cubic feet, canonical unit (when weight_method='volume')
    is_supplement: bool = False
    gate_pass: Optional[str] = None          # legacy free-text gate-pass note
    gate_pass_no: Optional[str] = None       # auto-allocated GP/25-26/0001
    source: str = "manual"                   # manual | anpr | kiosk
    anpr_entry_at: Optional[datetime] = None
    anpr_exit_at: Optional[datetime] = None
    transit_pass_id: Optional[UUID] = None
    agent_id: Optional[UUID] = None
    billing_unit: Optional[str] = None
    vehicle_rent: Optional[Decimal] = None
    operator_name: Optional[str] = None      # who created the token (cash accountability)
    remarks: Optional[str] = None
    custom_fields: Optional[dict[str, Any]] = None   # owner-defined attribute values
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

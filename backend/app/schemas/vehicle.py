import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel


class VehicleCreate(BaseModel):
    registration_no: str
    vehicle_type: str | None = None
    owner_name: str | None = None
    owner_phone: str | None = None
    default_tare_weight: Decimal = Decimal("0")


class VehicleUpdate(BaseModel):
    registration_no: str | None = None
    vehicle_type: str | None = None
    owner_name: str | None = None
    owner_phone: str | None = None
    default_tare_weight: Decimal | None = None
    is_active: bool | None = None


class VehicleResponse(BaseModel):
    id: uuid.UUID
    registration_no: str
    vehicle_type: str | None
    owner_name: str | None
    owner_phone: str | None
    default_tare_weight: Decimal
    is_active: bool

    model_config = {"from_attributes": True}


class TareWeightHistoryResponse(BaseModel):
    id: uuid.UUID
    tare_weight: Decimal
    recorded_at: datetime

    model_config = {"from_attributes": True}


class DriverCreate(BaseModel):
    name: str
    license_no: str | None = None
    phone: str | None = None
    aadhaar_no: str | None = None


class DriverResponse(BaseModel):
    id: uuid.UUID
    name: str
    license_no: str | None
    phone: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class TransporterCreate(BaseModel):
    name: str
    gstin: str | None = None
    phone: str | None = None
    address: str | None = None


class TransporterResponse(BaseModel):
    id: uuid.UUID
    name: str
    gstin: str | None
    phone: str | None
    is_active: bool

    model_config = {"from_attributes": True}

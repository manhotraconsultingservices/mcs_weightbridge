import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel


class VehicleCreate(BaseModel):
    registration_no: str
    vehicle_type: str | None = None
    owner_name: str | None = None
    owner_phone: str | None = None
    default_tare_weight: Decimal = Decimal("0")
    benchmark_mileage_kmpl: Decimal | None = None
    tank_capacity_litres: Decimal | None = None
    rent_rate_per_km_per_mt: Decimal | None = None
    rent_rate_per_km_per_cum: Decimal | None = None


class VehicleUpdate(BaseModel):
    registration_no: str | None = None
    vehicle_type: str | None = None
    owner_name: str | None = None
    owner_phone: str | None = None
    default_tare_weight: Decimal | None = None
    benchmark_mileage_kmpl: Decimal | None = None
    tank_capacity_litres: Decimal | None = None
    rent_rate_per_km_per_mt: Decimal | None = None
    rent_rate_per_km_per_cum: Decimal | None = None
    is_active: bool | None = None


class VehicleResponse(BaseModel):
    id: uuid.UUID
    registration_no: str
    vehicle_type: str | None
    owner_name: str | None
    owner_phone: str | None
    default_tare_weight: Decimal
    benchmark_mileage_kmpl: Decimal | None = None
    tank_capacity_litres: Decimal | None = None
    rent_rate_per_km_per_mt: Decimal | None = None
    rent_rate_per_km_per_cum: Decimal | None = None
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


# ── Fleet fuel & mileage ──────────────────────────────────────────────────────

class FuelEntryCreate(BaseModel):
    vehicle_id: uuid.UUID
    entry_date: date
    odometer_km: Decimal
    litres: Decimal
    rate_per_litre: Decimal | None = None
    amount: Decimal | None = None
    fuel_source: str = "plant_tank"      # plant_tank / outside_pump / other
    tank_full: bool = True
    driver_id: uuid.UUID | None = None
    notes: str | None = None


class FuelEntryUpdate(BaseModel):
    entry_date: date | None = None
    odometer_km: Decimal | None = None
    litres: Decimal | None = None
    rate_per_litre: Decimal | None = None
    amount: Decimal | None = None
    fuel_source: str | None = None
    tank_full: bool | None = None
    driver_id: uuid.UUID | None = None
    notes: str | None = None


class FuelEntryResponse(BaseModel):
    id: uuid.UUID
    vehicle_id: uuid.UUID
    registration_no: str | None = None
    entry_date: date
    odometer_km: Decimal
    litres: Decimal
    rate_per_litre: Decimal | None = None
    amount: Decimal | None = None
    fuel_source: str
    tank_full: bool
    driver_id: uuid.UUID | None = None
    driver_name: str | None = None
    notes: str | None = None
    created_at: datetime | None = None
    # Computed for the row (the interval that this fill just closed):
    distance_km: float | None = None      # km since the previous fill
    interval_kmpl: float | None = None    # km/litre for that interval
    flags: list[str] = []                 # odometer_rollback, litres_over_tank, …

    model_config = {"from_attributes": True}

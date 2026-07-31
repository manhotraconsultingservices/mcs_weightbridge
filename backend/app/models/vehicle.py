import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, Date, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    registration_no: Mapped[str] = mapped_column(String(20))
    vehicle_type: Mapped[str | None] = mapped_column(String(20))  # truck, tractor, trailer, tipper, mini_truck
    owner_name: Mapped[str | None] = mapped_column(String(100))
    owner_phone: Mapped[str | None] = mapped_column(String(15))
    default_tare_weight: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    # Fleet fuel & mileage — nullable so existing vehicles are unaffected.
    benchmark_mileage_kmpl: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # expected km per litre
    tank_capacity_litres: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    # Current odometer (km) — latest known reading. Settable on the master and
    # auto-bumped to the highest odometer recorded by any fuel entry.
    current_odometer_km: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    # Vehicle rent rate: ₹ per km per MT. vehicle_rent = rate × distance_km × net_weight_MT
    rent_rate_per_km_per_mt: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    # Alternate rent basis: ₹ per km per CUM. vehicle_rent = rate × distance_km × CUM.
    # Used for volume (CUB) loads; the operator picks/overrides the rate on the token.
    rent_rate_per_km_per_cum: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    tare_history: Mapped[list["TareWeightHistory"]] = relationship(back_populates="vehicle")


class TareWeightHistory(Base):
    __tablename__ = "tare_weight_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"))
    tare_weight: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    vehicle: Mapped["Vehicle"] = relationship(back_populates="tare_history")


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(100))
    license_no: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(15))
    aadhaar_no: Mapped[str | None] = mapped_column(String(12))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Transporter(Base):
    __tablename__ = "transporters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15))
    phone: Mapped[str | None] = mapped_column(String(15))
    address: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VehicleFuelEntry(Base):
    """One diesel fill per row. ``odometer_km`` = meter reading at the fill.
    Mileage + deviation are computed at read time (never stored) in services/fuel.py.
    Optional refs (branch/inventory/driver) are plain UUIDs — no DB FK — to keep the
    per-statement DDL bootstrap order-independent.
    """
    __tablename__ = "vehicle_fuel_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"))
    entry_date: Mapped[date] = mapped_column(Date)
    odometer_km: Mapped[Decimal] = mapped_column(Numeric(12, 1))
    litres: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    rate_per_litre: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    fuel_source: Mapped[str] = mapped_column(String(20), default="plant_tank")  # plant_tank/outside_pump/other
    tank_full: Mapped[bool] = mapped_column(Boolean, default=True)
    inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    inventory_txn_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Numeric, func
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

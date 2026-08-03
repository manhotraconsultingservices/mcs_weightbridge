"""Petrol-pump fuel-credit purchase orders + payments.

When a vehicle is fuelled at an OUTSIDE petrol pump ON CREDIT, the system
auto-creates a `FuelPurchaseOrder` against that pump/station name. These POs are
a pure **accounts-payable ledger to the pump** — they do NOT move store
inventory (only plant-tank fills do) and they do NOT re-book the fuel expense
(that is already recognised in the P&L via `vehicle_fuel_entries`). Payments to a
pump are recorded as `FuelPoPayment` rows and allocated FIFO across that pump's
open POs, so the "outstanding to petrol pump" report stays correct.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import String, DateTime, Date, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FuelPurchaseOrder(Base):
    __tablename__ = "fuel_purchase_orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    po_no: Mapped[str] = mapped_column(String(40))                 # FPO/25-26/0001
    station_name: Mapped[str] = mapped_column(String(120))         # the petrol pump
    supplier_party_id: Mapped[uuid.UUID | None] = mapped_column(default=None)   # optional link to a supplier
    fuel_entry_id: Mapped[uuid.UUID | None] = mapped_column(default=None)       # the vehicle_fuel_entries row
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    po_date: Mapped[date] = mapped_column(Date)
    litres: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    rate_per_litre: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    status: Mapped[str] = mapped_column(String(12), default="unpaid")   # unpaid | partial | paid
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FuelPoPayment(Base):
    __tablename__ = "fuel_po_payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    station_name: Mapped[str] = mapped_column(String(120))         # the pump paid
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    payment_date: Mapped[date] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(20), default="cash")  # cash | bank | upi | cheque
    reference: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

"""Workforce & Payroll — workers (non-login), attendance muster, payments.

The weighbridge as system-of-record for labour cost. Earnings + balance are
computed at read time (services/payroll.py) from attendance + payments — nothing
derived is stored. Optional refs (branch) are plain UUIDs (no DB FK) to keep the
per-statement DDL bootstrap order-independent.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, Date, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Worker(Base):
    """A labourer/staff member — NOT an application login. Just a payroll record."""
    __tablename__ = "workers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(15))
    worker_type: Mapped[str] = mapped_column(String(20), default="daily_wage")  # daily_wage | monthly_salary
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)            # ₹/day or ₹/month
    designation: Mapped[str | None] = mapped_column(String(80))
    joining_date: Mapped[date | None] = mapped_column(Date)
    aadhaar_no: Mapped[str | None] = mapped_column(String(12))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkerAttendance(Base):
    """One row per worker per day. UNIQUE(worker_id, att_date) — upserted from the muster grid."""
    __tablename__ = "worker_attendance"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    worker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workers.id"))
    att_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="present")  # present | absent | half_day | overtime
    ot_hours: Mapped[Decimal] = mapped_column(Numeric(4, 1), default=0)
    notes: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkerPayment(Base):
    """Every rupee out to (or deducted from) a worker: advance/wage/salary/bonus/deduction."""
    __tablename__ = "worker_payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    worker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workers.id"))
    pay_date: Mapped[date] = mapped_column(Date)
    payment_type: Mapped[str] = mapped_column(String(20), default="wage")  # advance | wage | salary | bonus | deduction
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    mode: Mapped[str] = mapped_column(String(20), default="cash")          # cash | bank | upi
    reference: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

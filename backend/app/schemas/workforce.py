import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel


class WorkerCreate(BaseModel):
    name: str
    phone: str | None = None
    worker_type: str = "daily_wage"     # daily_wage | monthly_salary
    rate: Decimal = Decimal("0")        # ₹/day or ₹/month
    designation: str | None = None
    joining_date: date | None = None
    aadhaar_no: str | None = None
    notes: str | None = None


class WorkerUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    worker_type: str | None = None
    rate: Decimal | None = None
    designation: str | None = None
    joining_date: date | None = None
    aadhaar_no: str | None = None
    is_active: bool | None = None
    notes: str | None = None


class WorkerResponse(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None = None
    worker_type: str
    rate: Decimal
    designation: str | None = None
    joining_date: date | None = None
    aadhaar_no: str | None = None
    is_active: bool
    notes: str | None = None

    model_config = {"from_attributes": True}


class AttendanceMark(BaseModel):
    worker_id: uuid.UUID
    att_date: date
    status: str                         # present | absent | half_day | overtime
    ot_hours: Decimal = Decimal("0")
    notes: str | None = None


class AttendanceBulk(BaseModel):
    items: list[AttendanceMark]


class PaymentCreate(BaseModel):
    worker_id: uuid.UUID
    pay_date: date
    payment_type: str = "wage"          # advance | wage | salary | bonus | deduction
    amount: Decimal
    mode: str = "cash"                  # cash | bank | upi
    reference: str | None = None
    notes: str | None = None


class PaymentUpdate(BaseModel):
    pay_date: date | None = None
    payment_type: str | None = None
    amount: Decimal | None = None
    mode: str | None = None
    reference: str | None = None
    notes: str | None = None


class PaymentResponse(BaseModel):
    id: uuid.UUID
    worker_id: uuid.UUID
    worker_name: str | None = None
    pay_date: date
    payment_type: str
    amount: Decimal
    mode: str
    reference: str | None = None
    notes: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}

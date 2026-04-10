import uuid
from datetime import date, datetime
from sqlalchemy import String, Boolean, Date, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15), unique=True)
    pan: Mapped[str | None] = mapped_column(String(10))
    cin: Mapped[str | None] = mapped_column(String(21))
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    state_code: Mapped[str | None] = mapped_column(String(2))
    pincode: Mapped[str | None] = mapped_column(String(6))
    phone: Mapped[str | None] = mapped_column(String(15))
    email: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(200))
    bank_name: Mapped[str | None] = mapped_column(String(100))
    bank_account_no: Mapped[str | None] = mapped_column(String(20))
    bank_ifsc: Mapped[str | None] = mapped_column(String(11))
    bank_branch: Mapped[str | None] = mapped_column(String(100))
    invoice_prefix: Mapped[str] = mapped_column(String(10), default="INV")
    quotation_prefix: Mapped[str] = mapped_column(String(10), default="QTN")
    purchase_prefix: Mapped[str] = mapped_column(String(10), default="PUR")
    logo_path: Mapped[str | None] = mapped_column(String(500))
    current_fy_start: Mapped[date] = mapped_column(Date)
    current_fy_end: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    financial_years: Mapped[list["FinancialYear"]] = relationship(back_populates="company")


class FinancialYear(Base):
    __tablename__ = "financial_years"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    label: Mapped[str] = mapped_column(String(20))  # e.g. "2025-26"
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped["Company"] = relationship(back_populates="financial_years")

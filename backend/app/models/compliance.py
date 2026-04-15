import uuid
from datetime import date, datetime
from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ComplianceItem(Base):
    """Stores insurance policies, certifications, licenses, and other compliance documents."""
    __tablename__ = "compliance_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))

    item_type: Mapped[str] = mapped_column(String(30))          # insurance | certification | license | permit
    name: Mapped[str] = mapped_column(String(200))              # e.g. "Vehicle Insurance - MH-12-AB-1234"
    policy_holder: Mapped[str | None] = mapped_column(String(200), nullable=True)  # e.g. "ABC Stone Crusher Pvt. Ltd."
    issuer: Mapped[str | None] = mapped_column(String(200))     # e.g. "New India Assurance"
    reference_no: Mapped[str | None] = mapped_column(String(100))  # Policy/cert number
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    file_path: Mapped[str | None] = mapped_column(Text)         # Local/network path to document
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

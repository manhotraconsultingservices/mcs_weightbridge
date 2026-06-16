"""Branch / plant (Horizon 3 — full multi-branch).

A company can run several crusher plants / weighbridges. Each branch can have
its own GSTIN (additional place of business), its own number series (invoices,
tokens, gate passes), and its own finished-goods stock. Backward-compatible:
existing data has branch_id = NULL, treated as the single default branch, so
nothing changes for single-plant tenants until they add branches.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str] = mapped_column(String(12))            # short tag in number series, e.g. "HQ", "PL2"
    gstin: Mapped[str | None] = mapped_column(String(15))    # per-branch GSTIN (optional)
    address_line1: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    state_code: Mapped[str | None] = mapped_column(String(2))
    pincode: Mapped[str | None] = mapped_column(String(10))
    phone: Mapped[str | None] = mapped_column(String(20))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

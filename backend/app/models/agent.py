"""Agent (broker / dalal) master + commission payouts.

An agent can be associated to a token, invoice or gate pass. Commission is
computed from the finalised invoices carrying the agent (snapshotted on the
invoice at finalise time) and paid out via AgentCommissionPayment rows.
"""
import uuid
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(15))
    gstin: Mapped[str | None] = mapped_column(String(15))
    pan: Mapped[str | None] = mapped_column(String(10))
    address: Mapped[str | None] = mapped_column(String(500))
    # Commission config:
    #   per_mt             → ₹rate per MT of invoice net_weight
    #   pct_of_taxable     → rate% of invoice taxable_amount
    #   pct_of_grand_total → rate% of invoice grand_total
    #   flat_per_invoice   → ₹rate per invoice
    commission_type: Mapped[str] = mapped_column(String(20), default="pct_of_taxable")
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    notes: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AgentCommissionPayment(Base):
    __tablename__ = "agent_commission_payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid_on: Mapped[date] = mapped_column(Date)
    payment_mode: Mapped[str | None] = mapped_column(String(20))
    reference_no: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

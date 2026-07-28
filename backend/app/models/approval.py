"""
Maker-checker (4-eyes) approval requests.

When a tenant turns the ``maker_checker`` control ON, sensitive money actions
(single write-off, bulk write-off, invoice cancel, day-book opening-balance
change) are PARKED as a pending request in this table instead of executing.
A second admin — the *checker*, who must differ from the *maker* who
submitted — approves (the real action then runs, replayed from ``payload``) or
rejects (the request is discarded). Every decision is audit-logged.

Lives in the per-tenant database. The table itself is created by the runtime
DDL bootstrap (``ddl.py::get_runtime_ddl``); this model is for ORM access.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, Numeric, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))

    # write_off | write_off_bulk | invoice_cancel | day_book_opening
    action_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)

    status: Mapped[str] = mapped_column(String(15), default="pending")  # pending|approved|rejected

    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    requested_by_name: Mapped[str | None] = mapped_column(String(200))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_by_name: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(500))

    result: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_approval_requests_status", "company_id", "status", "requested_at"),
    )

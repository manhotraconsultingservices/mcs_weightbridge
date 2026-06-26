"""
Tally relay job queue (SaaS/relay mode only).

In cloud/relay mode the backend builds the Tally voucher XML and enqueues a job
here instead of pushing directly (it can't reach the client's LAN Tally). A
LAN-side **Tally Connector** claims pending jobs (outbound HTTPS, agent-key
auth), pushes each job's XML to the local Tally gateway, and reports the result
back — which flips the source row's ``tally_synced``. Direct/on-prem mode never
writes to this table.

Lives in the per-tenant database. The table itself is created by the runtime DDL
bootstrap (``ddl.py::get_runtime_ddl``); this model is for ORM access.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    String, Integer, Text, DateTime, ForeignKey, UniqueConstraint, Index, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TallySyncJob(Base):
    __tablename__ = "tally_sync_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))

    entity_type: Mapped[str] = mapped_column(String(20))      # invoice|party|sales_order|purchase_order
    entity_id: Mapped[uuid.UUID] = mapped_column()
    idempotency_key: Mapped[str] = mapped_column(String(80))  # "<entity_type>:<entity_id>"
    priority: Mapped[int] = mapped_column(Integer, default=100)  # party=10, order=50, invoice=100
    company_name: Mapped[str | None] = mapped_column(String(200))
    xml: Mapped[str] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|in_progress|done|failed|dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=6)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    tally_response: Mapped[str | None] = mapped_column(Text)

    claim_token: Mapped[str | None] = mapped_column(String(64))
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    picked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_tally_job_company_idem"),
        Index("idx_tally_jobs_claim", "status", "priority", "next_attempt_at", "created_at"),
    )

"""
InvoiceRevision — stores snapshots and diffs for every invoice amendment.

When an accountant creates a new revision of a finalized invoice, a row is
inserted here capturing:
  - A full JSON snapshot of the invoice BEFORE the revision (from_invoice)
  - The structured diff once the new revision is finalized (diff / change_summary)

This lets business owners see the complete history and compare any two versions.
"""

import uuid
from datetime import datetime
from sqlalchemy import UUID, ForeignKey, Integer, Text, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InvoiceRevision(Base):
    __tablename__ = "invoice_revisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Root of the chain — always the original v1 invoice's id
    original_invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    from_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)   # e.g. 1
    to_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)      # e.g. 2

    from_invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)  # v1 invoice
    to_invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)    # v2 draft

    # Snapshot of the FROM invoice at the moment of revision creation
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Populated once the TO invoice is finalized
    diff: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    revised_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

"""ANPR (Automatic Number Plate Recognition) ORM model.

One row per plate detection event. Detections arrive from either:
  - Source A: local FastALPR worker running inside the camera agent
  - Source B: on-camera ANPR webhook from a Hikvision / Dahua unit

The router (`backend/app/routers/anpr.py`) decides whether each detection
is an `entry`, `exit`, `unmatched`, or `duplicate` and links the resulting
token (if any) via `token_id`.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AnprEvent(Base):
    __tablename__ = "anpr_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))

    # plate_raw  = exact OCR / webhook output (e.g. "MH 12 AB 1234", "mh12ab1234")
    # plate_normalized = uppercase, no spaces / dashes / dots — used for lookups
    plate_raw: Mapped[str] = mapped_column(String(20))
    plate_normalized: Mapped[str] = mapped_column(String(20))

    # Linked vehicle from the master, if plate matched (case-insensitive or
    # 1-char Levenshtein fuzzy). NULL means an unknown plate.
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id"))

    # Token created on entry (or linked on exit). ON DELETE SET NULL because
    # cancelling a token shouldn't lose the ANPR audit trail.
    token_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tokens.id", ondelete="SET NULL"))

    # 'entry' | 'exit' | 'unmatched' | 'duplicate' | 'heartbeat'
    direction: Mapped[str] = mapped_column(String(15))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))

    # 'local_fastalpr' | 'hikvision_webhook' | 'dahua_webhook' | 'cloud_platerec' | 'manual'
    source: Mapped[str] = mapped_column(String(30))
    camera_id: Mapped[str] = mapped_column(String(20))
    snapshot_path: Mapped[str | None] = mapped_column(Text)

    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Top-3 OCR candidates for review-screen disambiguation (Source A only)
    ocr_alternates: Mapped[list | None] = mapped_column(JSONB)

    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str | None] = mapped_column(Text)

"""Tenant model — stored in the master database (weighbridge_master).

Uses a separate declarative base (MasterBase) so it never interferes
with the per-tenant app schema (Base from app.database).
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, Text, func, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class MasterBase(DeclarativeBase):
    """Declarative base for the master (tenant-registry) database only."""
    pass


class Tenant(MasterBase):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    db_name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    agent_api_key: Mapped[str] = mapped_column(
        String(200), unique=True, nullable=False
    )
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

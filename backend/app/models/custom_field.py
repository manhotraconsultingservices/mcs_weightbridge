import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import String, Boolean, Integer, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class CustomFieldDefinition(Base):
    """Owner-defined custom attribute for an entity (v1: 'token' weighments).

    Definitions are per-tenant (live in the tenant DB). Values are stored in a
    JSONB column on the target entity (tokens.custom_fields), keyed by field_key.
    """

    __tablename__ = "custom_field_definitions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    entity_type: Mapped[str] = mapped_column(String(20), default="token")  # token | product | party
    field_key: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(120))
    field_type: Mapped[str] = mapped_column(String(20), default="text")  # text|number|select|date|boolean
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    options: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)  # for field_type='select'
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    show_on_slip: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

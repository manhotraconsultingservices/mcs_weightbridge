"""Platform-level models — stored in the master database (weighbridge_master).

These tables support the SaaS platform admin portal:
- PlatformUser: Internal Manhotra Consulting staff (platform_admin, sales_rep)
- TenantSalesRep: Junction table linking sales reps to their assigned tenants
- PlatformBranding: Singleton row for "Powered by" branding on client login pages
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    String, Boolean, DateTime, Integer, ForeignKey, UniqueConstraint,
    CheckConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.multitenancy.models import MasterBase


class PlatformUser(MasterBase):
    """Internal staff user (platform_admin or sales_rep)."""
    __tablename__ = "platform_users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="sales_rep"
    )  # platform_admin | sales_rep
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantSalesRep(MasterBase):
    """Maps sales reps to their assigned client tenants."""
    __tablename__ = "tenant_sales_reps"
    __table_args__ = (
        UniqueConstraint("tenant_id", "platform_user_id", name="uq_tenant_salesrep"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    platform_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlatformBranding(MasterBase):
    """Singleton row — 'Powered by' branding shown on all client login pages."""
    __tablename__ = "platform_branding"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_branding_singleton"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    company_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default="Manhotra Consulting"
    )
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

"""Customer portal login (Horizon 2).

A separate identity from staff `users`: external customers log into the
self-service portal with email + password to view their invoices, statement,
e-way bills, and pay via UPI. Scoped to ONE party — a customer user can only
ever see that party's data. JWTs carry scope='customer' so a portal token
can never be used on a staff endpoint (get_current_user loads from `users`).
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class CustomerUser(Base):
    __tablename__ = "customer_users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id"))
    email: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

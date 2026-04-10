import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, Numeric, Text, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class AccountGroup(Base):
    __tablename__ = "account_groups"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("account_groups.id"))
    group_type: Mapped[str | None] = mapped_column(String(20))  # asset, liability, income, expense
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # pre-seeded, non-deletable
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    children: Mapped[list["AccountGroup"]] = relationship(back_populates="parent")
    parent: Mapped["AccountGroup | None"] = relationship(back_populates="children", remote_side="AccountGroup.id")
    accounts: Mapped[list["Account"]] = relationship(back_populates="group")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account_groups.id"))
    name: Mapped[str] = mapped_column(String(200))
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    current_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    balance_type: Mapped[str | None] = mapped_column(String(2))  # Dr or Cr
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id"))  # link to party if applicable
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    group: Mapped["AccountGroup"] = relationship(back_populates="accounts")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    fy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_years.id"))
    entry_date: Mapped[date] = mapped_column(Date)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id"))
    voucher_type: Mapped[str] = mapped_column(String(20))  # sale, purchase, receipt, payment, journal
    voucher_id: Mapped[uuid.UUID | None] = mapped_column()  # polymorphic ref to invoice/receipt/voucher
    voucher_no: Mapped[str | None] = mapped_column(String(30))
    debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    narration: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

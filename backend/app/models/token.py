import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, Numeric, Text, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Token(Base):
    __tablename__ = "tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    fy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_years.id"))
    token_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_supplement: Mapped[bool] = mapped_column(Boolean, default=False)
    token_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    # OPEN, FIRST_WEIGHT, LOADING, SECOND_WEIGHT, COMPLETED, CANCELLED
    direction: Mapped[str | None] = mapped_column(String(10))  # inbound (purchase), outbound (sale)
    token_type: Mapped[str] = mapped_column(String(20), default="sale")  # sale, purchase, general

    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id"))
    driver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drivers.id"))
    transporter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transporters.id"))
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))

    vehicle_no: Mapped[str | None] = mapped_column(String(20))  # quick entry without vehicle master

    gross_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    tare_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    net_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    first_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    second_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    first_weight_type: Mapped[str | None] = mapped_column(String(5))  # gross or tare
    first_weight_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    second_weight_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_weight_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    second_weight_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    is_manual_weight: Mapped[bool] = mapped_column(Boolean, default=False)

    remarks: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships for eager loading
    party: Mapped["Party"] = relationship("Party", foreign_keys=[party_id], lazy="noload")
    product: Mapped["Product"] = relationship("Product", foreign_keys=[product_id], lazy="noload")
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", foreign_keys=[vehicle_id], lazy="noload")
    driver: Mapped["Driver"] = relationship("Driver", foreign_keys=[driver_id], lazy="noload")
    transporter: Mapped["Transporter"] = relationship("Transporter", foreign_keys=[transporter_id], lazy="noload")

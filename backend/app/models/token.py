import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, Numeric, Text, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Token(Base):
    __tablename__ = "tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"), nullable=True)  # NULL = default branch
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
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"))
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))

    vehicle_no: Mapped[str | None] = mapped_column(String(20))  # quick entry without vehicle master
    vehicle_type: Mapped[str | None] = mapped_column(String(50))  # truck, tractor, etc.
    # Tyre count (4/6/8/10/12) — used by operator kiosk + printed slips.
    # Tracked for both weighbridge AND volume tokens so the slip shows truck class.
    tyre_count: Mapped[int | None] = mapped_column(Integer)

    gross_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    tare_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    net_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # How the net_weight was determined: 'weighbridge' (gross-tare) or 'volume' (volume_cft × bulk_density)
    weight_method: Mapped[str] = mapped_column(String(20), default="weighbridge")
    # Recorded volume in CFT (cubic feet, canonical unit) for audit trail when weight_method='volume'.
    volume_cft: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    first_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    second_weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    first_weight_type: Mapped[str | None] = mapped_column(String(5))  # gross or tare
    first_weight_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    second_weight_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_weight_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    second_weight_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    is_manual_weight: Mapped[bool] = mapped_column(Boolean, default=False)

    gate_pass: Mapped[str | None] = mapped_column(String(100))      # free-text, manual entry (legacy)
    # ── ANPR-issued gate pass + entry/exit timestamps ────────────────────────
    # gate_pass_no is auto-allocated from NumberSequence(sequence_type='gate_pass')
    # at the moment a vehicle is detected entering the gate. Format: GP/25-26/0001.
    # anpr_entry_at / anpr_exit_at are stamped by /api/v1/anpr/detect.
    gate_pass_no: Mapped[str | None] = mapped_column(String(40))
    anpr_entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anpr_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How the token was created: 'manual' (kiosk/TokenPage) | 'anpr' (gate camera) | 'kiosk'
    source: Mapped[str] = mapped_column(String(20), default="manual")
    transit_pass_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("royalty_passes.id"), nullable=True)
    vehicle_rent: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=0)
    remarks: Mapped[str | None] = mapped_column(Text)
    # Owner-defined custom attributes, keyed by custom_field_definitions.field_key
    # (e.g. {"moisture_pct": 13.5, "quality": "A"}). Definitions drive the UI/slip.
    custom_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
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

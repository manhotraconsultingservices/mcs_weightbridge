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
    # Operator-chosen billing unit for this truck (MT/QUINTAL/KG/CFT/CBM/CUM/BRASS).
    # NULL → auto-invoice falls back to the product's own unit (pre-per-unit behaviour).
    billing_unit: Mapped[str | None] = mapped_column(String(20))
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
    # Operator-entered trip distance (km) — vehicle_rent auto-computed as
    # vehicle.rent_rate_per_km_per_mt × rent_km × net_weight_MT (weight known at
    # completion). vehicle_rent stays an editable override after that.
    rent_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Operator-overridable rent rates (prefilled from the vehicle master on the token
    # form; NULL → fall back to the vehicle master). Weighed loads use the ₹/km/MT
    # rate × net MT; volume loads use the ₹/km/CUM rate × CUM. Amount → vehicle_rent.
    rent_rate_per_km_per_mt: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    rent_rate_per_km_per_cum: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    # Royalty (govt mineral levy billed to the customer). Operator opts in per token.
    # royalty_cum = the CUM (cubic metre) volume the royalty is charged on — entered
    # manually on a weighed (MT) load, or auto-derived from volume_cft (÷35.3147) on a
    # volume token. royalty_amount = product.royalty_per_cum × royalty_cum (editable
    # override). NULL royalty_cum → no royalty. Flows to the invoice like vehicle_rent.
    royalty_cum: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    # Royalty basis: 'mt' (× net weight) or 'cum' (× royalty_cum). NULL = no royalty
    # (legacy tokens with royalty_cum set are treated as 'cum'). Follows the token's
    # measurement — weighed → mt, volume → cum.
    royalty_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Operator override of the ₹-per-unit royalty rate (prefilled from the product
    # master on the form). NULL → use product.royalty_per_mt / royalty_per_cum.
    royalty_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    royalty_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=0)
    # Operator-set material price (₹ per billing_unit). Shown on the create/edit
    # token form and used by the auto-invoice (falls back to the pricing resolver
    # when NULL). Editable via PUT /tokens/{id}/pricing, which re-syncs the linked
    # draft invoice.
    rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Operator-chosen payment mode for this trip: cash | credit | upi | bank_transfer.
    # Overrides the party's default_payment_mode when deciding the auto-invoice's
    # tax_type — 'cash' → non-GST Bill of Supply, everything else → GST Tax Invoice.
    payment_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text)
    # Owner-defined custom attributes, keyed by custom_field_definitions.field_key
    # (e.g. {"moisture_pct": 13.5, "quality": "A"}). Definitions drive the UI/slip.
    custom_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Offline replay (P1 #171): the client-generated op id that produced this
    # row (deduped via ux_tokens_client_op) + where it originated. NULL /
    # 'online' for normal cloud writes; set when a token was captured offline.
    client_op_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    origin: Mapped[str] = mapped_column(String(10), default="online")
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

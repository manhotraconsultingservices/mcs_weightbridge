"""Pydantic schemas for production cycles + yield metrics."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, field_validator


class CycleOutputCreate(BaseModel):
    product_id: uuid.UUID
    output_kg: Decimal

    @field_validator("output_kg")
    @classmethod
    def non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("output_kg must be >= 0")
        return v


class CycleOutputResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str = ""    # joined from products
    output_kg: Decimal
    model_config = {"from_attributes": True}


class ProductionCycleCreate(BaseModel):
    cycle_date: date
    raw_material_id: Optional[uuid.UUID] = None   # input material (Product with is_raw_material=True)
    input_kg: Decimal
    stage1_output_kg: Optional[Decimal] = None
    stage2_output_kg: Optional[Decimal] = None
    stage3_output_kg: Optional[Decimal] = None
    notes: Optional[str] = None
    outputs: List[CycleOutputCreate] = []

    @field_validator("input_kg")
    @classmethod
    def input_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("input_kg must be greater than 0")
        return v


class ProductionCycleUpdate(BaseModel):
    raw_material_id: Optional[uuid.UUID] = None
    input_kg: Optional[Decimal] = None
    stage1_output_kg: Optional[Decimal] = None
    stage2_output_kg: Optional[Decimal] = None
    stage3_output_kg: Optional[Decimal] = None
    notes: Optional[str] = None
    outputs: Optional[List[CycleOutputCreate]] = None  # if provided, replaces existing outputs


class ProductionCycleResponse(BaseModel):
    id: uuid.UUID
    cycle_no: int
    cycle_date: date
    raw_material_id: Optional[uuid.UUID] = None
    raw_material_name: Optional[str] = None           # joined for display
    input_kg: Decimal
    stage1_output_kg: Optional[Decimal]
    stage2_output_kg: Optional[Decimal]
    stage3_output_kg: Optional[Decimal]
    total_output_kg: Decimal = Decimal("0")     # sum of outputs
    yield_pct: Optional[float] = None           # total_output / input * 100
    belt_loss_pct: Optional[float] = None       # (stage3 - total_output) / stage3 * 100
    wastage_kg: Decimal = Decimal("0")          # input - total_output
    is_finalised: bool
    notes: Optional[str]
    outputs: List[CycleOutputResponse]
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ProductionCycleListResponse(BaseModel):
    items: List[ProductionCycleResponse]
    total: int
    page: int
    page_size: int


# ── Dashboard schemas ─────────────────────────────────────────────────────────

class YieldTrendPoint(BaseModel):
    date: str           # "DD MMM"
    yield_pct: float
    input_kg: float
    output_kg: float


class WastageStagePoint(BaseModel):
    date: str
    stage1_loss_pct: float
    stage2_loss_pct: float
    stage3_loss_pct: float
    belt_loss_pct: float


class ProductWastage(BaseModel):
    product_id: uuid.UUID
    product_name: str
    total_output_kg: float
    avg_output_per_cycle: float


class ProductionDashboardResponse(BaseModel):
    yield_trend: List[YieldTrendPoint]
    wastage_by_stage: List[WastageStagePoint]
    top_outputs: List[ProductWastage]
    summary: dict     # { input_total, output_total, avg_yield_pct, avg_belt_loss_pct, cycles_count }


# ── Stage defaults (configurable yield/loss expectations per stage) ──────────

class StageDefault(BaseModel):
    """One stage's default expected yield + naming.

    The four stones-crusher stages are fixed in number (1-4), but their names
    and expected yields can be tuned per operation.
    """
    stage_no: int                          # 1, 2, 3, 4
    stage_name: str                        # "Primary Crushing", etc.
    loss_type: str                         # "Dust & Spillage Loss", etc.
    expected_yield_pct: float              # e.g. 97.5 — yield this stage targets
    warning_threshold_pct: float = 2.0     # variance band: |actual - expected| above this → warning


class StageDefaultsResponse(BaseModel):
    stages: List[StageDefault]
    overall_expected_yield_pct: float      # product of all stages: ~80.8% by default


class StageDefaultsUpdate(BaseModel):
    """Bulk update — replaces all four stages atomically."""
    stages: List[StageDefault]

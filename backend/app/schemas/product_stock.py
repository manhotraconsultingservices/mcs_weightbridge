"""Pydantic schemas for product (finished-goods) stock."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, field_validator


class ProductStockResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str = ""          # joined from products
    unit: str = ""                  # joined from products
    current_stock: Decimal
    min_stock_level: Decimal
    stock_status: str = "ok"        # ok | low | out
    last_alerted_at: Optional[datetime] = None
    updated_at: datetime
    model_config = {"from_attributes": True}


class UpdateMinStockRequest(BaseModel):
    min_stock_level: Decimal

    @field_validator("min_stock_level")
    @classmethod
    def non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("min_stock_level must be >= 0")
        return v


class StockAdjustmentRequest(BaseModel):
    """Adjust stock by a signed quantity. Reason is required for audit."""
    product_id: uuid.UUID
    quantity: Decimal     # signed: + add, − remove
    reason: str

    @field_validator("reason")
    @classmethod
    def reason_required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Reason is required")
        return v.strip()


class OpeningStockRequest(BaseModel):
    """Set opening stock — only allowed when current_stock = 0."""
    product_id: uuid.UUID
    opening_quantity: Decimal
    notes: Optional[str] = None

    @field_validator("opening_quantity")
    @classmethod
    def must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("opening_quantity must be greater than 0")
        return v


class MovementResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str = ""
    movement_type: str
    quantity: Decimal
    stock_before: Decimal
    stock_after: Decimal
    reference_type: Optional[str] = None
    reference_id: Optional[uuid.UUID] = None
    reference_no: Optional[str] = None
    notes: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class MovementListResponse(BaseModel):
    items: List[MovementResponse]
    total: int
    page: int
    page_size: int


class ProductStockListResponse(BaseModel):
    items: List[ProductStockResponse]
    total: int

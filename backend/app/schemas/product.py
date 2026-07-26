import uuid
from decimal import Decimal
from pydantic import BaseModel


class ProductCategoryCreate(BaseModel):
    name: str
    description: str | None = None
    sort_order: int = 0


class ProductCategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    sort_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class ProductCreate(BaseModel):
    category_id: uuid.UUID | None = None
    name: str
    code: str | None = None
    hsn_code: str = "2517"
    unit: str = "MT"
    default_rate: Decimal = Decimal("0")
    gst_rate: Decimal = Decimal("5.00")
    bulk_density: Decimal | None = None   # kg/CFT
    royalty_per_cum: Decimal | None = None   # ₹ royalty per cubic metre (CUM)
    is_raw_material: bool = False         # mark inputs to production
    description: str | None = None


class ProductUpdate(BaseModel):
    category_id: uuid.UUID | None = None
    name: str | None = None
    code: str | None = None
    hsn_code: str | None = None
    unit: str | None = None
    default_rate: Decimal | None = None
    gst_rate: Decimal | None = None
    bulk_density: Decimal | None = None
    royalty_per_cum: Decimal | None = None   # ₹ royalty per cubic metre (CUM)
    is_raw_material: bool | None = None
    description: str | None = None
    is_active: bool | None = None


class ProductRateBulkItem(BaseModel):
    product_id: uuid.UUID
    default_rate: Decimal | None = None
    gst_rate: Decimal | None = None


class ProductRatesBulkRequest(BaseModel):
    """Bulk-set default_rate (and optionally gst_rate) for many products at once."""
    items: list[ProductRateBulkItem]


class ProductUnitRateItem(BaseModel):
    product_id: uuid.UUID
    unit: str
    rate: Decimal | None = None   # None → clear that (product, unit) rate


class ProductUnitRatesBulkRequest(BaseModel):
    """Bulk-set per-unit default rates (₹/MT, ₹/CFT, ₹/CBM, ₹/Brass…)."""
    items: list[ProductUnitRateItem]


class ProductResponse(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    name: str
    code: str | None
    hsn_code: str
    unit: str
    default_rate: Decimal
    gst_rate: Decimal
    bulk_density: Decimal | None = None
    royalty_per_cum: Decimal | None = None   # ₹ royalty per cubic metre (CUM)
    is_raw_material: bool = False
    description: str | None
    is_active: bool

    model_config = {"from_attributes": True}

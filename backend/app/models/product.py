import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Numeric, Text, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ProductCategory(Base):
    __tablename__ = "product_categories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("product_categories.id"))
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str | None] = mapped_column(String(50))
    hsn_code: Mapped[str] = mapped_column(String(8), default="2517")
    unit: Mapped[str] = mapped_column(String(10))  # MT, CFT, BRASS, CUM, NOS
    default_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=5.00)
    # Govt mineral royalty rate, ₹ per cubic metre (CUM). Nullable — set per item on
    # the Products page. When an operator applies royalty on a token, the charge is
    # royalty_per_cum × the token's CUM volume, billed on the token + invoice.
    royalty_per_cum: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # Alternate royalty basis: ₹ per metric tonne (MT). Used when the token is
    # weighed (billed by weight); the token's royalty_unit picks mt vs cum.
    royalty_per_mt: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # Bulk density in kg/CFT — enables volume → weight conversion at token creation.
    # NULL means volume mode is not available for this product.
    # Industry typicals (per CFT, kg): aggregate ≈ 42.5, sand ≈ 48.1, GSB ≈ 53.8,
    # stone dust ≈ 43.9. Conversion from older t/m³ units: ×28.3168.
    bulk_density: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    # Raw-material flag — only relevant for products that are INPUTS to production
    # (e.g. "Raw Boulder"). When a production cycle's raw_material_id points
    # here, finalising the cycle posts a negative stock movement = input consumed.
    is_raw_material: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    category: Mapped["ProductCategory | None"] = relationship(back_populates="products")

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.product import Product, ProductCategory
from app.models.product_unit_rate import ProductUnitRate
from app.schemas.product import (
    ProductCreate, ProductUpdate, ProductResponse,
    ProductCategoryCreate, ProductCategoryResponse,
    ProductRatesBulkRequest, ProductUnitRatesBulkRequest,
)

router = APIRouter()


# --- Product Categories ---

@router.get("/product-categories", response_model=list[ProductCategoryResponse])
async def list_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ProductCategory)
        .where(ProductCategory.company_id == current_user.company_id, ProductCategory.is_active == True)
        .order_by(ProductCategory.sort_order, ProductCategory.name)
    )
    return [ProductCategoryResponse.model_validate(c) for c in result.scalars().all()]


@router.post("/product-categories", response_model=ProductCategoryResponse, status_code=201)
async def create_category(
    data: ProductCategoryCreate,
    current_user: User = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
):
    cat = ProductCategory(company_id=current_user.company_id, **data.model_dump())
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return ProductCategoryResponse.model_validate(cat)


@router.put("/product-categories/{cat_id}", response_model=ProductCategoryResponse)
async def update_category(
    cat_id: uuid.UUID,
    data: ProductCategoryCreate,
    current_user: User = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ProductCategory).where(ProductCategory.id == cat_id, ProductCategory.company_id == current_user.company_id)
    )
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    for field, value in data.model_dump().items():
        setattr(cat, field, value)
    await db.commit()
    await db.refresh(cat)
    return ProductCategoryResponse.model_validate(cat)


# --- Products ---

@router.get("/products", response_model=dict)
async def list_products(
    category_id: uuid.UUID | None = None,
    active_only: bool = True,
    is_raw_material: bool | None = None,    # True → only raw materials, False → only finished goods
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List products with pagination. Pass page_size=9999 for dropdown use.

    `is_raw_material=true` filter is used by the Production page's raw-material
    picker. Default (None) returns all products.
    """
    base_q = select(Product).where(Product.company_id == current_user.company_id)
    if active_only:
        base_q = base_q.where(Product.is_active == True)
    if category_id:
        base_q = base_q.where(Product.category_id == category_id)
    if is_raw_material is not None:
        base_q = base_q.where(Product.is_raw_material == is_raw_material)
    if search:
        base_q = base_q.where(or_(
            Product.name.ilike(f"%{search}%"),
            Product.hsn_code.ilike(f"%{search}%"),
        ))

    total = (await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )).scalar() or 0

    query = base_q.order_by(Product.name).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = [ProductResponse.model_validate(p) for p in result.scalars().all()]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(
    data: ProductCreate,
    current_user: User = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
):
    product = Product(company_id=current_user.company_id, **data.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return ProductResponse.model_validate(product)


# NOTE: must be defined BEFORE `PUT /products/{product_id}` so the literal
# "default-rates" path isn't swallowed as a {product_id} UUID.
@router.put("/products/default-rates")
async def bulk_update_default_rates(
    data: ProductRatesBulkRequest,
    current_user: User = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-set default_rate (and optionally gst_rate) for many products at once.

    Powers the Pricing → Default Rates editor (avoids editing products one by
    one). Company-scoped; unknown/foreign product ids are skipped. Only the
    fields provided per item are updated.
    """
    if not data.items:
        return {"updated": 0}
    ids = [i.product_id for i in data.items]
    prods = {p.id: p for p in (await db.execute(
        select(Product).where(Product.id.in_(ids), Product.company_id == current_user.company_id)
    )).scalars().all()}
    updated = 0
    for it in data.items:
        p = prods.get(it.product_id)
        if not p:
            continue
        changed = False
        if it.default_rate is not None:
            if it.default_rate < 0:
                raise HTTPException(400, f"Rate cannot be negative for '{p.name}'")
            p.default_rate = it.default_rate
            changed = True
        if it.gst_rate is not None:
            if it.gst_rate < 0:
                raise HTTPException(400, f"GST rate cannot be negative for '{p.name}'")
            p.gst_rate = it.gst_rate
            changed = True
        if changed:
            updated += 1
    await db.commit()
    return {"updated": updated}


@router.get("/products/unit-rates")
async def get_product_unit_rates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-unit default rates for every active product (powers Pricing → Default
    Rates by unit). Returns each product's base `unit` + `default_rate` plus its
    `product_unit_rates` cells as `{ "MT": 500, "CFT": 42, … }`."""
    prods = (await db.execute(
        select(Product).where(Product.company_id == current_user.company_id, Product.is_active == True)
        .order_by(Product.name)
    )).scalars().all()
    cells = (await db.execute(
        select(ProductUnitRate).where(ProductUnitRate.company_id == current_user.company_id)
    )).scalars().all()
    by_prod: dict = {}
    for c in cells:
        by_prod.setdefault(c.product_id, {})[(c.unit or "").upper()] = float(c.rate)
    rows = []
    for p in prods:
        rates = dict(by_prod.get(p.id, {}))
        # Mirror the legacy single default_rate onto the base unit if not overridden.
        base = (p.unit or "").upper()
        if base and base not in rates and p.default_rate:
            rates[base] = float(p.default_rate)
        rows.append({
            "product_id": str(p.id), "name": p.name, "hsn_code": p.hsn_code,
            "base_unit": p.unit, "gst_rate": float(p.gst_rate or 0), "rates": rates,
        })
    return {"rows": rows}


@router.put("/products/unit-rates")
async def bulk_update_unit_rates(
    data: ProductUnitRatesBulkRequest,
    current_user: User = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
):
    """Upsert per-unit default rates. When a unit == the product's base unit, the
    value is mirrored into `products.default_rate` so legacy single-rate readers
    stay correct. `rate=None` clears that (product, unit) cell."""
    if not data.items:
        return {"updated": 0}
    ids = {i.product_id for i in data.items}
    prods = {p.id: p for p in (await db.execute(
        select(Product).where(Product.id.in_(ids), Product.company_id == current_user.company_id)
    )).scalars().all()}
    updated = 0
    for it in data.items:
        p = prods.get(it.product_id)
        if not p:
            continue
        unit = (it.unit or "").strip().upper()
        if not unit:
            continue
        existing = (await db.execute(
            select(ProductUnitRate).where(
                ProductUnitRate.product_id == it.product_id,
                func.upper(ProductUnitRate.unit) == unit,
            )
        )).scalar_one_or_none()
        if it.rate is None:
            if existing:
                await db.delete(existing)
                updated += 1
            continue
        if it.rate < 0:
            raise HTTPException(400, f"Rate cannot be negative for '{p.name}' ({unit})")
        if existing:
            existing.rate = it.rate
        else:
            db.add(ProductUnitRate(company_id=current_user.company_id, product_id=it.product_id, unit=unit, rate=it.rate))
        if unit == (p.unit or "").upper():   # keep legacy default_rate in sync
            p.default_rate = it.rate
        updated += 1
    await db.commit()
    return {"updated": updated}


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.company_id == current_user.company_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductResponse.model_validate(product)


@router.put("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    data: ProductUpdate,
    current_user: User = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.company_id == current_user.company_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    await db.commit()
    await db.refresh(product)
    return ProductResponse.model_validate(product)


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.company_id == current_user.company_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.is_active = False  # Soft delete
    await db.commit()
    return {"message": "Product deactivated"}

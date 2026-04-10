import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.product import Product, ProductCategory
from app.schemas.product import (
    ProductCreate, ProductUpdate, ProductResponse,
    ProductCategoryCreate, ProductCategoryResponse,
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
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List products with pagination. Pass page_size=9999 for dropdown use."""
    base_q = select(Product).where(Product.company_id == current_user.company_id)
    if active_only:
        base_q = base_q.where(Product.is_active == True)
    if category_id:
        base_q = base_q.where(Product.category_id == category_id)
    if search:
        base_q = base_q.where(Product.name.ilike(f"%{search}%"))

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

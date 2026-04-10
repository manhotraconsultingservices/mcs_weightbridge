import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.company import Company, FinancialYear
from app.schemas.company import CompanyUpdate, CompanyResponse, FinancialYearCreate, FinancialYearResponse

router = APIRouter()


@router.get("", response_model=CompanyResponse)
async def get_company(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Company).where(Company.id == current_user.company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return CompanyResponse.model_validate(company)


@router.put("", response_model=CompanyResponse)
async def update_company(
    data: CompanyUpdate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Company).where(Company.id == current_user.company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
    await db.commit()
    await db.refresh(company)
    return CompanyResponse.model_validate(company)


@router.get("/financial-years", response_model=list[FinancialYearResponse])
async def list_financial_years(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FinancialYear)
        .where(FinancialYear.company_id == current_user.company_id)
        .order_by(FinancialYear.start_date.desc())
    )
    return [FinancialYearResponse.model_validate(fy) for fy in result.scalars().all()]


@router.post("/financial-years", response_model=FinancialYearResponse, status_code=201)
async def create_financial_year(
    data: FinancialYearCreate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    fy = FinancialYear(
        company_id=current_user.company_id,
        label=data.label,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    db.add(fy)
    await db.commit()
    await db.refresh(fy)
    return FinancialYearResponse.model_validate(fy)


@router.put("/financial-years/{fy_id}/activate", response_model=FinancialYearResponse)
async def activate_financial_year(
    fy_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    # Deactivate all
    result = await db.execute(
        select(FinancialYear).where(FinancialYear.company_id == current_user.company_id)
    )
    for fy in result.scalars().all():
        fy.is_active = False

    # Activate selected
    result = await db.execute(
        select(FinancialYear).where(FinancialYear.id == fy_id, FinancialYear.company_id == current_user.company_id)
    )
    fy = result.scalar_one_or_none()
    if not fy:
        raise HTTPException(status_code=404, detail="Financial year not found")

    fy.is_active = True
    await db.commit()
    await db.refresh(fy)
    return FinancialYearResponse.model_validate(fy)

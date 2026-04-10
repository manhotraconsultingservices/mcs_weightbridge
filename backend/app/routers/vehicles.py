import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.vehicle import Vehicle, TareWeightHistory, Driver, Transporter
from app.schemas.vehicle import (
    VehicleCreate, VehicleUpdate, VehicleResponse, TareWeightHistoryResponse,
    DriverCreate, DriverResponse,
    TransporterCreate, TransporterResponse,
)

router = APIRouter()


# --- Vehicles ---

@router.get("/vehicles", response_model=dict)
async def list_vehicles(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List vehicles with pagination. Pass page_size=9999 for dropdown use."""
    base_q = select(Vehicle).where(Vehicle.company_id == current_user.company_id, Vehicle.is_active == True)
    if search:
        base_q = base_q.where(Vehicle.registration_no.ilike(f"%{search}%"))

    total = (await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )).scalar() or 0

    query = base_q.order_by(Vehicle.registration_no).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = [VehicleResponse.model_validate(v) for v in result.scalars().all()]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/vehicles", response_model=VehicleResponse, status_code=201)
async def create_vehicle(
    data: VehicleCreate,
    current_user: User = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
):
    vehicle = Vehicle(company_id=current_user.company_id, **data.model_dump())
    db.add(vehicle)
    await db.commit()
    await db.refresh(vehicle)
    return VehicleResponse.model_validate(vehicle)


@router.get("/vehicles/search", response_model=list[VehicleResponse])
async def search_vehicles(
    reg: str = Query(..., min_length=2),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Vehicle)
        .where(Vehicle.company_id == current_user.company_id, Vehicle.registration_no.ilike(f"%{reg}%"), Vehicle.is_active == True)
        .limit(10)
    )
    return [VehicleResponse.model_validate(v) for v in result.scalars().all()]


@router.get("/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.company_id == current_user.company_id)
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return VehicleResponse.model_validate(vehicle)


@router.put("/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    vehicle_id: uuid.UUID,
    data: VehicleUpdate,
    current_user: User = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.company_id == current_user.company_id)
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(vehicle, field, value)
    await db.commit()
    await db.refresh(vehicle)
    return VehicleResponse.model_validate(vehicle)


@router.get("/vehicles/{vehicle_id}/tare-history", response_model=list[TareWeightHistoryResponse])
async def get_tare_history(
    vehicle_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TareWeightHistory)
        .where(TareWeightHistory.vehicle_id == vehicle_id)
        .order_by(TareWeightHistory.recorded_at.desc())
        .limit(20)
    )
    return [TareWeightHistoryResponse.model_validate(t) for t in result.scalars().all()]


# --- Drivers ---

@router.get("/drivers", response_model=dict)
async def list_drivers(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base_q = select(Driver).where(Driver.company_id == current_user.company_id, Driver.is_active == True)
    if search:
        base_q = base_q.where(Driver.name.ilike(f"%{search}%"))
    total = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar() or 0
    result = await db.execute(base_q.order_by(Driver.name).offset((page - 1) * page_size).limit(page_size))
    return {"items": [DriverResponse.model_validate(d) for d in result.scalars().all()], "total": total, "page": page, "page_size": page_size}


@router.post("/drivers", response_model=DriverResponse, status_code=201)
async def create_driver(
    data: DriverCreate,
    current_user: User = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
):
    driver = Driver(company_id=current_user.company_id, **data.model_dump())
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return DriverResponse.model_validate(driver)


@router.put("/drivers/{driver_id}", response_model=DriverResponse)
async def update_driver(
    driver_id: uuid.UUID,
    data: DriverCreate,
    current_user: User = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Driver).where(Driver.id == driver_id, Driver.company_id == current_user.company_id)
    )
    driver = result.scalar_one_or_none()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(driver, field, value)
    await db.commit()
    await db.refresh(driver)
    return DriverResponse.model_validate(driver)


# --- Transporters ---

@router.get("/transporters", response_model=dict)
async def list_transporters(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base_q = select(Transporter).where(Transporter.company_id == current_user.company_id, Transporter.is_active == True)
    if search:
        base_q = base_q.where(Transporter.name.ilike(f"%{search}%"))
    total = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar() or 0
    result = await db.execute(base_q.order_by(Transporter.name).offset((page - 1) * page_size).limit(page_size))
    return {"items": [TransporterResponse.model_validate(t) for t in result.scalars().all()], "total": total, "page": page, "page_size": page_size}


@router.post("/transporters", response_model=TransporterResponse, status_code=201)
async def create_transporter(
    data: TransporterCreate,
    current_user: User = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
):
    transporter = Transporter(company_id=current_user.company_id, **data.model_dump())
    db.add(transporter)
    await db.commit()
    await db.refresh(transporter)
    return TransporterResponse.model_validate(transporter)


@router.put("/transporters/{transporter_id}", response_model=TransporterResponse)
async def update_transporter(
    transporter_id: uuid.UUID,
    data: TransporterCreate,
    current_user: User = Depends(require_role("admin", "operator")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Transporter).where(Transporter.id == transporter_id, Transporter.company_id == current_user.company_id)
    )
    transporter = result.scalar_one_or_none()
    if not transporter:
        raise HTTPException(status_code=404, detail="Transporter not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(transporter, field, value)
    await db.commit()
    await db.refresh(transporter)
    return TransporterResponse.model_validate(transporter)

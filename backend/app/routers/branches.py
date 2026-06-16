"""Branch / plant management (Horizon 3 — full multi-branch).

A company runs N plants/weighbridges. Each branch carries its own number series
(invoices/tokens/gate passes) and can have its own GSTIN. Backward-compatible:
with zero branches defined, everything runs as the single default (NULL) branch.
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role, get_current_branch_id
from app.models.branch import Branch
from app.models.user import User

router = APIRouter(prefix="/api/v1/branches", tags=["Branches"])


class BranchCreate(BaseModel):
    name: str
    code: str
    gstin: Optional[str] = None
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    pincode: Optional[str] = None
    phone: Optional[str] = None
    is_default: bool = False


class BranchUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    gstin: Optional[str] = None
    address_line1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    pincode: Optional[str] = None
    phone: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class BranchResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    gstin: Optional[str]
    address_line1: Optional[str]
    city: Optional[str]
    state: Optional[str]
    state_code: Optional[str]
    pincode: Optional[str]
    phone: Optional[str]
    is_default: bool
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


@router.get("", response_model=list[BranchResponse])
async def list_branches(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Branch).where(Branch.company_id == current_user.company_id)
    if not include_inactive:
        stmt = stmt.where(Branch.is_active == True)
    rows = (await db.execute(stmt.order_by(Branch.is_default.desc(), Branch.name))).scalars().all()
    return [BranchResponse.model_validate(b) for b in rows]


@router.get("/current")
async def current_branch(
    branch_id=Depends(get_current_branch_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resolve the active branch for this request (from header / user / default)."""
    if not branch_id:
        return {"branch_id": None, "name": "All branches", "code": "ALL", "can_switch": current_user.role == "admin"}
    b = (await db.execute(select(Branch).where(Branch.id == branch_id))).scalar_one_or_none()
    if not b:
        return {"branch_id": None, "name": "All branches", "code": "ALL", "can_switch": current_user.role == "admin"}
    return {"branch_id": str(b.id), "name": b.name, "code": b.code, "can_switch": current_user.role == "admin"}


@router.post("", response_model=BranchResponse, status_code=201)
async def create_branch(
    payload: BranchCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if payload.is_default:
        # only one default
        for b in (await db.execute(select(Branch).where(
            Branch.company_id == current_user.company_id, Branch.is_default == True
        ))).scalars().all():
            b.is_default = False
    branch = Branch(
        company_id=current_user.company_id,
        name=payload.name.strip(), code=payload.code.strip().upper()[:12],
        gstin=payload.gstin, address_line1=payload.address_line1,
        city=payload.city, state=payload.state, state_code=payload.state_code,
        pincode=payload.pincode, phone=payload.phone,
        is_default=payload.is_default, is_active=True,
    )
    db.add(branch)
    await db.commit()
    await db.refresh(branch)
    return BranchResponse.model_validate(branch)


@router.put("/{branch_id}", response_model=BranchResponse)
async def update_branch(
    branch_id: uuid.UUID,
    payload: BranchUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    b = (await db.execute(select(Branch).where(
        Branch.id == branch_id, Branch.company_id == current_user.company_id
    ))).scalar_one_or_none()
    if not b:
        raise HTTPException(404, "Branch not found")
    data = payload.model_dump(exclude_unset=True)
    if data.get("is_default"):
        for other in (await db.execute(select(Branch).where(
            Branch.company_id == current_user.company_id, Branch.is_default == True, Branch.id != branch_id
        ))).scalars().all():
            other.is_default = False
    for k, v in data.items():
        if k == "code" and v:
            v = v.strip().upper()[:12]
        setattr(b, k, v)
    await db.commit()
    await db.refresh(b)
    return BranchResponse.model_validate(b)


@router.delete("/{branch_id}")
async def deactivate_branch(
    branch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    b = (await db.execute(select(Branch).where(
        Branch.id == branch_id, Branch.company_id == current_user.company_id
    ))).scalar_one_or_none()
    if not b:
        raise HTTPException(404, "Branch not found")
    b.is_active = False
    await db.commit()
    return {"ok": True}

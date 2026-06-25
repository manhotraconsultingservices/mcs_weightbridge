"""
Owner-managed custom attributes (custom fields).

Definitions are per-tenant (company-scoped) and live in `custom_field_definitions`.
Values live in a JSONB column on the target entity (v1: tokens.custom_fields).
The admin "Custom Fields" matrix manages definitions; weighment forms + the slip
render them dynamically. Relevance is automatic — a tenant only sees its own defs.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.custom_field import CustomFieldDefinition
from app.schemas.custom_field import (
    CustomFieldDefinitionCreate,
    CustomFieldDefinitionUpdate,
    CustomFieldDefinitionOut,
    _slugify_key,
)
from app.multitenancy.industry import industry_default_fields

router = APIRouter(prefix="/api/v1/custom-fields", tags=["custom-fields"])


async def _get_owned(db: AsyncSession, company_id, field_id: uuid.UUID) -> CustomFieldDefinition:
    row = (await db.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.id == field_id,
            CustomFieldDefinition.company_id == company_id,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Custom field not found")
    return row


@router.get("", response_model=list[CustomFieldDefinitionOut])
async def list_custom_fields(
    entity_type: str | None = Query(None, description="Filter by entity (token/product/party)"),
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List custom-field definitions for the current tenant (any authenticated user
    — the weighment form needs them to render)."""
    q = select(CustomFieldDefinition).where(CustomFieldDefinition.company_id == current_user.company_id)
    if entity_type:
        q = q.where(CustomFieldDefinition.entity_type == entity_type.lower())
    if not include_inactive:
        q = q.where(CustomFieldDefinition.is_active.is_(True))
    q = q.order_by(CustomFieldDefinition.sort_order, CustomFieldDefinition.label)
    return (await db.execute(q)).scalars().all()


@router.post("", response_model=CustomFieldDefinitionOut, status_code=201)
async def create_custom_field(
    payload: CustomFieldDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    key = _slugify_key(payload.field_key or payload.label)
    # Unique per (company, entity_type, field_key)
    exists = (await db.execute(
        select(CustomFieldDefinition.id).where(
            CustomFieldDefinition.company_id == current_user.company_id,
            CustomFieldDefinition.entity_type == payload.entity_type,
            CustomFieldDefinition.field_key == key,
        )
    )).scalar_one_or_none()
    if exists:
        raise HTTPException(409, f"A field with key '{key}' already exists for {payload.entity_type}")
    row = CustomFieldDefinition(
        company_id=current_user.company_id,
        entity_type=payload.entity_type,
        field_key=key,
        label=payload.label,
        field_type=payload.field_type,
        unit=payload.unit,
        options=payload.options,
        required=payload.required,
        show_on_slip=payload.show_on_slip,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.put("/{field_id}", response_model=CustomFieldDefinitionOut)
async def update_custom_field(
    field_id: uuid.UUID,
    payload: CustomFieldDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    row = await _get_owned(db, current_user.company_id, field_id)
    data = payload.model_dump(exclude_unset=True)
    # field_key + entity_type are immutable (values are keyed by them).
    for k, v in data.items():
        setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{field_id}", status_code=204)
async def delete_custom_field(
    field_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    row = await _get_owned(db, current_user.company_id, field_id)
    await db.delete(row)
    await db.commit()
    return None


@router.post("/seed-defaults", response_model=list[CustomFieldDefinitionOut])
async def seed_default_fields(
    industry: str = Query(..., description="Industry whose starter fields to seed"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Idempotently seed the starter custom fields for an industry (skips any
    field_key that already exists). Used by the admin page to one-click add the
    recommended fields for a vertical (e.g. Moisture % + Quality for maize)."""
    defaults = industry_default_fields(industry)
    if not defaults:
        return []
    existing = set((await db.execute(
        select(CustomFieldDefinition.entity_type, CustomFieldDefinition.field_key)
        .where(CustomFieldDefinition.company_id == current_user.company_id)
    )).all())
    created: list[CustomFieldDefinition] = []
    for f in defaults:
        et = (f.get("entity_type") or "token").lower()
        key = _slugify_key(f.get("field_key") or f["label"])
        if (et, key) in existing:
            continue
        row = CustomFieldDefinition(
            company_id=current_user.company_id,
            entity_type=et,
            field_key=key,
            label=f["label"],
            field_type=f.get("field_type", "text"),
            unit=f.get("unit"),
            options=f.get("options"),
            required=bool(f.get("required", False)),
            show_on_slip=bool(f.get("show_on_slip", True)),
            sort_order=int(f.get("sort_order", 0)),
            is_active=True,
        )
        db.add(row)
        created.append(row)
    if created:
        await db.commit()
        for r in created:
            await db.refresh(r)
    return created

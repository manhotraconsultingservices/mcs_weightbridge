"""Pydantic schemas for tenant management API."""

import re
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,30}$")


class TenantCreate(BaseModel):
    slug: str
    display_name: str
    admin_username: str = "admin"
    admin_password: str
    company_name: str
    company_gstin: Optional[str] = None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not SLUG_PATTERN.match(v):
            raise ValueError(
                "Slug must be 3-31 chars, start with letter, "
                "only lowercase letters/digits/underscores"
            )
        # Reserved slugs
        if v in ("admin", "master", "system", "public", "default", "api", "www"):
            raise ValueError(f"'{v}' is a reserved slug")
        return v


class TenantUpdate(BaseModel):
    display_name: Optional[str] = None
    is_active: Optional[bool] = None
    config: Optional[dict] = None


class TenantResponse(BaseModel):
    id: UUID
    slug: str
    display_name: str
    db_name: str
    is_active: bool
    agent_api_key: str
    config: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TenantCreateResponse(BaseModel):
    tenant: TenantResponse
    admin_username: str
    message: str


class TenantListResponse(BaseModel):
    tenants: list[TenantResponse]
    total: int

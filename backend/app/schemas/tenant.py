"""Pydantic schemas for tenant management API."""

import re
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,30}$")  # hyphens only (no underscores — invalid in DNS)


class TenantCreate(BaseModel):
    slug: str
    display_name: str
    admin_username: str = "admin"
    admin_password: str
    company_name: str
    company_gstin: Optional[str] = None
    amc_start_date: Optional[date] = None
    amc_expiry_date: Optional[date] = None

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
        if v in ("admin", "master", "system", "public", "default", "api", "www", "platform"):
            raise ValueError(f"'{v}' is a reserved slug")
        return v


class TenantUpdate(BaseModel):
    display_name: Optional[str] = None
    is_active: Optional[bool] = None
    status: Optional[str] = None              # active / readonly / suspended
    config: Optional[dict] = None
    amc_start_date: Optional[date] = None
    amc_expiry_date: Optional[date] = None
    logo_url: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None


class TenantResponse(BaseModel):
    id: UUID
    slug: str
    display_name: str
    db_name: str
    is_active: bool
    status: str = "active"
    agent_api_key: str
    config: Optional[dict] = None
    amc_start_date: Optional[date] = None
    amc_expiry_date: Optional[date] = None
    logo_url: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
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

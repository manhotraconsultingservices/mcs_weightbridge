"""Pydantic schemas for the SaaS platform admin portal."""

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Platform User ─────────────────────────────────────────────────────────────

class PlatformUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=100)
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    role: str = Field(default="sales_rep", pattern=r"^(platform_admin|sales_rep)$")


class PlatformUserUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    role: str | None = None
    is_active: bool | None = None


class PlatformUserResponse(BaseModel):
    id: UUID
    username: str
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ── Platform Auth ─────────────────────────────────────────────────────────────

class PlatformLoginRequest(BaseModel):
    username: str
    password: str


class PlatformTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: PlatformUserResponse


# ── Platform Branding ─────────────────────────────────────────────────────────

class PlatformBrandingResponse(BaseModel):
    company_name: str
    website: str | None = None
    email: str | None = None
    logo_url: str | None = None


class PlatformBrandingUpdate(BaseModel):
    company_name: str | None = None
    website: str | None = None
    email: str | None = None
    logo_url: str | None = None


# ── Tenant Info (public, no auth) ─────────────────────────────────────────────

class TenantPublicInfo(BaseModel):
    slug: str
    display_name: str
    logo_url: str | None = None
    status: str
    branding: PlatformBrandingResponse


# ── Tenant with sales rep details (platform admin view) ───────────────────────

class SalesRepBrief(BaseModel):
    id: UUID
    full_name: str | None = None
    email: str | None = None
    username: str


class TenantOverview(BaseModel):
    id: UUID
    slug: str
    display_name: str
    db_name: str
    is_active: bool
    status: str
    amc_start_date: date | None = None
    amc_expiry_date: date | None = None
    logo_url: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    agent_api_key: str
    config: dict | None = None
    created_at: datetime
    updated_at: datetime
    sales_reps: list[SalesRepBrief] = []


class TenantListResponse(BaseModel):
    tenants: list[TenantOverview]
    total: int


# ── Sales Rep Assignment ──────────────────────────────────────────────────────

class SalesRepAssign(BaseModel):
    platform_user_id: UUID


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=6, max_length=100)

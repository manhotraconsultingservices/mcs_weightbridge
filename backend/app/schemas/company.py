import uuid
from datetime import date
from pydantic import BaseModel


class CompanyUpdate(BaseModel):
    name: str | None = None
    legal_name: str | None = None
    gstin: str | None = None
    pan: str | None = None
    cin: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    state_code: str | None = None
    pincode: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    bank_name: str | None = None
    bank_account_no: str | None = None
    bank_ifsc: str | None = None
    bank_branch: str | None = None
    invoice_prefix: str | None = None
    quotation_prefix: str | None = None
    purchase_prefix: str | None = None


class CompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    legal_name: str | None
    gstin: str | None
    pan: str | None
    address_line1: str | None
    city: str | None
    state: str | None
    state_code: str | None
    pincode: str | None
    phone: str | None
    email: str | None
    invoice_prefix: str
    quotation_prefix: str
    purchase_prefix: str

    model_config = {"from_attributes": True}


class FinancialYearCreate(BaseModel):
    label: str
    start_date: date
    end_date: date


class FinancialYearResponse(BaseModel):
    id: uuid.UUID
    label: str
    start_date: date
    end_date: date
    is_active: bool

    model_config = {"from_attributes": True}

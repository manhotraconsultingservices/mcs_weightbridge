import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel


class AgentCreate(BaseModel):
    name: str
    phone: str | None = None
    gstin: str | None = None
    pan: str | None = None
    address: str | None = None
    commission_type: str = "pct_of_taxable"   # per_mt | pct_of_taxable | pct_of_grand_total | flat_per_invoice
    commission_rate: Decimal = Decimal("0")
    notes: str | None = None
    is_active: bool | None = None


class AgentResponse(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None
    gstin: str | None
    pan: str | None
    address: str | None
    commission_type: str
    commission_rate: Decimal
    notes: str | None
    is_active: bool
    model_config = {"from_attributes": True}


class AgentPayoutCreate(BaseModel):
    amount: Decimal
    paid_on: date
    payment_mode: str | None = None
    reference_no: str | None = None
    notes: str | None = None


class AgentPayoutResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    amount: Decimal
    paid_on: date
    payment_mode: str | None
    reference_no: str | None
    notes: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class AgentReportInvoice(BaseModel):
    invoice_id: uuid.UUID
    invoice_no: str | None
    invoice_date: date
    invoice_type: str
    party_name: str | None
    net_weight_mt: Decimal
    taxable_amount: Decimal
    grand_total: Decimal
    commission_amount: Decimal


class AgentReport(BaseModel):
    agent: AgentResponse
    earned: Decimal
    paid: Decimal
    due: Decimal
    invoice_count: int
    total_sale_value: Decimal
    invoices: list[AgentReportInvoice]
    payouts: list[AgentPayoutResponse]


class AgentSummaryRow(BaseModel):
    agent_id: uuid.UUID
    name: str
    commission_type: str
    commission_rate: Decimal
    invoice_count: int
    earned: Decimal
    paid: Decimal
    due: Decimal

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from typing import Optional
from pydantic import BaseModel, ConfigDict


class InvoiceAllocation(BaseModel):
    invoice_id: UUID
    amount: Decimal


# ── Receipt ──────────────────────────────────────────────────────────────── #

class PaymentReceiptCreate(BaseModel):
    receipt_date: date
    party_id: UUID
    amount: Decimal
    payment_mode: str  # cash, cheque, upi, bank_transfer
    reference_no: Optional[str] = None
    bank_name: Optional[str] = None
    notes: Optional[str] = None
    allocations: list[InvoiceAllocation] = []


class PaymentReceiptResponse(BaseModel):
    id: UUID
    receipt_no: str
    receipt_date: date
    party_id: UUID
    party_name: str
    amount: Decimal
    payment_mode: str
    reference_no: Optional[str] = None
    bank_name: Optional[str] = None
    notes: Optional[str] = None
    tally_synced: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PaymentReceiptListResponse(BaseModel):
    items: list[PaymentReceiptResponse]
    total: int
    page: int
    page_size: int


# ── Voucher ───────────────────────────────────────────────────────────────── #

class PaymentVoucherCreate(BaseModel):
    voucher_date: date
    party_id: UUID
    amount: Decimal
    payment_mode: str
    reference_no: Optional[str] = None
    bank_name: Optional[str] = None
    notes: Optional[str] = None
    allocations: list[InvoiceAllocation] = []


class PaymentVoucherResponse(BaseModel):
    id: UUID
    voucher_no: str
    voucher_date: date
    party_id: UUID
    party_name: str
    amount: Decimal
    payment_mode: str
    reference_no: Optional[str] = None
    bank_name: Optional[str] = None
    notes: Optional[str] = None
    tally_synced: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PaymentVoucherListResponse(BaseModel):
    items: list[PaymentVoucherResponse]
    total: int
    page: int
    page_size: int


# ── Ledger ────────────────────────────────────────────────────────────────── #

class LedgerEntrySchema(BaseModel):
    entry_date: date
    voucher_type: str
    voucher_no: str
    narration: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


class PartyLedgerResponse(BaseModel):
    party_id: UUID
    party_name: str
    opening_balance: Decimal
    entries: list[LedgerEntrySchema]
    closing_balance: Decimal
    total_debit: Decimal
    total_credit: Decimal


# ── Outstanding ───────────────────────────────────────────────────────────── #

class OutstandingInvoice(BaseModel):
    id: UUID
    invoice_no: str
    invoice_date: date
    due_date: Optional[date] = None
    invoice_type: str
    party_id: UUID
    party_name: str
    grand_total: Decimal
    amount_paid: Decimal
    balance: Decimal
    days_overdue: int
    age_bucket: str  # current, 1-30, 31-60, 61-90, 90+


class OutstandingResponse(BaseModel):
    items: list[OutstandingInvoice]
    total_outstanding: Decimal
    total_overdue: Decimal

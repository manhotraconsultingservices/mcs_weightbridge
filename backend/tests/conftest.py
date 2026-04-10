"""
Pytest configuration and fixtures for Tally integration tests.

All test data is built with types.SimpleNamespace so no database is needed.
The MockTallyServer fixture is session-scoped — started once and shared across
the entire test session for speed. Individual tests reset state via the
autouse `reset_mock_tally` fixture.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.mock_tally_server import MockTallyServer

# ─────────────────────────────────────────────────────────────────────────────
# Server fixture
# ─────────────────────────────────────────────────────────────────────────────

MOCK_TALLY_PORT = 9099


@pytest.fixture(scope="session")
def mock_tally_server() -> MockTallyServer:
    """Start MockTallyServer once for the entire test session."""
    server = MockTallyServer(port=MOCK_TALLY_PORT)
    server.start()
    yield server
    server.stop()


@pytest.fixture(autouse=True)
def reset_mock_tally(mock_tally_server: MockTallyServer):
    """Reset mock server state before each test."""
    mock_tally_server.reset()
    yield
    # post-test cleanup (no-op — reset is pre-test)


# ─────────────────────────────────────────────────────────────────────────────
# Sample data factories
# ─────────────────────────────────────────────────────────────────────────────

def make_company(
    name: str = "Test Crushers Pvt Ltd",
    gstin: str = "27AAACT1234A1Z5",
    tally_company_name: str = "Test Crushers",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        gstin=gstin,
        tally_company_name=tally_company_name,
        billing_state="Maharashtra",
        billing_state_code="27",
    )


def make_party(
    name: str = "Sharma Stone Works",
    party_type: str = "customer",
    gstin: str = "27ABCDE1234F1Z5",
    billing_state: str = "Maharashtra",
    billing_state_code: str = "27",
    billing_address: str = "Plot 12, Industrial Area",
    billing_city: str = "Pune",
    billing_pincode: str = "411001",
    phone: str = "9876543210",
    email: str = "sharma@example.com",
    payment_terms_days: int = 30,
    tally_ledger_name: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        party_type=party_type,
        gstin=gstin,
        billing_state=billing_state,
        billing_state_code=billing_state_code,
        billing_address=billing_address,
        billing_city=billing_city,
        billing_pincode=billing_pincode,
        phone=phone,
        email=email,
        payment_terms_days=payment_terms_days,
        tally_ledger_name=tally_ledger_name,
        tally_synced=False,
        tally_sync_at=None,
    )


def make_invoice_item(
    description: str = "Crushed Stone 20mm",
    hsn_code: str = "25171010",
    quantity: Decimal = Decimal("10.000"),
    unit: str = "MT",
    rate: Decimal = Decimal("800.00"),
    amount: Decimal = Decimal("8000.00"),
    gst_rate: Decimal = Decimal("5.00"),
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        description=description,
        hsn_code=hsn_code,
        quantity=quantity,
        unit=unit,
        rate=rate,
        amount=amount,
        gst_rate=gst_rate,
    )


def make_sales_invoice(
    invoice_no: str = "SI/25-26/0001",
    invoice_date: date = date(2025, 5, 10),
    party: SimpleNamespace | None = None,
    items: list | None = None,
    taxable_amount: Decimal = Decimal("8000.00"),
    cgst_amount: Decimal = Decimal("200.00"),
    sgst_amount: Decimal = Decimal("200.00"),
    igst_amount: Decimal = Decimal("0.00"),
    discount_amount: Decimal = Decimal("0.00"),
    freight: Decimal = Decimal("0.00"),
    tcs_amount: Decimal = Decimal("0.00"),
    round_off: Decimal = Decimal("0.00"),
    grand_total: Decimal = Decimal("8400.00"),
    invoice_type: str = "sale",
    vehicle_no: str | None = "MH12AB1234",
    token_no: int | None = 42,
    net_weight: Decimal | None = Decimal("10000"),
) -> SimpleNamespace:
    if items is None:
        items = [make_invoice_item(
            amount=taxable_amount,
            gst_rate=Decimal("5.00") if (cgst_amount + sgst_amount + igst_amount) > 0 else Decimal("0"),
        )]
    return SimpleNamespace(
        id=uuid.uuid4(),
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        invoice_type=invoice_type,
        party_id=party.id if party else uuid.uuid4(),
        items=items,
        taxable_amount=taxable_amount,
        discount_amount=discount_amount,
        freight=freight,
        cgst_amount=cgst_amount,
        sgst_amount=sgst_amount,
        igst_amount=igst_amount,
        tcs_amount=tcs_amount,
        round_off=round_off,
        grand_total=grand_total,
        customer_name=party.name if party else "Walk-in Customer",
        vehicle_no=vehicle_no,
        token_no=token_no,
        net_weight=net_weight,
        due_date=None,
        status="final",
        tally_synced=False,
        tally_sync_at=None,
    )


def make_purchase_invoice(
    invoice_no: str = "PI/25-26/0001",
    invoice_date: date = date(2025, 5, 12),
    party: SimpleNamespace | None = None,
    items: list | None = None,
    taxable_amount: Decimal = Decimal("5000.00"),
    cgst_amount: Decimal = Decimal("125.00"),
    sgst_amount: Decimal = Decimal("125.00"),
    igst_amount: Decimal = Decimal("0.00"),
    discount_amount: Decimal = Decimal("0.00"),
    freight: Decimal = Decimal("0.00"),
    tcs_amount: Decimal = Decimal("0.00"),
    round_off: Decimal = Decimal("0.00"),
    grand_total: Decimal = Decimal("5250.00"),
) -> SimpleNamespace:
    if items is None:
        items = [make_invoice_item(
            quantity=Decimal("5.000"),
            rate=Decimal("1000.00"),
            amount=taxable_amount,
        )]
    return SimpleNamespace(
        id=uuid.uuid4(),
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        invoice_type="purchase",
        party_id=party.id if party else uuid.uuid4(),
        items=items,
        taxable_amount=taxable_amount,
        discount_amount=discount_amount,
        freight=freight,
        cgst_amount=cgst_amount,
        sgst_amount=sgst_amount,
        igst_amount=igst_amount,
        tcs_amount=tcs_amount,
        round_off=round_off,
        grand_total=grand_total,
        customer_name=party.name if party else "Walk-in Supplier",
        vehicle_no=None,
        token_no=None,
        net_weight=None,
        due_date=None,
        status="final",
        tally_synced=False,
        tally_sync_at=None,
    )


def make_quotation(
    quotation_no: str = "QT/25-26/0001",
    quotation_date: date = date(2025, 5, 15),
    party: SimpleNamespace | None = None,
    items: list | None = None,
    grand_total: Decimal = Decimal("8400.00"),
    cgst_amount: Decimal = Decimal("200.00"),
    sgst_amount: Decimal = Decimal("200.00"),
    igst_amount: Decimal = Decimal("0.00"),
    taxable_amount: Decimal = Decimal("8000.00"),
    discount_amount: Decimal = Decimal("0.00"),
    round_off: Decimal = Decimal("0.00"),
) -> SimpleNamespace:
    if items is None:
        items = [make_invoice_item(amount=taxable_amount)]
    return SimpleNamespace(
        id=uuid.uuid4(),
        quotation_no=quotation_no,
        quotation_date=quotation_date,
        party_id=party.id if party else uuid.uuid4(),
        items=items,
        grand_total=grand_total,
        taxable_amount=taxable_amount,
        cgst_amount=cgst_amount,
        sgst_amount=sgst_amount,
        igst_amount=igst_amount,
        discount_amount=discount_amount,
        round_off=round_off,
        freight=Decimal("0.00"),
        tcs_amount=Decimal("0.00"),
        status="accepted",
        tally_synced=False,
        tally_sync_at=None,
    )


def make_po_item(
    item_name: str = "Engine Oil",
    unit: str = "Ltrs",
    quantity_ordered: Decimal = Decimal("20.000"),
    unit_price: Decimal = Decimal("350.00"),
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        item_name=item_name,
        unit=unit,
        quantity_ordered=quantity_ordered,
        unit_price=unit_price,
    )


def make_purchase_order(
    po_no: str = "PO/25-26/0001",
    supplier_name: str = "Lubes & Spares Co.",
    items: list | None = None,
    status: str = "approved",
) -> SimpleNamespace:
    if items is None:
        items = [make_po_item()]
    return SimpleNamespace(
        id=uuid.uuid4(),
        po_no=po_no,
        supplier_name=supplier_name,
        items=items,
        status=status,
        created_at=date(2025, 5, 10),
        tally_synced=False,
        tally_sync_at=None,
    )

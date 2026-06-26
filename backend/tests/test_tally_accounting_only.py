"""Accounting-only / no-GST Tally export mode (legacy Tally + non-GST demos).

In this mode a Sales/Purchase invoice is built as a plain accounting voucher:
  - OBJVIEW="Accounting Voucher View" (never "Invoice Voucher View")
  - party ledger + Sales/Purchase ledger only — NO stock item / inventory
  - NO GST ledger lines, NO GST tags (PARTYGSTIN / PLACEOFSUPPLY)
  - NO invoice-view hints (BASICBASEPARTYNAME / PERSISTEDVIEW / CREDITPERIOD)
    that make legacy Tally open the voucher interactively
  - still balances to zero
This is the format that imports cleanly on Tally 9; full mode is unchanged.
"""
from decimal import Decimal
from datetime import date
from xml.etree import ElementTree as ET

from app.integrations.tally.xml_builder import build_sales_xml, build_purchase_xml, TallyLedgerMap
from tests.conftest import make_company, make_party, make_invoice_item, make_sales_invoice

LED = TallyLedgerMap(sales="Sales", purchase="Purchase")


def _sale(**kw):
    company, party = make_company(), make_party(payment_terms_days=30)
    inv = make_sales_invoice(
        invoice_no="INV/1", invoice_date=date(2026, 6, 26), party=party,
        items=[make_invoice_item(amount=Decimal("7000.00"), gst_rate=Decimal("0"))],
        taxable_amount=Decimal("7000.00"), cgst_amount=Decimal("0"), sgst_amount=Decimal("0"),
        igst_amount=Decimal("0"), grand_total=Decimal("7000.00"), round_off=Decimal("0"),
        **kw,
    )
    return ET.fromstring(build_sales_xml(inv, company, party, LED, accounting_only=True)).find(".//VOUCHER")


def _balance(v):
    s = sum(Decimal(e.findtext("AMOUNT", "0")) for e in v.findall("ALLLEDGERENTRIES.LIST"))
    s += sum(Decimal(e.findtext("AMOUNT", "0")) for e in v.findall("INVENTORYENTRIES.LIST"))
    return s


def test_accounting_only_is_legacy_safe():
    v = _sale()
    assert v.get("OBJVIEW") == "Accounting Voucher View"
    assert v.find("PERSISTEDVIEW") is None
    assert v.find("BASICBASEPARTYNAME") is None
    assert v.find("PLACEOFSUPPLY") is None
    assert v.findall("INVENTORYENTRIES.LIST") == []          # no stock
    ledgers = [e.findtext("LEDGERNAME") for e in v.findall("ALLLEDGERENTRIES.LIST")]
    assert ledgers == [make_party().name, "Sales"]           # party + income ledger only
    assert "CGST" not in ledgers and "SGST" not in ledgers   # no GST
    # bill ref present but WITHOUT a credit period (legacy hangs on it)
    ba = v.find(".//BILLALLOCATIONS.LIST")
    assert ba is not None and ba.find("CREDITPERIOD") is None
    assert _balance(v) == Decimal("0.00")


def test_accounting_only_purchase_balances_and_posts_to_purchase():
    company = make_company()
    supp = make_party(name="Quarry Co", party_type="supplier")
    pinv = make_sales_invoice(
        invoice_no="PUR/1", invoice_date=date(2026, 6, 26), party=supp, invoice_type="purchase",
        items=[make_invoice_item(amount=Decimal("4000.00"), gst_rate=Decimal("0"))],
        taxable_amount=Decimal("4000.00"), cgst_amount=Decimal("0"), sgst_amount=Decimal("0"),
        igst_amount=Decimal("0"), grand_total=Decimal("4000.00"), round_off=Decimal("0"),
    )
    v = ET.fromstring(build_purchase_xml(pinv, company, supp, LED, accounting_only=True)).find(".//VOUCHER")
    assert v.get("OBJVIEW") == "Accounting Voucher View"
    assert v.findall("INVENTORYENTRIES.LIST") == []
    ledgers = [e.findtext("LEDGERNAME") for e in v.findall("ALLLEDGERENTRIES.LIST")]
    assert ledgers == ["Quarry Co", "Purchase"]
    assert _balance(v) == Decimal("0.00")


def test_full_mode_unchanged():
    """accounting_only defaults False → full GST invoice voucher (inventory + Invoice View)."""
    company, party = make_company(), make_party()
    inv = make_sales_invoice(
        invoice_no="INV/2", invoice_date=date(2026, 6, 26), party=party,
        items=[make_invoice_item(amount=Decimal("8000.00"), gst_rate=Decimal("5.00"))],
        taxable_amount=Decimal("8000.00"), cgst_amount=Decimal("200.00"), sgst_amount=Decimal("200.00"),
        igst_amount=Decimal("0"), grand_total=Decimal("8400.00"), round_off=Decimal("0"),
    )
    v = ET.fromstring(build_sales_xml(inv, company, party, LED)).find(".//VOUCHER")
    assert v.get("OBJVIEW") == "Invoice Voucher View"
    assert len(v.findall("INVENTORYENTRIES.LIST")) == 1
    assert v.find("PERSISTEDVIEW") is not None

"""Quantity must reach Tally, and Tally's stock must be able to go UP as well as down.

A sale takes stock out of Tally. A stone crusher's finished goods are MANUFACTURED,
not bought — so without a production inflow Tally's inventory falls forever and goes
permanently negative. These tests pin both directions, plus the two site-specific
values that reject an entire voucher when they are wrong: the godown, and a batch
name on an item that has no batching.
"""
from decimal import Decimal
from datetime import date
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from app.integrations.tally.xml_builder import (
    build_sales_xml, build_stock_journal_xml, build_stock_item_xml, TallyLedgerMap,
)
from tests.conftest import make_company, make_party, make_sales_invoice, make_invoice_item

LED = TallyLedgerMap(sales="Sales", purchase="Purchase", cgst="CGST", sgst="SGST", igst="IGST")


def _inv(qty="10.000", unit="MT"):
    return make_sales_invoice(items=[make_invoice_item(
        description="M Sand", quantity=Decimal(qty), unit=unit,
        rate=Decimal("500.00"), amount=Decimal("5000.00"), gst_rate=Decimal("5.00"))],
        taxable_amount=Decimal("5000.00"), cgst_amount=Decimal("125.00"),
        sgst_amount=Decimal("125.00"), igst_amount=Decimal("0.00"),
        grand_total=Decimal("5250.00"), round_off=Decimal("0.00"))


def _cycle():
    return SimpleNamespace(id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                           cycle_date=date(2026, 9, 9), cycle_no=7)


def test_a_sale_carries_the_quantity_that_tally_will_deduct():
    v = ET.fromstring(build_sales_xml(_inv(), make_company(), make_party(), LED)).find(".//VOUCHER")
    line = v.find("INVENTORYENTRIES.LIST")
    assert line is not None, "no inventory line — Tally would deduct nothing"
    assert line.findtext("ACTUALQTY") == "10.000 MT"
    assert line.findtext("BILLEDQTY") == "10.000 MT"


def test_accounting_only_sends_no_quantity_at_all():
    """The mode every live tenant runs today — worth stating plainly."""
    xml = build_sales_xml(_inv(), make_company(), make_party(), LED, accounting_only=True)
    assert "<INVENTORYENTRIES.LIST>" not in xml
    assert "ACTUALQTY" not in xml          # nothing for Tally to deduct


def test_the_godown_is_configurable_and_defaults_to_tallys_own():
    """An unknown godown rejects the WHOLE voucher, so it cannot be hardcoded."""
    named = build_sales_xml(_inv(), make_company(), make_party(), LED, godown="Plant Yard")
    assert ET.fromstring(named).find(".//GODOWNNAME").text == "Plant Yard"
    default = build_sales_xml(_inv(), make_company(), make_party(), LED)
    assert ET.fromstring(default).find(".//GODOWNNAME").text == "Main Location"


def test_no_batch_name_unless_the_tenant_has_batching():
    """Tally refuses a batch on an item that is not batched — so it is opt-in."""
    off = build_sales_xml(_inv(), make_company(), make_party(), LED)
    assert "<BATCHNAME>" not in off
    on = build_sales_xml(_inv(), make_company(), make_party(), LED, batch_name="Primary Batch")
    assert "<BATCHNAME>Primary Batch</BATCHNAME>" in on


def test_production_puts_stock_back_IN_via_a_stock_journal():
    """The inflow that stops Tally going permanently negative."""
    xml = build_stock_journal_xml(
        _cycle(), make_company(),
        consumed=[{"name": "ROM", "unit": "MT", "qty": Decimal("100")}],
        produced=[{"name": "M Sand", "unit": "MT", "qty": Decimal("40")},
                  {"name": "Gitti 20mm", "unit": "MT", "qty": Decimal("45")}],
        godown="Plant Yard")
    v = ET.fromstring(xml).find(".//VOUCHER")
    assert v.get("VCHTYPE") == "Stock Journal"
    out = [(e.findtext("STOCKITEMNAME"), e.findtext("ACTUALQTY")) for e in v.findall("INVENTORYENTRIESOUT.LIST")]
    inn = [(e.findtext("STOCKITEMNAME"), e.findtext("ACTUALQTY")) for e in v.findall("INVENTORYENTRIESIN.LIST")]
    assert out == [("ROM", "100.000 MT")]                    # raw material consumed
    assert inn == [("M Sand", "40.000 MT"), ("Gitti 20mm", "45.000 MT")]   # goods produced
    assert v.findtext("GUID") == _cycle().id                 # re-sending ALTERs, never duplicates


def test_a_zero_output_product_is_not_sent():
    """A cycle row left blank must not post a zero movement into Tally."""
    xml = build_stock_journal_xml(
        _cycle(), make_company(), consumed=[],
        produced=[{"name": "M Sand", "unit": "MT", "qty": Decimal("0")}])
    assert "INVENTORYENTRIESIN.LIST" not in xml


def test_opening_stock_is_opt_in_so_a_re_sync_cannot_reset_it():
    """Re-syncing an item must never silently reset a balance Tally has moved on."""
    product = SimpleNamespace(name="M Sand", unit="MT", hsn_code="2517",
                              gst_rate=Decimal("5.00"), bulk_density=Decimal("1.5"))
    assert "<OPENINGBALANCE>" not in build_stock_item_xml(product, make_company())
    seeded = build_stock_item_xml(product, make_company(), opening_qty=Decimal("132.5"))
    assert "<OPENINGBALANCE>132.500 MT</OPENINGBALANCE>" in seeded

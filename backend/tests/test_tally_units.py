"""Units: a line billed in CBM must reach Tally as a quantity its Stock Item knows.

Since per-unit pricing shipped, the same product is billed under several unit
labels - on sss 155 of 208 final sale lines are in a unit that is NOT the
product's base unit (CBM against MT items). Tally rejects a quantity in a unit
the item does not carry, so those vouchers failed in full (inventory) mode.

An item gets ONE alternate unit (all Tally allows), and every billed unit of that
dimension is converted exactly onto the base or the alternate. The amount is
never touched - only qty and rate move, inversely - so the voucher still foots.
"""
from decimal import Decimal
from xml.etree import ElementTree as ET

from app.integrations.tally import units as tu
from app.integrations.tally.xml_builder import (
    build_sales_xml, build_stock_item_xml, build_customer_master_xml,
    gl_ledger_specs, TallyLedgerMap,
)
from tests.conftest import make_company, make_party, make_invoice_item, make_sales_invoice

LED = TallyLedgerMap(sales="Sales", purchase="Purchase", cgst="CGST", sgst="SGST", igst="IGST")
# 42.5 kg/CFT is the documented aggregate density; 1 CUM = 35.3147 CFT
STONE = tu.line_product("MT", Decimal("42.5"))


def _item(v):
    return v.find("INVENTORYENTRIES.LIST")


def _voucher(xml):
    return ET.fromstring(xml).find(".//VOUCHER")


# -- the master --------------------------------------------------------------

def test_weight_item_carries_the_volume_unit_as_its_alternate():
    xml = build_stock_item_xml(
        tu.line_product("MT", Decimal("42.5")), make_company(), volume_unit="CUM")
    item = ET.fromstring(xml).find(".//STOCKITEM")
    assert item.findtext("BASEUNITS") == "MT"
    assert item.findtext("ADDITIONALUNITS") == "CUM"
    # 1 CUM = 35.3147 CFT x 42.5 kg = 1500.87 kg = 1.5009 MT
    assert item.findtext("CONVERSION") == "1.5009"
    assert item.findtext("DENOMINATOR") == "1"


def test_volume_item_carries_MT_as_its_alternate():
    item = ET.fromstring(build_stock_item_xml(
        tu.line_product("CFT", Decimal("42.5")), make_company())).find(".//STOCKITEM")
    assert item.findtext("BASEUNITS") == "CFT"
    assert item.findtext("ADDITIONALUNITS") == "MT"
    assert item.findtext("CONVERSION") == "23.5294"      # 1 MT = 1000/42.5 CFT


def test_no_density_means_no_alternate_unit():
    """Without a density there is no honest bridge between weight and volume,
    so the item is left exactly as it was before this change."""
    item = ET.fromstring(build_stock_item_xml(
        tu.line_product("MT", None), make_company())).find(".//STOCKITEM")
    assert item.findtext("BASEUNITS") == "MT"
    assert item.find("ADDITIONALUNITS") is None
    assert item.find("CONVERSION") is None


def test_a_countable_item_gets_no_alternate():
    item = ET.fromstring(build_stock_item_xml(
        tu.line_product("NOS", Decimal("42.5")), make_company())).find(".//STOCKITEM")
    assert item.find("ADDITIONALUNITS") is None


def test_the_tenants_volume_unit_is_honoured():
    for vu, conv in (("CUM", "1.5009"), ("CFT", "0.0425"), ("BRASS", "4.25")):
        item = ET.fromstring(build_stock_item_xml(
            STONE, make_company(), volume_unit=vu)).find(".//STOCKITEM")
        assert item.findtext("ADDITIONALUNITS") == vu
        assert item.findtext("CONVERSION") == conv


# -- the line conversion -----------------------------------------------------

def test_same_dimension_converts_exactly_to_the_base():
    """CBM and CUM are the same unit under two names; BRASS is 100 CFT."""
    q, r, u, note = tu.convert_line(Decimal("10"), Decimal("1500"), "CBM", STONE, "CUM")
    assert (u, note) == ("CUM", None) and q == Decimal("10.000")
    q, r, u, _ = tu.convert_line(Decimal("5"), Decimal("4000"), "BRASS", STONE, "CUM")
    assert u == "CUM" and q == Decimal("14.158")        # 500 CFT / 35.3147
    q, r, u, _ = tu.convert_line(Decimal("45"), Decimal("100"), "MT",
                                 tu.line_product("QUINTAL", Decimal("42.5")), "CUM")
    assert (u, q) == ("QUINTAL", Decimal("450.000"))     # megna's actual shape


def test_the_amount_is_never_changed_by_a_conversion():
    """Only qty and rate move, inversely - the money must be untouched."""
    for qty, rate, unit in ((Decimal("10"), Decimal("1500"), "CBM"),
                            (Decimal("5"), Decimal("4000"), "BRASS"),
                            (Decimal("353.147"), Decimal("42"), "CFT")):
        amount = qty * rate
        q, r, _, _ = tu.convert_line(qty, rate, unit, STONE, "CUM", amount=amount)
        # within half a paisa of the amount the books and the GST return carry
        assert abs(q * r - amount) <= Decimal("0.005")

    # ...and without the amount the rate is merely scaled, which is why the
    # builder always passes it: a rounded quantity drifts against the money.
    q, r, _, _ = tu.convert_line(Decimal("5"), Decimal("4000"), "BRASS", STONE, "CUM")
    assert abs(q * r - Decimal("20000")) > Decimal("0.1")


def test_a_line_in_the_base_unit_is_untouched():
    q, r, u, note = tu.convert_line(Decimal("24"), Decimal("550"), "MT", STONE, "CUM")
    assert (q, r, u, note) == (Decimal("24"), Decimal("550"), "MT", None)


def test_a_line_that_cannot_be_converted_says_so_instead_of_guessing():
    q, r, u, note = tu.convert_line(Decimal("10"), Decimal("1500"), "CBM",
                                    tu.line_product("MT", None), "CUM")
    assert (q, u) == (Decimal("10"), "CBM")             # passed through, not invented
    assert note and "bulk density" in note

    _, _, u2, note2 = tu.convert_line(Decimal("3"), Decimal("90"), "L", STONE, "CUM")
    assert u2 == "L" and note2 and "no known dimension" in note2


# -- end to end on a real voucher --------------------------------------------

def test_a_CBM_line_reaches_the_voucher_in_the_items_alternate_unit():
    inv = make_sales_invoice(
        items=[make_invoice_item(description="Gitti 20mm", quantity=Decimal("10.000"),
                                 unit="CBM", rate=Decimal("1500.00"),
                                 amount=Decimal("15000.00"), gst_rate=Decimal("5.00"))],
        taxable_amount=Decimal("15000.00"), cgst_amount=Decimal("375.00"),
        sgst_amount=Decimal("375.00"), grand_total=Decimal("15750.00"))
    inv.items[0]._product = STONE                        # what routers.tally attaches
    inv.items[0]._product_name = "Gitti 20mm"
    e = _item(_voucher(build_sales_xml(inv, make_company(), make_party(), LED,
                                       volume_unit="CUM")))
    assert e.findtext("ACTUALQTY") == "10.000 CUM"       # not "10.000 CBM"
    assert e.findtext("BILLEDQTY") == "10.000 CUM"
    assert e.findtext("RATE") == "1500.00/CUM"
    assert Decimal(e.findtext("AMOUNT")) == Decimal("-15000.00")   # unchanged


def test_a_line_with_no_product_attached_behaves_exactly_as_before():
    """Back-compat: every existing caller that does not attach _product."""
    inv = make_sales_invoice(
        items=[make_invoice_item(description="M-Sand", quantity=Decimal("4.000"),
                                 unit="MT", rate=Decimal("500.00"),
                                 amount=Decimal("2000.00"))],
        taxable_amount=Decimal("2000.00"), grand_total=Decimal("2100.00"))
    e = _item(_voucher(build_sales_xml(inv, make_company(), make_party(), LED)))
    assert e.findtext("ACTUALQTY") == "4.000 MT"


# -- Findings 3 & 4: the ledgers a voucher references must exist -------------

def test_the_walkin_ledger_is_created_and_matches_the_voucher_party():
    names = [n for (n, _, _) in gl_ledger_specs(LED)]
    assert "Walk-in Customer" in names
    inv = make_sales_invoice()
    inv.party_id = None
    inv.customer_name = None
    v = _voucher(build_sales_xml(inv, make_company(), None, LED))
    party = [e.findtext("LEDGERNAME") for e in v.findall("ALLLEDGERENTRIES.LIST")
             if e.findtext("ISPARTYLEDGER") == "Yes"][0]
    assert party in names                                # the ledger now exists


def test_party_ledgers_track_bills_so_notes_can_settle_against_an_invoice():
    led = ET.fromstring(build_customer_master_xml(
        make_party(), make_company())).find(".//LEDGER")
    assert led.findtext("ISBILLWISEON") == "Yes"

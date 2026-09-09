"""Which Tally company a document is filed under.

Tally rejects an ENTIRE import with "Could not set 'SVCurrentCompany'" when the
name in the XML is not a company it has open — before it reads a single voucher.
That failure took a live site down for a day, and it was invisible because the
name never came from where the operator set it: `tally_company_name` is a column
on TallyConfig, but every builder read it off the Company object, which has no
such attribute, so it silently fell back to the app's own company name.

Two rules are pinned here: the configured name is used verbatim, and a blank one
omits SVCURRENTCOMPANY entirely (Tally then uses whichever company is open)
rather than guessing with a name that is almost never right.
"""
from types import SimpleNamespace
from decimal import Decimal
from xml.etree import ElementTree as ET

from app.integrations.tally.xml_builder import (
    build_sales_xml, build_purchase_xml, build_credit_note_xml,
    build_stock_item_xml, build_unit_xml, build_ledger_master_xml,
    build_customer_master_xml, build_supplier_master_xml, TallyLedgerMap,
)
from tests.conftest import make_company, make_party, make_sales_invoice

LED = TallyLedgerMap(sales="Sales", purchase="Purchase", cgst="CGST", sgst="SGST", igst="IGST")


def _company(tally_name):
    """A company as `routers.tally._get_company` hands it to the builders."""
    co = make_company()
    co.name = "Acme Stone Works Pvt Ltd"      # the APP's name — never a fallback
    co.tally_company_name = tally_name
    return co


def _current(xml):
    root = ET.fromstring(xml)
    return root.findtext(".//SVCURRENTCOMPANY")


def _has_empty_static(xml):
    root = ET.fromstring(xml)
    return any(len(sv) == 0 for sv in root.iter("STATICVARIABLES"))


def test_configured_name_is_sent_verbatim():
    inv = make_sales_invoice()
    xml = build_sales_xml(inv, _company("Manhotra Consulting Services"), make_party(), LED)
    assert _current(xml) == "Manhotra Consulting Services"


def test_blank_omits_the_element_so_tally_uses_the_open_company():
    inv = make_sales_invoice()
    for blank in (None, "", "   "):
        xml = build_sales_xml(inv, _company(blank), make_party(), LED)
        assert _current(xml) is None, f"{blank!r} should emit no SVCURRENTCOMPANY"
        # ...and no hollow <STATICVARIABLES/> left behind
        assert not _has_empty_static(xml)


def test_never_falls_back_to_the_apps_own_company_name():
    """The actual bug: the app's name reached Tally and Tally refused it."""
    inv = make_sales_invoice()
    xml = build_sales_xml(inv, _company(None), make_party(), LED)
    assert "Acme Stone Works Pvt Ltd" not in xml


def test_surrounding_whitespace_is_trimmed():
    """A trailing space is invisible on screen and rejects every voucher."""
    inv = make_sales_invoice()
    xml = build_sales_xml(inv, _company("  Manhotra Consulting  "), make_party(), LED)
    assert _current(xml) == "Manhotra Consulting"


def test_rule_holds_for_every_document_type():
    """Masters fail the same way — a rejected ledger import blocks the vouchers."""
    co_set, co_blank = _company("Real Tally Co"), _company(None)
    party, inv = make_party(), make_sales_invoice()
    product = SimpleNamespace(name="M-Sand", unit="MT", hsn_code="2517",
                              gst_rate=Decimal("5.00"), bulk_density=None)
    builders = {
        "sales": lambda c: build_sales_xml(inv, c, party, LED),
        "purchase": lambda c: build_purchase_xml(inv, c, party, LED),
        "credit_note": lambda c: build_credit_note_xml(inv, c, party, LED,
                                                       reference_invoice_no="INV/1"),
        "customer_master": lambda c: build_customer_master_xml(party, c),
        "supplier_master": lambda c: build_supplier_master_xml(party, c),
        "stock_item": lambda c: build_stock_item_xml(product, c),
        "unit": lambda c: build_unit_xml("MT", c),
        "ledger": lambda c: build_ledger_master_xml("Sales", "Sales Accounts", c),
    }
    for label, build in builders.items():
        assert _current(build(co_set)) == "Real Tally Co", f"{label} lost the name"
        assert _current(build(co_blank)) is None, f"{label} still names a company"


def test_a_merged_import_keeps_the_company_name():
    """A merge REBUILDS the envelope, so it must re-state the company.

    `/sync/ledgers` and `/sync/product` bundle several masters into one import.
    The merge discards the source envelopes, so before this the configured company
    was silently dropped from exactly those two — masters landed in whichever
    company was open while vouchers went to the configured one.
    """
    from app.routers.tally import _merge_master_xmls, _merge_voucher_xmls

    co = _company("Real Tally Co")
    masters = [build_unit_xml("MT", co), build_ledger_master_xml("Sales", "Sales Accounts", co)]
    vouchers = [build_sales_xml(make_sales_invoice(), co, make_party(), LED)]

    for merged in (_merge_master_xmls(masters, "Real Tally Co"),
                   _merge_voucher_xmls(vouchers, "Real Tally Co")):
        root = ET.fromstring(merged)                      # must still be valid XML
        names = [e.text for e in root.iter("SVCURRENTCOMPANY")]
        assert names == ["Real Tally Co"], names          # exactly one, not per-message

    # ...and blank still means "whichever company is open"
    for merged in (_merge_master_xmls(masters), _merge_voucher_xmls(vouchers)):
        assert _current(merged) is None
        assert not _has_empty_static(merged)


def test_a_company_name_with_an_ampersand_survives_the_merge():
    """The merge builds XML by string concatenation — an unescaped & breaks it."""
    from app.routers.tally import _merge_master_xmls
    co = _company("Ram & Sons Traders")
    merged = _merge_master_xmls([build_unit_xml("MT", co)], "Ram & Sons Traders")
    assert ET.fromstring(merged).findtext(".//SVCURRENTCOMPANY") == "Ram & Sons Traders"

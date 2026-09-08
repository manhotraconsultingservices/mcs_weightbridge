"""A revised invoice must REPLACE its voucher in Tally, not sit beside it.

A revision is a new invoice row in the app, but the same commercial document.
Before this rule every version got its own GUID, so Tally CREATED a second
voucher for the revision while the original stayed — revenue and GST liability
double-counted in Tally even though the app's own books excluded the superseded
row. Keying the GUID on the ROOT of the revision chain makes Tally ALTER the
voucher in place (with "Overwrite voucher when same GUID exists = Yes").

Style matches the existing suite: SimpleNamespace fixtures, no database.
"""
import uuid
from decimal import Decimal
from datetime import date
from xml.etree import ElementTree as ET

from app.integrations.tally.xml_builder import (
    build_sales_xml, build_purchase_xml, build_credit_note_xml, voucher_guid,
    TallyLedgerMap,
)
from tests.conftest import (
    make_company, make_party, make_invoice_item, make_sales_invoice, make_purchase_invoice,
)

LED = TallyLedgerMap(sales="Sales", purchase="Purchase", cgst="CGST", sgst="SGST", igst="IGST")


def _voucher(xml):
    return ET.fromstring(xml).find(".//VOUCHER")


def _revision_of(root, revision_no, invoice_no, **overrides):
    """Build the row `create_revision` + finalise would produce: a NEW id, a
    /RvN number, and original_invoice_id pointing at the ROOT (never the parent)."""
    kw = dict(invoice_no=invoice_no, invoice_date=root.invoice_date,
              invoice_type=root.invoice_type)
    kw.update(overrides)
    maker = make_purchase_invoice if root.invoice_type == "purchase" else make_sales_invoice
    if root.invoice_type == "purchase":
        kw.pop("invoice_type")
    rev = maker(**kw)
    rev.revision_no = revision_no
    rev.original_invoice_id = root.id
    return rev


def test_plain_invoice_keeps_its_own_guid():
    """Backward compatibility: a never-revised invoice is byte-for-byte as before."""
    inv = make_sales_invoice()
    assert not hasattr(inv, "original_invoice_id")          # the real fixture shape
    assert voucher_guid(inv) == str(inv.id)
    inv.original_invoice_id = None                           # the real column, NULL
    inv.revision_no = 1
    assert voucher_guid(inv) == str(inv.id)
    v = _voucher(build_sales_xml(inv, make_company(), make_party(), LED))
    assert v.findtext("GUID") == str(inv.id)


def test_revision_shares_the_original_guid():
    company, party = make_company(), make_party()
    root = make_sales_invoice(invoice_no="INV/25-26/0001")
    rev = _revision_of(root, 2, "INV/25-26/0001/Rv2",
                       items=[make_invoice_item(quantity=Decimal("6.000"), rate=Decimal("500.00"),
                                                amount=Decimal("3000.00"), gst_rate=Decimal("5.00"))],
                       taxable_amount=Decimal("3000.00"), cgst_amount=Decimal("75.00"),
                       sgst_amount=Decimal("75.00"), grand_total=Decimal("3150.00"))
    assert rev.id != root.id                                  # a genuinely new row

    v_root = _voucher(build_sales_xml(root, company, party, LED))
    v_rev = _voucher(build_sales_xml(rev, company, party, LED))

    # same GUID → Tally alters the existing voucher instead of creating a second one
    assert v_rev.findtext("GUID") == v_root.findtext("GUID") == str(root.id)
    # ...but the voucher carries the REVISION's number and figures
    assert v_rev.findtext("VOUCHERNUMBER") == "INV/25-26/0001/Rv2"
    assert v_root.findtext("VOUCHERNUMBER") == "INV/25-26/0001"
    party_amt = [e.findtext("AMOUNT") for e in v_rev.findall("ALLLEDGERENTRIES.LIST")
                 if e.findtext("ISPARTYLEDGER") == "Yes"][0]
    assert Decimal(party_amt) == Decimal("3150.00")


def test_third_revision_points_at_the_root_not_its_parent():
    root = make_sales_invoice(invoice_no="INV/25-26/0007")
    rv2 = _revision_of(root, 2, "INV/25-26/0007/Rv2")
    rv3 = _revision_of(root, 3, "INV/25-26/0007/Rv3")   # the app stores the ROOT on every revision
    assert voucher_guid(rv2) == voucher_guid(rv3) == str(root.id)
    assert voucher_guid(rv3) != str(rv2.id)


def test_purchase_revision_shares_the_original_guid():
    company, party = make_company(), make_party()
    root = make_purchase_invoice(invoice_no="PUR/25-26/0003")
    rev = _revision_of(root, 2, "PUR/25-26/0003/Rv2")
    v_root = _voucher(build_purchase_xml(root, company, party, LED))
    v_rev = _voucher(build_purchase_xml(rev, company, party, LED))
    assert v_rev.findtext("GUID") == v_root.findtext("GUID") == str(root.id)
    assert v_rev.findtext("VOUCHERNUMBER") == "PUR/25-26/0003/Rv2"


def test_credit_note_against_a_revised_invoice_keeps_its_own_guid():
    """A note is a separate document. It links through reference_invoice_id and
    must never inherit the invoice's GUID — that would overwrite the sale."""
    company, party = make_company(), make_party()
    root = make_sales_invoice(invoice_no="INV/25-26/0009")
    rev = _revision_of(root, 2, "INV/25-26/0009/Rv2")
    note = make_sales_invoice(invoice_no="CN/25-26/0001", invoice_type="credit_note",
                              invoice_date=date(2025, 6, 26), vehicle_no=None, token_no=None,
                              net_weight=None)
    note.reference_invoice_id = rev.id          # what issue_note sets
    note.original_invoice_id = None             # what issue_note does NOT set
    v = _voucher(build_credit_note_xml(note, company, party, LED,
                                       reference_invoice_no=rev.invoice_no))
    assert v.findtext("GUID") == str(note.id)
    assert v.findtext("GUID") != voucher_guid(rev)

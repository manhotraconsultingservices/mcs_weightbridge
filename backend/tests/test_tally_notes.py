"""Tally Credit Note / Debit Note voucher builders.

A seller-issued Credit Note (against a sale) REVERSES the sale: customer credited,
Sales + output GST debited, settled "Agst Ref" the original invoice.
A Debit Note (supplementary) goes the SAME direction as a sale: customer debited.
Both must balance to zero and post goods to the "Sales" ledger (not "Purchase").
"""
from decimal import Decimal
from datetime import date
from xml.etree import ElementTree as ET

from app.integrations.tally.xml_builder import (
    build_credit_note_xml, build_debit_note_xml, TallyLedgerMap,
)
from tests.conftest import make_company, make_party, make_invoice_item, make_sales_invoice

LED = TallyLedgerMap(sales="Sales", purchase="Purchase", cgst="CGST", sgst="SGST", igst="IGST")


def _note_invoice(invoice_type, no):
    return make_sales_invoice(
        invoice_no=no, invoice_date=date(2025, 6, 26), invoice_type=invoice_type,
        items=[make_invoice_item(description="M-Sand", quantity=Decimal("4.000"), unit="MT",
                                 rate=Decimal("500.00"), amount=Decimal("2000.00"), gst_rate=Decimal("5.00"))],
        taxable_amount=Decimal("2000.00"), cgst_amount=Decimal("50.00"), sgst_amount=Decimal("50.00"),
        igst_amount=Decimal("0.00"), grand_total=Decimal("2100.00"), round_off=Decimal("0.00"),
        vehicle_no=None, token_no=None, net_weight=None,
    )


def _voucher(xml):
    return ET.fromstring(xml).find(".//VOUCHER")


def _balance(v):
    s = sum(Decimal(e.findtext("AMOUNT", "0")) for e in v.findall("ALLLEDGERENTRIES.LIST"))
    s += sum(Decimal(e.findtext("AMOUNT", "0")) for e in v.findall("INVENTORYENTRIES.LIST"))
    return s


def _party_entry(v):
    for e in v.findall("ALLLEDGERENTRIES.LIST"):
        if e.findtext("ISPARTYLEDGER") == "Yes":
            return e
    return None


def _item_ledgers(v):
    return [a.findtext("LEDGERNAME") for inv in v.findall("INVENTORYENTRIES.LIST")
            for a in inv.findall("ACCOUNTINGALLOCATIONS.LIST")]


def test_credit_note_reverses_sale():
    company, party = make_company(), make_party()
    inv = _note_invoice("credit_note", "CN/25-26/0001")
    v = _voucher(build_credit_note_xml(inv, company, party, LED, reference_invoice_no="INV/25-26/0007"))

    assert v.get("VCHTYPE") == "Credit Note"
    assert v.findtext("VOUCHERTYPENAME") == "Credit Note"
    pe = _party_entry(v)
    assert pe.findtext("ISDEEMEDPOSITIVE") == "No"           # customer CREDITED
    assert Decimal(pe.findtext("AMOUNT")) == Decimal("-2100.00")
    ba = pe.find("BILLALLOCATIONS.LIST")
    assert ba.findtext("BILLTYPE") == "Agst Ref"             # settles the original
    assert ba.findtext("NAME") == "INV/25-26/0007"
    assert _item_ledgers(v) == ["Sales"]                     # goods post to Sales, not Purchase
    assert _balance(v) == Decimal("0.00")                    # voucher balances


def test_debit_note_matches_sale_direction():
    company, party = make_company(), make_party()
    inv = _note_invoice("debit_note", "DN/25-26/0001")
    v = _voucher(build_debit_note_xml(inv, company, party, LED, reference_invoice_no="INV/25-26/0007"))

    assert v.get("VCHTYPE") == "Debit Note"
    pe = _party_entry(v)
    assert pe.findtext("ISDEEMEDPOSITIVE") == "Yes"          # customer DEBITED
    assert Decimal(pe.findtext("AMOUNT")) == Decimal("2100.00")
    assert pe.find("BILLALLOCATIONS.LIST").findtext("BILLTYPE") == "Agst Ref"
    assert _item_ledgers(v) == ["Sales"]
    assert _balance(v) == Decimal("0.00")


def test_note_gst_reversed_vs_sale():
    """CN debits output GST (positive); DN credits it (negative)."""
    company, party = make_company(), make_party()
    cn = _voucher(build_credit_note_xml(_note_invoice("credit_note", "CN/1"), company, party, LED))
    dn = _voucher(build_debit_note_xml(_note_invoice("debit_note", "DN/1"), company, party, LED))

    def tax(v, name):
        for e in v.findall("ALLLEDGERENTRIES.LIST"):
            if e.findtext("LEDGERNAME") == name:
                return Decimal(e.findtext("AMOUNT"))
        return None

    assert tax(cn, "CGST") == Decimal("50.00") and tax(cn, "SGST") == Decimal("50.00")    # debit (reverse)
    assert tax(dn, "CGST") == Decimal("-50.00") and tax(dn, "SGST") == Decimal("-50.00")  # credit (increase)

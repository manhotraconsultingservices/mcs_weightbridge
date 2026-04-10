"""
Tally Integration Test Suite
~35 tests covering:
  Cat 1 — XML Structure     (no server, pure builder tests)
  Cat 2 — Ledger Balance    (no server, verify amounts sum to zero)
  Cat 3 — Mock Server       (HTTP round-trip with MockTallyServer)
  Cat 4 — Edge Cases        (special characters, zero amounts, multi-item)

Run:
    cd backend
    python -m pytest tests/test_tally_integration.py -v
"""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import httpx
import pytest

from app.integrations.tally.xml_builder import (
    TallyLedgerMap,
    NarrationOptions,
    build_customer_master_xml,
    build_purchase_order_xml,
    build_purchase_xml,
    build_sales_order_xml,
    build_sales_xml,
    build_supplier_master_xml,
)
from tests.conftest import (
    MOCK_TALLY_PORT,
    make_company,
    make_invoice_item,
    make_party,
    make_po_item,
    make_purchase_invoice,
    make_purchase_order,
    make_quotation,
    make_sales_invoice,
)
from tests.mock_tally_server import _voucher_is_balanced

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse(xml_str: str) -> ET.Element:
    """Parse XML string and return root element. Raises on malformed XML."""
    return ET.fromstring(xml_str)


def _find_voucher(root: ET.Element) -> ET.Element:
    el = root.find(".//VOUCHER")
    assert el is not None, "No VOUCHER element found in XML"
    return el


def _find_ledger(root: ET.Element) -> ET.Element:
    el = root.find(".//LEDGER")
    assert el is not None, "No LEDGER element found in XML"
    return el


def _collect_all_ledger_amounts(voucher: ET.Element) -> list[float]:
    """Collect all ALLLEDGERENTRIES amounts + ACCOUNTINGALLOCATIONS amounts."""
    amounts: list[float] = []
    for entry in voucher.findall("ALLLEDGERENTRIES.LIST"):
        t = entry.findtext("AMOUNT")
        if t:
            amounts.append(float(t.strip()))
    for inv in voucher.findall("INVENTORYENTRIES.LIST"):
        for acc in inv.findall("ACCOUNTINGALLOCATIONS.LIST"):
            t = acc.findtext("AMOUNT")
            if t:
                amounts.append(float(t.strip()))
    return amounts


def _post_to_mock(xml_str: str, port: int = MOCK_TALLY_PORT) -> tuple[int, str]:
    """Synchronously POST XML to mock server. Returns (status_code, body)."""
    with httpx.Client(timeout=5.0) as client:
        resp = client.post(
            f"http://127.0.0.1:{port}",
            content=xml_str.encode("utf-8"),
            headers={"Content-Type": "text/xml"},
        )
    return resp.status_code, resp.text


# ─────────────────────────────────────────────────────────────────────────────
# Category 1 — XML Structure (12 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestXmlStructure:

    def test_sales_invoice_xml_well_formed(self):
        """Sales XML must parse without error."""
        company = make_company()
        party = make_party()
        inv = make_sales_invoice(party=party)
        xml = build_sales_xml(inv, company, party)
        root = _parse(xml)   # raises ET.ParseError if malformed
        assert root is not None

    def test_purchase_invoice_xml_well_formed(self):
        company = make_company()
        party = make_party(party_type="supplier")
        inv = make_purchase_invoice(party=party)
        xml = build_purchase_xml(inv, company, party)
        assert _parse(xml) is not None

    def test_sales_invoice_vchtype(self):
        company = make_company()
        party = make_party()
        inv = make_sales_invoice(party=party)
        root = _parse(build_sales_xml(inv, company, party))
        vch = _find_voucher(root)
        assert vch.get("VCHTYPE") == "Sales"

    def test_purchase_invoice_vchtype(self):
        company = make_company()
        party = make_party(party_type="supplier")
        inv = make_purchase_invoice(party=party)
        root = _parse(build_purchase_xml(inv, company, party))
        vch = _find_voucher(root)
        assert vch.get("VCHTYPE") == "Purchase"

    def test_customer_master_parent_sundry_debtors(self):
        company = make_company()
        party = make_party(party_type="customer")
        root = _parse(build_customer_master_xml(party, company))
        ledger = _find_ledger(root)
        assert ledger.findtext("PARENT") == "Sundry Debtors"

    def test_supplier_master_parent_sundry_creditors(self):
        company = make_company()
        party = make_party(party_type="supplier")
        root = _parse(build_supplier_master_xml(party, company))
        ledger = _find_ledger(root)
        assert ledger.findtext("PARENT") == "Sundry Creditors"

    def test_customer_with_gstin_gst_reg_type_regular(self):
        company = make_company()
        party = make_party(gstin="27ABCDE1234F1Z5")
        root = _parse(build_customer_master_xml(party, company))
        ledger = _find_ledger(root)
        assert ledger.findtext("GSTREGISTRATIONTYPE") == "Regular"

    def test_customer_without_gstin_gst_reg_type_unregistered(self):
        company = make_company()
        party = make_party(gstin=None)
        root = _parse(build_customer_master_xml(party, company))
        ledger = _find_ledger(root)
        assert ledger.findtext("GSTREGISTRATIONTYPE") == "Unregistered"

    def test_customer_address_has_two_children(self):
        company = make_company()
        party = make_party(billing_address="Plot 12", billing_city="Pune", billing_pincode="411001")
        root = _parse(build_customer_master_xml(party, company))
        ledger = _find_ledger(root)
        addr_list = ledger.find("ADDRESS.LIST")
        assert addr_list is not None
        addresses = addr_list.findall("ADDRESS")
        assert len(addresses) == 2

    def test_sales_order_no_billallocations(self):
        company = make_company()
        party = make_party()
        quot = make_quotation(party=party)
        root = _parse(build_sales_order_xml(quot, company, party))
        vch = _find_voucher(root)
        # BILLALLOCATIONS.LIST must NOT appear anywhere in a Sales Order
        bill_alloc_count = sum(
            len(entry.findall("BILLALLOCATIONS.LIST"))
            for entry in vch.findall("ALLLEDGERENTRIES.LIST")
        )
        assert bill_alloc_count == 0

    def test_sales_order_objview_ordering(self):
        company = make_company()
        party = make_party()
        quot = make_quotation(party=party)
        root = _parse(build_sales_order_xml(quot, company, party))
        vch = _find_voucher(root)
        assert vch.get("OBJVIEW") == "Ordering Voucher View"

    def test_purchase_order_vchtype(self):
        company = make_company()
        po = make_purchase_order()
        items = po.items
        tally_company = company.tally_company_name
        root = _parse(build_purchase_order_xml(po, items, tally_company))
        vch = _find_voucher(root)
        assert vch.get("VCHTYPE") == "Purchase Order"

    def test_sales_order_vchtype(self):
        company = make_company()
        party = make_party()
        quot = make_quotation(party=party)
        root = _parse(build_sales_order_xml(quot, company, party))
        vch = _find_voucher(root)
        assert vch.get("VCHTYPE") == "Sales Order"

    def test_master_xml_reportname_all_masters(self):
        company = make_company()
        party = make_party()
        root = _parse(build_customer_master_xml(party, company))
        reportname = root.findtext(".//REPORTNAME")
        assert reportname == "All Masters"

    def test_voucher_xml_reportname_vouchers(self):
        company = make_company()
        party = make_party()
        inv = make_sales_invoice(party=party)
        root = _parse(build_sales_xml(inv, company, party))
        reportname = root.findtext(".//REPORTNAME")
        assert reportname == "Vouchers"


# ─────────────────────────────────────────────────────────────────────────────
# Category 2 — Ledger Balance (10 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestLedgerBalance:
    """
    Every voucher must balance: sum(all ledger amounts) = 0.
    Sign convention:
      Sales   — party +grand_total, sales ledger -taxable, tax ledgers -tax
      Purchase — party -grand_total, purchase ledger +taxable, tax ledgers +tax
    """

    TOL = 0.02  # tolerance in rupees

    def _assert_balanced(self, xml_str: str):
        root = _parse(xml_str)
        vch = _find_voucher(root)
        balanced, total = _voucher_is_balanced(vch, self.TOL)
        assert balanced, f"Voucher NOT balanced: sum = {total:.4f}"

    def test_sales_voucher_balances(self):
        company = make_company()
        party = make_party()
        inv = make_sales_invoice(
            party=party,
            taxable_amount=Decimal("8000.00"),
            cgst_amount=Decimal("200.00"),
            sgst_amount=Decimal("200.00"),
            grand_total=Decimal("8400.00"),
        )
        self._assert_balanced(build_sales_xml(inv, company, party))

    def test_purchase_voucher_balances(self):
        company = make_company()
        party = make_party(party_type="supplier")
        inv = make_purchase_invoice(
            party=party,
            taxable_amount=Decimal("5000.00"),
            cgst_amount=Decimal("125.00"),
            sgst_amount=Decimal("125.00"),
            grand_total=Decimal("5250.00"),
        )
        self._assert_balanced(build_purchase_xml(inv, company, party))

    def test_sales_with_discount_balances(self):
        """
        Tally discount accounting:
          item.amount = GROSS value (before discount) → goes to Sales ledger
          discount ledger entry = +discount (debit, reduces income)
          party amount = grand_total = gross - discount + GST

          Balance: party + items_credit + discount_debit + gst_credit = 0
            +9975 - 10000 + 500 - 475 = 0 ✓
        """
        company = make_company()
        party = make_party()
        gross = Decimal("10000.00")    # item amount (before discount)
        discount = Decimal("500.00")
        taxable = gross - discount     # 9500 — used for GST computation
        cgst = Decimal("237.50")       # 5% / 2
        sgst = Decimal("237.50")
        grand_total = taxable + cgst + sgst  # 9975.00
        items = [make_invoice_item(amount=gross)]   # gross in Tally item entry
        inv = make_sales_invoice(
            party=party,
            items=items,
            taxable_amount=taxable,
            discount_amount=discount,
            cgst_amount=cgst,
            sgst_amount=sgst,
            grand_total=grand_total,
        )
        self._assert_balanced(build_sales_xml(inv, company, party))

    def test_sales_with_freight_balances(self):
        company = make_company()
        party = make_party()
        taxable = Decimal("8000.00")
        freight = Decimal("300.00")
        cgst = Decimal("200.00")
        sgst = Decimal("200.00")
        grand_total = taxable + freight + cgst + sgst  # 8700
        items = [make_invoice_item(amount=taxable)]
        inv = make_sales_invoice(
            party=party,
            items=items,
            taxable_amount=taxable,
            freight=freight,
            cgst_amount=cgst,
            sgst_amount=sgst,
            grand_total=grand_total,
        )
        self._assert_balanced(build_sales_xml(inv, company, party))

    def test_igst_only_balances(self):
        """Inter-state sales: only IGST, no CGST/SGST."""
        company = make_company()
        party = make_party(billing_state="Delhi", billing_state_code="07")
        taxable = Decimal("8000.00")
        igst = Decimal("400.00")  # 5%
        grand_total = taxable + igst
        items = [make_invoice_item(amount=taxable)]
        inv = make_sales_invoice(
            party=party,
            items=items,
            taxable_amount=taxable,
            cgst_amount=Decimal("0.00"),
            sgst_amount=Decimal("0.00"),
            igst_amount=igst,
            grand_total=grand_total,
        )
        self._assert_balanced(build_sales_xml(inv, company, party))

    def test_cgst_sgst_only_balances(self):
        """Intra-state purchase: CGST + SGST, no IGST."""
        company = make_company()
        party = make_party(party_type="supplier")
        taxable = Decimal("10000.00")
        cgst = Decimal("900.00")  # 9%
        sgst = Decimal("900.00")
        grand_total = taxable + cgst + sgst
        items = [make_invoice_item(amount=taxable)]
        inv = make_purchase_invoice(
            party=party,
            items=items,
            taxable_amount=taxable,
            cgst_amount=cgst,
            sgst_amount=sgst,
            grand_total=grand_total,
        )
        self._assert_balanced(build_purchase_xml(inv, company, party))

    def test_with_tcs_balances(self):
        """Sales invoice with TCS — party amount includes TCS."""
        company = make_company()
        party = make_party()
        taxable = Decimal("100000.00")
        cgst = Decimal("2500.00")
        sgst = Decimal("2500.00")
        tcs = Decimal("1050.00")  # 1% on grand total (before TCS) ≈ 1050
        grand_total = taxable + cgst + sgst + tcs  # 106050
        items = [make_invoice_item(
            quantity=Decimal("100.000"),
            rate=Decimal("1000.00"),
            amount=taxable,
        )]
        inv = make_sales_invoice(
            party=party,
            items=items,
            taxable_amount=taxable,
            cgst_amount=cgst,
            sgst_amount=sgst,
            tcs_amount=tcs,
            grand_total=grand_total,
        )
        self._assert_balanced(build_sales_xml(inv, company, party))

    def test_with_round_off_balances(self):
        """Invoice with round-off must still balance."""
        company = make_company()
        party = make_party()
        taxable = Decimal("7999.00")
        cgst = Decimal("200.00")
        sgst = Decimal("200.00")
        round_off = Decimal("1.00")  # round up to 8400
        grand_total = Decimal("8400.00")
        items = [make_invoice_item(amount=taxable)]
        inv = make_sales_invoice(
            party=party,
            items=items,
            taxable_amount=taxable,
            cgst_amount=cgst,
            sgst_amount=sgst,
            round_off=round_off,
            grand_total=grand_total,
        )
        self._assert_balanced(build_sales_xml(inv, company, party))

    def test_zero_amounts_no_extra_entries(self):
        """When discount/freight/tcs/round_off = 0, no spurious ledger entries."""
        company = make_company()
        party = make_party()
        taxable = Decimal("5000.00")
        cgst = Decimal("125.00")
        sgst = Decimal("125.00")
        grand_total = taxable + cgst + sgst
        items = [make_invoice_item(amount=taxable)]
        inv = make_sales_invoice(
            party=party,
            items=items,
            taxable_amount=taxable,
            discount_amount=Decimal("0.00"),
            freight=Decimal("0.00"),
            tcs_amount=Decimal("0.00"),
            round_off=Decimal("0.00"),
            cgst_amount=cgst,
            sgst_amount=sgst,
            grand_total=grand_total,
        )
        xml = build_sales_xml(inv, company, party)
        self._assert_balanced(xml)

        # Verify only party + 2 GST + items → no discount/freight/TCS entries
        root = _parse(xml)
        vch = _find_voucher(root)
        ledger_names = [e.findtext("LEDGERNAME") for e in vch.findall("ALLLEDGERENTRIES.LIST")]
        for forbidden in ("Trade Discount", "Freight Outward", "TCS Payable", "Round Off"):
            assert forbidden not in ledger_names, f"Unexpected ledger entry: {forbidden}"

    def test_sales_order_xml_well_formed_and_has_inventory(self):
        """Sales Order XML must be well-formed and have inventory entries."""
        company = make_company()
        party = make_party()
        quot = make_quotation(party=party)
        xml = build_sales_order_xml(quot, company, party)
        root = _parse(xml)
        vch = _find_voucher(root)
        assert len(vch.findall("INVENTORYENTRIES.LIST")) >= 1

    def test_purchase_order_xml_well_formed(self):
        """Purchase Order XML must be well-formed."""
        company = make_company()
        po = make_purchase_order()
        xml = build_purchase_order_xml(po, po.items, company.tally_company_name)
        assert _parse(xml) is not None


# ─────────────────────────────────────────────────────────────────────────────
# Category 3 — Mock Server Integration (8 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestMockServerIntegration:

    def test_push_sales_invoice_success(self, mock_tally_server):
        company = make_company()
        party = make_party()
        inv = make_sales_invoice(party=party)
        xml = build_sales_xml(inv, company, party)
        status, body = _post_to_mock(xml)
        assert status == 200
        assert "<CREATED>1</CREATED>" in body
        vouchers = mock_tally_server.received_vouchers
        assert len(vouchers) == 1
        assert vouchers[0]["vchtype"] == "Sales"

    def test_push_purchase_invoice_success(self, mock_tally_server):
        company = make_company()
        party = make_party(party_type="supplier")
        inv = make_purchase_invoice(party=party)
        xml = build_purchase_xml(inv, company, party)
        status, body = _post_to_mock(xml)
        assert status == 200
        assert len(mock_tally_server.received_vouchers) == 1
        assert mock_tally_server.received_vouchers[0]["vchtype"] == "Purchase"

    def test_push_customer_master_success(self, mock_tally_server):
        company = make_company()
        party = make_party(party_type="customer", name="Sharma Stone Works")
        xml = build_customer_master_xml(party, company)
        status, body = _post_to_mock(xml)
        assert status == 200
        masters = mock_tally_server.received_masters
        assert len(masters) == 1
        assert masters[0]["parent"] == "Sundry Debtors"
        assert masters[0]["name"] == "Sharma Stone Works"

    def test_push_supplier_master_success(self, mock_tally_server):
        company = make_company()
        party = make_party(party_type="supplier", name="Rock Suppliers Ltd")
        xml = build_supplier_master_xml(party, company)
        status, body = _post_to_mock(xml)
        assert status == 200
        masters = mock_tally_server.received_masters
        assert len(masters) == 1
        assert masters[0]["parent"] == "Sundry Creditors"

    def test_push_sales_order_success(self, mock_tally_server):
        company = make_company()
        party = make_party()
        quot = make_quotation(party=party)
        xml = build_sales_order_xml(quot, company, party)
        status, body = _post_to_mock(xml)
        assert status == 200
        vouchers = mock_tally_server.received_vouchers
        assert len(vouchers) == 1
        assert vouchers[0]["vchtype"] == "Sales Order"

    def test_push_purchase_order_success(self, mock_tally_server):
        company = make_company()
        po = make_purchase_order()
        xml = build_purchase_order_xml(po, po.items, company.tally_company_name)
        status, body = _post_to_mock(xml)
        assert status == 200
        vouchers = mock_tally_server.received_vouchers
        assert len(vouchers) == 1
        assert vouchers[0]["vchtype"] == "Purchase Order"

    def test_mock_rejects_malformed_xml(self, mock_tally_server):
        """Sending garbage XML should return 400 with LINEERROR."""
        status, body = _post_to_mock("<not valid xml>>><<")
        assert status == 400
        assert "LINEERROR" in body or "ERRORS" in body
        assert len(mock_tally_server.received_vouchers) == 0

    def test_mock_error_injection(self, mock_tally_server):
        """set_error_mode causes next request to fail."""
        mock_tally_server.set_error_mode("License expired in Tally")
        company = make_company()
        party = make_party()
        inv = make_sales_invoice(party=party)
        xml = build_sales_xml(inv, company, party)
        status, body = _post_to_mock(xml)
        assert status == 400
        assert "License expired in Tally" in body
        # Error mode clears after one use
        assert mock_tally_server._error_mode is None
        assert len(mock_tally_server.received_vouchers) == 0

    def test_mock_resets_between_tests(self, mock_tally_server):
        """Each test starts with empty received_vouchers (autouse reset)."""
        assert len(mock_tally_server.received_vouchers) == 0
        assert len(mock_tally_server.received_masters) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Category 4 — Edge Cases (6 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_party_name_with_ampersand_xml_safe(self):
        """Party name with '&' must be XML-escaped."""
        company = make_company()
        party = make_party(name="Ram & Shyam Industries")
        xml = build_customer_master_xml(party, company)
        # ET.fromstring will raise if not escaped
        root = _parse(xml)
        ledger = _find_ledger(root)
        # NAME attribute or element must contain the unescaped form
        assert "Ram & Shyam Industries" in (ledger.get("NAME") or "")

    def test_party_name_with_angle_bracket_xml_safe(self):
        """Party name with '<' must be XML-escaped in XML text nodes."""
        company = make_company()
        party = make_party(name="A<B Minerals")
        xml = build_customer_master_xml(party, company)
        root = _parse(xml)   # would raise ParseError if not escaped
        assert root is not None

    def test_multiple_line_items(self, mock_tally_server):
        """3 line items must all appear as INVENTORYENTRIES.LIST."""
        company = make_company()
        party = make_party()
        items = [
            make_invoice_item("Stone 10mm", quantity=Decimal("5"), rate=Decimal("600"), amount=Decimal("3000")),
            make_invoice_item("Stone 20mm", quantity=Decimal("8"), rate=Decimal("800"), amount=Decimal("6400")),
            make_invoice_item("Stone 40mm", quantity=Decimal("3"), rate=Decimal("700"), amount=Decimal("2100")),
        ]
        taxable = Decimal("11500.00")
        cgst = Decimal("287.50")
        sgst = Decimal("287.50")
        grand_total = taxable + cgst + sgst
        inv = make_sales_invoice(
            party=party,
            items=items,
            taxable_amount=taxable,
            cgst_amount=cgst,
            sgst_amount=sgst,
            grand_total=grand_total,
        )
        xml = build_sales_xml(inv, company, party)
        root = _parse(xml)
        vch = _find_voucher(root)
        assert len(vch.findall("INVENTORYENTRIES.LIST")) == 3

        # Also push to mock and verify
        status, _ = _post_to_mock(xml)
        assert status == 200

    def test_tally_ledger_name_override(self):
        """If party has tally_ledger_name, it must be used in XML."""
        company = make_company()
        party = make_party(name="Sharma Stone Works", tally_ledger_name="Sharma Stones (Tally)")
        xml = build_customer_master_xml(party, company)
        root = _parse(xml)
        ledger = _find_ledger(root)
        assert ledger.get("NAME") == "Sharma Stones (Tally)"

    def test_supplier_master_without_gstin(self, mock_tally_server):
        """Supplier with no GSTIN must be accepted by mock as Unregistered."""
        company = make_company()
        party = make_party(party_type="supplier", name="Local Supplier", gstin=None)
        xml = build_supplier_master_xml(party, company)
        status, body = _post_to_mock(xml)
        assert status == 200
        masters = mock_tally_server.received_masters
        assert masters[0]["gst_reg_type"] == "Unregistered"

    def test_purchase_order_multi_item_balance(self):
        """PO with multiple items: party amount must equal sum of all items."""
        company = make_company()
        po_items = [
            make_po_item("Engine Oil", "Ltrs", Decimal("20"), Decimal("350")),
            make_po_item("Grease 3kg", "Nos", Decimal("5"), Decimal("450")),
            make_po_item("HSD Fuel", "Ltrs", Decimal("100"), Decimal("90")),
        ]
        expected_total = 20 * 350 + 5 * 450 + 100 * 90  # 7000 + 2250 + 9000 = 18250
        po = make_purchase_order(po_no="PO/25-26/0099", items=po_items)
        xml = build_purchase_order_xml(po, po_items, company.tally_company_name)
        root = _parse(xml)
        vch = _find_voucher(root)

        # Party entry should be -18250 (purchase credit)
        party_entries = [e for e in vch.findall("ALLLEDGERENTRIES.LIST")
                         if e.findtext("ISPARTYLEDGER") == "Yes"]
        assert len(party_entries) == 1
        party_amt = float(party_entries[0].findtext("AMOUNT") or "0")
        assert abs(party_amt - (-expected_total)) < 0.02

        # Verify 3 inventory entries
        assert len(vch.findall("INVENTORYENTRIES.LIST")) == 3

    def test_narration_options_off(self):
        """With all narration options off, narration is just 'Sales <invoice_no>'."""
        company = make_company()
        party = make_party()
        inv = make_sales_invoice(party=party, invoice_no="SI/25-26/0042")
        opts = NarrationOptions(include_vehicle=False, include_token=False, include_weight=False)
        xml = build_sales_xml(inv, company, party, narration_opts=opts)
        root = _parse(xml)
        vch = _find_voucher(root)
        narration = vch.findtext("NARRATION") or ""
        assert "Sales SI/25-26/0042" in narration
        assert "Token" not in narration
        assert "Vehicle" not in narration
        assert "Net Wt" not in narration

    def test_customer_gstin_in_master_xml(self):
        """GSTIN must appear in customer master LEDGER element."""
        company = make_company()
        party = make_party(gstin="27ABCDE9999X1Z3")
        xml = build_customer_master_xml(party, company)
        root = _parse(xml)
        ledger = _find_ledger(root)
        assert ledger.findtext("GSTIN") == "27ABCDE9999X1Z3"

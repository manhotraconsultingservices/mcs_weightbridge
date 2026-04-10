"""
Tally Prime XML builder — converts invoices to Tally-compatible import XML.

Phase 1 changes:
  - All ledger names configurable (no hard-coded "Sales", "CGST", etc.)
  - Discount, Freight, TCS, Round-off ledger entries added so vouchers balance
  - Buyer GSTIN + Place of Supply included for GST compliance
  - Rich narration: voucher type | token no | vehicle no | net weight
  - GST rate % passed on each inventory item

Phase 2 changes:
  - BILLALLOCATIONS.LIST on party entry → enables bill-wise aging in Tally
  - CREDITPERIOD derived from invoice due_date or party payment_terms_days
  - Net weight already in narration (wired via NarrationOptions.include_weight)
  - Per-party tally_ledger_name used via _party_name() helper

Amount sign convention in Tally:
  Sales voucher  — party Debited (+),  sales/tax/freight ledgers Credited (-)
  Purchase voucher — party Credited (-), purchase/tax/freight ledgers Debited (+)

Balance check (Sales):
  +grand_total (party)
  - subtotal   (inventory items → sales ledger)
  + discount   (discount ledger, debit — reduces income)
  - freight    (freight ledger, credit — freight income)
  - cgst/sgst  (tax ledgers, credit — tax liability)
  - tcs        (TCS ledger, credit — TCS liability)
  ± round_off  (round-off ledger)
  = 0 ✓
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date as _date
from decimal import Decimal
from xml.etree import ElementTree as ET
from xml.dom import minidom
import uuid as _uuid


# ─────────────────────────────────────────────────────────────────────────────
# Ledger mapping config (passed from TallyConfig)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TallyLedgerMap:
    """All configurable ledger names. Defaults match typical Tally setup."""
    sales: str = "Sales"
    purchase: str = "Purchase"
    cgst: str = "CGST"
    sgst: str = "SGST"
    igst: str = "IGST"
    freight: str = "Freight Outward"
    discount: str = "Trade Discount"
    tcs: str = "TCS Payable"
    roundoff: str = "Round Off"


@dataclass
class NarrationOptions:
    include_vehicle: bool = True
    include_token: bool = True
    include_weight: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_date(d) -> str:
    """Convert date/str to YYYYMMDD for Tally."""
    return str(d).replace("-", "")[:8]


def _fmt_amt(v, sign: int = 1) -> str:
    """Format amount with sign: positive = debit, negative = credit in Tally."""
    return f"{sign * float(v):.2f}"


def _sub(parent, tag, text=""):
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el


def _pretty(root: ET.Element) -> str:
    raw = ET.tostring(root, encoding="unicode")
    dom = minidom.parseString(raw)
    return dom.toprettyxml(indent="  ", encoding=None)


def _build_narration(
    vch_type: str,
    invoice_no: str,
    opts: NarrationOptions,
    vehicle_no: str | None,
    token_no: int | None,
    net_weight_kg: Decimal | None,
) -> str:
    parts = [f"{vch_type} {invoice_no}"]
    if opts.include_token and token_no:
        parts.append(f"Token #{token_no}")
    if opts.include_vehicle and vehicle_no:
        parts.append(f"Vehicle: {vehicle_no}")
    if opts.include_weight and net_weight_kg and net_weight_kg > 0:
        mt = float(net_weight_kg) / 1000
        parts.append(f"Net Wt: {mt:.3f} MT")
    return " | ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Core XML builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_voucher_xml(
    *,
    vch_type: str,                   # "Sales" | "Purchase"
    voucher_no: str,
    voucher_date,
    due_date: _date | None = None,   # Phase 2: for BILLALLOCATIONS credit period
    payment_terms_days: int = 0,     # Phase 2: fallback when due_date absent
    narration: str,
    party_name: str,
    party_gstin: str | None,
    place_of_supply: str | None,     # State name, e.g. "Maharashtra"
    tally_company: str,
    items: list[dict],               # [{name, unit, qty, rate, amount, hsn, gst_rate}]
    taxable_amount: Decimal,
    discount_amount: Decimal,
    freight: Decimal,
    cgst_amount: Decimal,
    sgst_amount: Decimal,
    igst_amount: Decimal,
    tcs_amount: Decimal,
    round_off: Decimal,
    grand_total: Decimal,
    ledgers: TallyLedgerMap,
    guid: str | None = None,
) -> str:
    is_sale = vch_type == "Sales"

    # Sign convention: Sales → party +, ledgers -
    #                  Purchase → party -, ledgers +
    party_sign = 1 if is_sale else -1
    ledger_sign = -1 if is_sale else 1   # sales/tax/freight ledgers
    stock_sign = -1 if is_sale else 1    # inventory items

    # Discount is on opposite side: reduces income (Sales debit) / reduces cost (Purchase credit)
    discount_sign = 1 if is_sale else -1

    root = ET.Element("ENVELOPE")
    hdr = _sub(root, "HEADER")
    _sub(hdr, "TALLYREQUEST", "Import Data")

    body = _sub(root, "BODY")
    imp = _sub(body, "IMPORTDATA")
    rdesc = _sub(imp, "REQUESTDESC")
    _sub(rdesc, "REPORTNAME", "Vouchers")
    static = _sub(rdesc, "STATICVARIABLES")
    _sub(static, "SVCURRENTCOMPANY", tally_company)

    rdata = _sub(imp, "REQUESTDATA")
    msg = _sub(rdata, "TALLYMESSAGE")
    msg.set("xmlns:UDF", "TallyUDF")

    vch = _sub(msg, "VOUCHER")
    vch.set("VCHTYPE", vch_type)
    vch.set("ACTION", "Create")
    vch.set("OBJVIEW", "Invoice Voucher View")

    _sub(vch, "DATE", _fmt_date(voucher_date))
    _sub(vch, "GUID", guid or str(_uuid.uuid4()))
    _sub(vch, "NARRATION", narration)
    _sub(vch, "VOUCHERTYPENAME", vch_type)
    _sub(vch, "VOUCHERNUMBER", voucher_no)
    _sub(vch, "PARTYLEDGERNAME", party_name)
    _sub(vch, "BASICBASEPARTYNAME", party_name)
    _sub(vch, "PERSISTEDVIEW", "Invoice Voucher View")

    # Place of supply (state name) for GST
    if place_of_supply:
        _sub(vch, "PLACEOFSUPPLY", place_of_supply)

    # ── Party ledger entry ──────────────────────────────────────────────────
    party_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
    _sub(party_entry, "LEDGERNAME", party_name)
    _sub(party_entry, "ISDEEMEDPOSITIVE", "Yes" if is_sale else "No")
    _sub(party_entry, "ISPARTYLEDGER", "Yes")
    _sub(party_entry, "AMOUNT", _fmt_amt(grand_total, party_sign))

    # Buyer GSTIN on the party entry (used by Tally for GSTR reports)
    if party_gstin:
        _sub(party_entry, "GSTREGISTRATIONTYPE", "Regular")
        _sub(party_entry, "PARTYGSTIN", party_gstin)

    # ── Bill allocation (enables bill-wise aging in Tally) ──────────────────
    # Compute credit period: prefer explicit due_date, fall back to payment_terms_days
    credit_days: int = 0
    if due_date and voucher_date:
        try:
            inv_date = voucher_date if isinstance(voucher_date, _date) else _date.fromisoformat(str(voucher_date)[:10])
            due = due_date if isinstance(due_date, _date) else _date.fromisoformat(str(due_date)[:10])
            credit_days = max(0, (due - inv_date).days)
        except Exception:
            credit_days = payment_terms_days or 0
    else:
        credit_days = payment_terms_days or 0

    bill_alloc = _sub(party_entry, "BILLALLOCATIONS.LIST")
    _sub(bill_alloc, "NAME", voucher_no or str(_uuid.uuid4())[:8])
    _sub(bill_alloc, "BILLTYPE", "New Ref")
    _sub(bill_alloc, "AMOUNT", _fmt_amt(grand_total, party_sign))
    if credit_days > 0:
        _sub(bill_alloc, "CREDITPERIOD", f"{credit_days} Days")

    # ── Inventory entries (one per line item) ───────────────────────────────
    item_ledger = ledgers.sales if is_sale else ledgers.purchase
    for item in items:
        inv_entry = _sub(vch, "INVENTORYENTRIES.LIST")
        _sub(inv_entry, "STOCKITEMNAME", item["name"])
        _sub(inv_entry, "ISDEEMEDPOSITIVE", "No" if is_sale else "Yes")
        _sub(inv_entry, "RATE", f"{float(item['rate']):.2f}/{item['unit']}")
        _sub(inv_entry, "AMOUNT", _fmt_amt(item["amount"], stock_sign))
        _sub(inv_entry, "ACTUALQTY", f"{float(item['qty']):.3f} {item['unit']}")
        _sub(inv_entry, "BILLEDQTY", f"{float(item['qty']):.3f} {item['unit']}")

        # HSN + GST rate for GSTR-1 HSN summary
        if item.get("hsn"):
            _sub(inv_entry, "GSTTAXABILITY", "Taxable")
            _sub(inv_entry, "HSNCODE", item["hsn"])
        if item.get("gst_rate") and float(item["gst_rate"]) > 0:
            _sub(inv_entry, "GSTRATE", f"{float(item['gst_rate']):.2f}")

        # Batch allocation
        batch = _sub(inv_entry, "BATCHALLOCATIONS.LIST")
        _sub(batch, "GODOWNNAME", "Main Location")
        _sub(batch, "BATCHNAME", "Primary Batch")
        _sub(batch, "AMOUNT", _fmt_amt(item["amount"], stock_sign))
        _sub(batch, "ACTUALQTY", f"{float(item['qty']):.3f} {item['unit']}")
        _sub(batch, "BILLEDQTY", f"{float(item['qty']):.3f} {item['unit']}")

        # Accounting allocation inside inventory entry (links item to sales/purchase ledger)
        acc = _sub(inv_entry, "ACCOUNTINGALLOCATIONS.LIST")
        _sub(acc, "LEDGERNAME", item_ledger)
        _sub(acc, "ISDEEMEDPOSITIVE", "No" if is_sale else "Yes")
        _sub(acc, "AMOUNT", _fmt_amt(item["amount"], stock_sign))

    # ── Discount ledger entry ───────────────────────────────────────────────
    if float(discount_amount) > 0:
        disc_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
        _sub(disc_entry, "LEDGERNAME", ledgers.discount)
        # Discount: Sales → debit (+), Purchase → credit (-)
        _sub(disc_entry, "ISDEEMEDPOSITIVE", "Yes" if is_sale else "No")
        _sub(disc_entry, "AMOUNT", _fmt_amt(discount_amount, discount_sign))

    # ── Freight ledger entry ────────────────────────────────────────────────
    if float(freight) > 0:
        frt_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
        _sub(frt_entry, "LEDGERNAME", ledgers.freight)
        _sub(frt_entry, "ISDEEMEDPOSITIVE", "No" if is_sale else "Yes")
        _sub(frt_entry, "AMOUNT", _fmt_amt(freight, ledger_sign))

    # ── GST ledger entries ──────────────────────────────────────────────────
    use_igst = float(igst_amount) > 0
    if use_igst:
        igst_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
        _sub(igst_entry, "LEDGERNAME", ledgers.igst)
        _sub(igst_entry, "ISDEEMEDPOSITIVE", "No" if is_sale else "Yes")
        _sub(igst_entry, "AMOUNT", _fmt_amt(igst_amount, ledger_sign))
    else:
        if float(cgst_amount) > 0:
            cgst_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
            _sub(cgst_entry, "LEDGERNAME", ledgers.cgst)
            _sub(cgst_entry, "ISDEEMEDPOSITIVE", "No" if is_sale else "Yes")
            _sub(cgst_entry, "AMOUNT", _fmt_amt(cgst_amount, ledger_sign))
        if float(sgst_amount) > 0:
            sgst_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
            _sub(sgst_entry, "LEDGERNAME", ledgers.sgst)
            _sub(sgst_entry, "ISDEEMEDPOSITIVE", "No" if is_sale else "Yes")
            _sub(sgst_entry, "AMOUNT", _fmt_amt(sgst_amount, ledger_sign))

    # ── TCS ledger entry ────────────────────────────────────────────────────
    if float(tcs_amount) > 0:
        tcs_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
        _sub(tcs_entry, "LEDGERNAME", ledgers.tcs)
        _sub(tcs_entry, "ISDEEMEDPOSITIVE", "No" if is_sale else "Yes")
        _sub(tcs_entry, "AMOUNT", _fmt_amt(tcs_amount, ledger_sign))

    # ── Round-off ledger entry ──────────────────────────────────────────────
    if abs(float(round_off)) > 0.001:
        # Round-off sign: opposite of ledger_sign to bring total to zero
        ro_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
        _sub(ro_entry, "LEDGERNAME", ledgers.roundoff)
        # Round-off balances the voucher: same sign direction as ledger
        _sub(ro_entry, "ISDEEMEDPOSITIVE", "No" if is_sale else "Yes")
        _sub(ro_entry, "AMOUNT", _fmt_amt(round_off, ledger_sign))

    return _pretty(root)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def _build_party_master_xml(
    *,
    party_name: str,
    parent_group: str,           # "Sundry Debtors" | "Sundry Creditors"
    gstin: str | None,
    state: str | None,
    address_line1: str | None,
    city: str | None,
    pincode: str | None,
    phone: str | None,
    email: str | None,
    tally_company: str,
) -> str:
    """
    Build Tally XML to create/update a Party master (LEDGER) under All Masters.

    The resulting LEDGER element is placed under Sundry Debtors (customers)
    or Sundry Creditors (suppliers) so Tally can use it for bill-wise tracking
    and GSTR reports.
    """
    root = ET.Element("ENVELOPE")
    hdr = _sub(root, "HEADER")
    _sub(hdr, "TALLYREQUEST", "Import Data")

    body = _sub(root, "BODY")
    imp = _sub(body, "IMPORTDATA")
    rdesc = _sub(imp, "REQUESTDESC")
    _sub(rdesc, "REPORTNAME", "All Masters")
    static = _sub(rdesc, "STATICVARIABLES")
    _sub(static, "SVCURRENTCOMPANY", tally_company)

    rdata = _sub(imp, "REQUESTDATA")
    msg = _sub(rdata, "TALLYMESSAGE")
    msg.set("xmlns:UDF", "TallyUDF")

    ledger = _sub(msg, "LEDGER")
    ledger.set("NAME", party_name)
    ledger.set("ACTION", "Create")

    _sub(ledger, "NAME", party_name)
    _sub(ledger, "PARENT", parent_group)

    # GST registration
    if gstin:
        _sub(ledger, "GSTIN", gstin)
        _sub(ledger, "GSTREGISTRATIONTYPE", "Regular")
    else:
        _sub(ledger, "GSTREGISTRATIONTYPE", "Unregistered")

    # State of supply
    if state:
        _sub(ledger, "STATENAME", state)

    # Address block (Tally uses ADDRESS.LIST with multiple ADDRESS children)
    if address_line1 or city:
        addr_list = _sub(ledger, "ADDRESS.LIST")
        if address_line1:
            _sub(addr_list, "ADDRESS", address_line1)
        if city:
            city_pin = city if not pincode else f"{city} - {pincode}"
            _sub(addr_list, "ADDRESS", city_pin)

    # Contact details
    if phone:
        _sub(ledger, "LEDGERPHONE", phone)
    if email:
        _sub(ledger, "EMAIL", email)

    return _pretty(root)


def build_customer_master_xml(party, company) -> str:
    """Build Tally XML to create a Customer master (Sundry Debtors)."""
    tally_company = getattr(company, "tally_company_name", None) or company.name
    name = getattr(party, "tally_ledger_name", None) or party.name
    return _build_party_master_xml(
        party_name=name,
        parent_group="Sundry Debtors",
        gstin=getattr(party, "gstin", None),
        state=getattr(party, "billing_state", None),
        address_line1=getattr(party, "billing_address", None),
        city=getattr(party, "billing_city", None),
        pincode=getattr(party, "billing_pincode", None),
        phone=getattr(party, "phone", None),
        email=getattr(party, "email", None),
        tally_company=tally_company,
    )


def build_supplier_master_xml(party, company) -> str:
    """Build Tally XML to create a Supplier master (Sundry Creditors)."""
    tally_company = getattr(company, "tally_company_name", None) or company.name
    name = getattr(party, "tally_ledger_name", None) or party.name
    return _build_party_master_xml(
        party_name=name,
        parent_group="Sundry Creditors",
        gstin=getattr(party, "gstin", None),
        state=getattr(party, "billing_state", None),
        address_line1=getattr(party, "billing_address", None),
        city=getattr(party, "billing_city", None),
        pincode=getattr(party, "billing_pincode", None),
        phone=getattr(party, "phone", None),
        email=getattr(party, "email", None),
        tally_company=tally_company,
    )


def build_sales_order_xml(
    quotation,
    company,
    party,
    ledgers: TallyLedgerMap | None = None,
) -> str:
    """
    Build Tally XML for a Sales Order voucher from a Quotation.

    Sales Orders in Tally use VCHTYPE="Sales Order" and OBJVIEW="Ordering
    Voucher View". They have INVENTORYENTRIES but NO BILLALLOCATIONS.LIST
    (orders are not financial transactions yet).
    """
    if ledgers is None:
        ledgers = TallyLedgerMap()

    tally_company = getattr(company, "tally_company_name", None) or company.name
    party_name_str = getattr(party, "tally_ledger_name", None) or party.name if party else "Walk-in Customer"
    voucher_date = quotation.quotation_date
    voucher_no = quotation.quotation_no
    grand_total = quotation.grand_total

    narration = f"Sales Order {voucher_no}"

    # Sales Order sign: same as Sales voucher (party debit +, ledger credit -)
    party_sign = 1
    ledger_sign = -1
    stock_sign = -1

    root = ET.Element("ENVELOPE")
    hdr = _sub(root, "HEADER")
    _sub(hdr, "TALLYREQUEST", "Import Data")

    body = _sub(root, "BODY")
    imp = _sub(body, "IMPORTDATA")
    rdesc = _sub(imp, "REQUESTDESC")
    _sub(rdesc, "REPORTNAME", "Vouchers")
    static = _sub(rdesc, "STATICVARIABLES")
    _sub(static, "SVCURRENTCOMPANY", tally_company)

    rdata = _sub(imp, "REQUESTDATA")
    msg = _sub(rdata, "TALLYMESSAGE")
    msg.set("xmlns:UDF", "TallyUDF")

    vch = _sub(msg, "VOUCHER")
    vch.set("VCHTYPE", "Sales Order")
    vch.set("ACTION", "Create")
    vch.set("OBJVIEW", "Ordering Voucher View")

    _sub(vch, "DATE", _fmt_date(voucher_date))
    _sub(vch, "GUID", str(quotation.id))
    _sub(vch, "NARRATION", narration)
    _sub(vch, "VOUCHERTYPENAME", "Sales Order")
    _sub(vch, "VOUCHERNUMBER", voucher_no)
    _sub(vch, "PARTYLEDGERNAME", party_name_str)
    _sub(vch, "BASICBASEPARTYNAME", party_name_str)
    _sub(vch, "PERSISTEDVIEW", "Ordering Voucher View")

    # ── Party ledger entry (no BILLALLOCATIONS for orders) ────────────────
    party_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
    _sub(party_entry, "LEDGERNAME", party_name_str)
    _sub(party_entry, "ISDEEMEDPOSITIVE", "Yes")
    _sub(party_entry, "ISPARTYLEDGER", "Yes")
    _sub(party_entry, "AMOUNT", _fmt_amt(grand_total, party_sign))

    # ── Inventory entries ─────────────────────────────────────────────────
    for item in (quotation.items or []):
        inv_entry = _sub(vch, "INVENTORYENTRIES.LIST")
        item_name = getattr(item, "description", None) or "Item"
        item_unit = getattr(item, "unit", "Nos")
        _sub(inv_entry, "STOCKITEMNAME", item_name)
        _sub(inv_entry, "ISDEEMEDPOSITIVE", "No")
        _sub(inv_entry, "RATE", f"{float(item.rate):.2f}/{item_unit}")
        _sub(inv_entry, "AMOUNT", _fmt_amt(item.amount, stock_sign))
        _sub(inv_entry, "ACTUALQTY", f"{float(item.quantity):.3f} {item_unit}")
        _sub(inv_entry, "BILLEDQTY", f"{float(item.quantity):.3f} {item_unit}")

        if getattr(item, "hsn_code", None):
            _sub(inv_entry, "GSTTAXABILITY", "Taxable")
            _sub(inv_entry, "HSNCODE", item.hsn_code)

        acc = _sub(inv_entry, "ACCOUNTINGALLOCATIONS.LIST")
        _sub(acc, "LEDGERNAME", ledgers.sales)
        _sub(acc, "ISDEEMEDPOSITIVE", "No")
        _sub(acc, "AMOUNT", _fmt_amt(item.amount, stock_sign))

    # ── GST ledger entries (order still carries GST amount for estimates) ─
    cgst = getattr(quotation, "cgst_amount", Decimal("0")) or Decimal("0")
    sgst = getattr(quotation, "sgst_amount", Decimal("0")) or Decimal("0")
    igst = getattr(quotation, "igst_amount", Decimal("0")) or Decimal("0")

    if float(igst) > 0:
        igst_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
        _sub(igst_entry, "LEDGERNAME", ledgers.igst)
        _sub(igst_entry, "ISDEEMEDPOSITIVE", "No")
        _sub(igst_entry, "AMOUNT", _fmt_amt(igst, ledger_sign))
    else:
        if float(cgst) > 0:
            cgst_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
            _sub(cgst_entry, "LEDGERNAME", ledgers.cgst)
            _sub(cgst_entry, "ISDEEMEDPOSITIVE", "No")
            _sub(cgst_entry, "AMOUNT", _fmt_amt(cgst, ledger_sign))
        if float(sgst) > 0:
            sgst_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
            _sub(sgst_entry, "LEDGERNAME", ledgers.sgst)
            _sub(sgst_entry, "ISDEEMEDPOSITIVE", "No")
            _sub(sgst_entry, "AMOUNT", _fmt_amt(sgst, ledger_sign))

    round_off = getattr(quotation, "round_off", Decimal("0")) or Decimal("0")
    if abs(float(round_off)) > 0.001:
        ro_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
        _sub(ro_entry, "LEDGERNAME", ledgers.roundoff)
        _sub(ro_entry, "ISDEEMEDPOSITIVE", "No")
        _sub(ro_entry, "AMOUNT", _fmt_amt(round_off, ledger_sign))

    return _pretty(root)


def build_purchase_order_xml(
    po,
    po_items: list,
    tally_company: str,
    ledgers: TallyLedgerMap | None = None,
) -> str:
    """
    Build Tally XML for a Purchase Order voucher from an InventoryPurchaseOrder.

    Purchase Orders are simple: VCHTYPE="Purchase Order", supplier as party,
    line items with qty/price only. No GST/discount/freight — these are
    unpriced store orders, not financial purchase invoices.

    Balance: party amount = sum of all item amounts (with sign flip for purchase).
    """
    if ledgers is None:
        ledgers = TallyLedgerMap()

    supplier_name = po.supplier_name or "Unknown Supplier"
    voucher_date = getattr(po, "created_at", _date.today())
    voucher_no = po.po_no

    # Calculate total from items
    total = sum(
        float(item.quantity_ordered or 0) * float(item.unit_price or 0)
        for item in po_items
    )
    grand_total = Decimal(str(total))

    narration = f"Purchase Order {voucher_no}"

    # Purchase sign: party credit (-), purchase ledger debit (+)
    party_sign = -1
    ledger_sign = 1

    root = ET.Element("ENVELOPE")
    hdr = _sub(root, "HEADER")
    _sub(hdr, "TALLYREQUEST", "Import Data")

    body = _sub(root, "BODY")
    imp = _sub(body, "IMPORTDATA")
    rdesc = _sub(imp, "REQUESTDESC")
    _sub(rdesc, "REPORTNAME", "Vouchers")
    static = _sub(rdesc, "STATICVARIABLES")
    _sub(static, "SVCURRENTCOMPANY", tally_company)

    rdata = _sub(imp, "REQUESTDATA")
    msg = _sub(rdata, "TALLYMESSAGE")
    msg.set("xmlns:UDF", "TallyUDF")

    vch = _sub(msg, "VOUCHER")
    vch.set("VCHTYPE", "Purchase Order")
    vch.set("ACTION", "Create")
    vch.set("OBJVIEW", "Ordering Voucher View")

    _sub(vch, "DATE", _fmt_date(voucher_date))
    _sub(vch, "GUID", str(po.id))
    _sub(vch, "NARRATION", narration)
    _sub(vch, "VOUCHERTYPENAME", "Purchase Order")
    _sub(vch, "VOUCHERNUMBER", voucher_no)
    _sub(vch, "PARTYLEDGERNAME", supplier_name)
    _sub(vch, "BASICBASEPARTYNAME", supplier_name)
    _sub(vch, "PERSISTEDVIEW", "Ordering Voucher View")

    # ── Party (supplier) ledger entry ─────────────────────────────────────
    party_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
    _sub(party_entry, "LEDGERNAME", supplier_name)
    _sub(party_entry, "ISDEEMEDPOSITIVE", "No")
    _sub(party_entry, "ISPARTYLEDGER", "Yes")
    _sub(party_entry, "AMOUNT", _fmt_amt(grand_total, party_sign))

    # ── Inventory entries (one per PO line item) ──────────────────────────
    for item in po_items:
        qty = float(item.quantity_ordered or 0)
        price = float(item.unit_price or 0)
        line_amount = Decimal(str(qty * price))
        item_unit = item.unit or "Nos"

        inv_entry = _sub(vch, "INVENTORYENTRIES.LIST")
        _sub(inv_entry, "STOCKITEMNAME", item.item_name)
        _sub(inv_entry, "ISDEEMEDPOSITIVE", "Yes")
        _sub(inv_entry, "RATE", f"{price:.2f}/{item_unit}")
        _sub(inv_entry, "AMOUNT", _fmt_amt(line_amount, ledger_sign))
        _sub(inv_entry, "ACTUALQTY", f"{qty:.3f} {item_unit}")
        _sub(inv_entry, "BILLEDQTY", f"{qty:.3f} {item_unit}")

        acc = _sub(inv_entry, "ACCOUNTINGALLOCATIONS.LIST")
        _sub(acc, "LEDGERNAME", ledgers.purchase)
        _sub(acc, "ISDEEMEDPOSITIVE", "Yes")
        _sub(acc, "AMOUNT", _fmt_amt(line_amount, ledger_sign))

    return _pretty(root)


def build_sales_xml(
    invoice,
    company,
    party,
    ledgers: TallyLedgerMap | None = None,
    narration_opts: NarrationOptions | None = None,
) -> str:
    """Build Tally XML for a Sales voucher."""
    if ledgers is None:
        ledgers = TallyLedgerMap()
    if narration_opts is None:
        narration_opts = NarrationOptions()

    narration = _build_narration(
        vch_type="Sales",
        invoice_no=invoice.invoice_no or "Draft",
        opts=narration_opts,
        vehicle_no=getattr(invoice, "vehicle_no", None),
        token_no=getattr(invoice, "token_no", None),
        net_weight_kg=getattr(invoice, "net_weight", None),
    )

    return _build_voucher_xml(
        vch_type="Sales",
        voucher_no=invoice.invoice_no or "",
        voucher_date=invoice.invoice_date,
        due_date=getattr(invoice, "due_date", None),
        payment_terms_days=getattr(party, "payment_terms_days", 0) or 0,
        narration=narration,
        party_name=_party_name(invoice, party),
        party_gstin=_party_gstin(party),
        place_of_supply=_place_of_supply(party),
        tally_company=_tally_company(invoice, company),
        items=_extract_items(invoice),
        taxable_amount=invoice.taxable_amount or Decimal("0"),
        discount_amount=invoice.discount_amount or Decimal("0"),
        freight=invoice.freight or Decimal("0"),
        cgst_amount=invoice.cgst_amount or Decimal("0"),
        sgst_amount=invoice.sgst_amount or Decimal("0"),
        igst_amount=invoice.igst_amount or Decimal("0"),
        tcs_amount=invoice.tcs_amount or Decimal("0"),
        round_off=invoice.round_off or Decimal("0"),
        grand_total=invoice.grand_total,
        ledgers=ledgers,
        guid=str(invoice.id),
    )


def build_purchase_xml(
    invoice,
    company,
    party,
    ledgers: TallyLedgerMap | None = None,
    narration_opts: NarrationOptions | None = None,
) -> str:
    """Build Tally XML for a Purchase voucher."""
    if ledgers is None:
        ledgers = TallyLedgerMap()
    if narration_opts is None:
        narration_opts = NarrationOptions()

    narration = _build_narration(
        vch_type="Purchase",
        invoice_no=invoice.invoice_no or "Draft",
        opts=narration_opts,
        vehicle_no=getattr(invoice, "vehicle_no", None),
        token_no=getattr(invoice, "token_no", None),
        net_weight_kg=getattr(invoice, "net_weight", None),
    )

    return _build_voucher_xml(
        vch_type="Purchase",
        voucher_no=invoice.invoice_no or "",
        voucher_date=invoice.invoice_date,
        due_date=getattr(invoice, "due_date", None),
        payment_terms_days=getattr(party, "payment_terms_days", 0) or 0,
        narration=narration,
        party_name=_party_name(invoice, party),
        party_gstin=_party_gstin(party),
        place_of_supply=_place_of_supply(party),
        tally_company=_tally_company(invoice, company),
        items=_extract_items(invoice),
        taxable_amount=invoice.taxable_amount or Decimal("0"),
        discount_amount=invoice.discount_amount or Decimal("0"),
        freight=invoice.freight or Decimal("0"),
        cgst_amount=invoice.cgst_amount or Decimal("0"),
        sgst_amount=invoice.sgst_amount or Decimal("0"),
        igst_amount=invoice.igst_amount or Decimal("0"),
        tcs_amount=invoice.tcs_amount or Decimal("0"),
        round_off=invoice.round_off or Decimal("0"),
        grand_total=invoice.grand_total,
        ledgers=ledgers,
        guid=str(invoice.id),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────

def _party_name(invoice, party) -> str:
    if party and (getattr(party, "tally_ledger_name", None) or party.name):
        return party.tally_ledger_name or party.name
    return invoice.customer_name or "Walk-in Customer"


def _party_gstin(party) -> str | None:
    if party and getattr(party, "gstin", None):
        return party.gstin
    return None


def _place_of_supply(party) -> str | None:
    """Return state name for Place of Supply field in Tally."""
    if party and getattr(party, "billing_state", None):
        return party.billing_state
    return None


def _tally_company(invoice, company) -> str:
    return getattr(company, "tally_company_name", None) or company.name


def _extract_items(invoice) -> list[dict]:
    items = []
    for it in (invoice.items or []):
        items.append({
            "name": it.description or getattr(it, "_product_name", "Item"),
            "unit": it.unit or "Nos",
            "qty": it.quantity,
            "rate": it.rate,
            "amount": it.amount,
            "hsn": it.hsn_code or "",
            "gst_rate": getattr(it, "gst_rate", Decimal("0")),
        })
    return items

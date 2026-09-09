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
from decimal import Decimal, ROUND_HALF_UP

from app.integrations.tally import units as tally_units
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


def _current_company(rdesc, tally_company) -> None:
    """Name the target company on a REQUESTDESC — only when one is configured.

    With no name, STATICVARIABLES is omitted entirely so Tally imports into the
    company that is currently open. Sending a name Tally does not have open fails
    the whole import before a single voucher is read.
    """
    name = (tally_company or "").strip()
    if name:
        _sub(_sub(rdesc, "STATICVARIABLES"), "SVCURRENTCOMPANY", name)


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
    sign_basis: str | None = None,        # "sales" | "purchase" — Dr/Cr direction; defaults from vch_type
    item_ledger_kind: str | None = None,  # "sales" | "purchase" — which income/expense ledger goods post to
    bill_type: str = "New Ref",           # "New Ref" (invoice) | "Agst Ref" (credit/debit note vs original)
    bill_ref_name: str | None = None,     # original invoice no, used when bill_type="Agst Ref"
    accounting_only: bool = False,        # legacy/no-GST mode: party + income ledger only, no stock/GST
    godown: str | None = None,            # Tally godown for stock lines (must exist in Tally)
    batch_name: str | None = None,        # only for items with batching enabled
) -> str:
    # Sign + income-ledger selection are decoupled from the voucher label so a
    # Credit Note (which reverses a sale) can carry VCHTYPE="Credit Note", post
    # to the "Sales" ledger, yet use purchase-direction Dr/Cr signs.
    effective_basis = sign_basis or ("sales" if vch_type == "Sales" else "purchase")
    is_sale = effective_basis == "sales"

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
    _current_company(rdesc, tally_company)

    rdata = _sub(imp, "REQUESTDATA")
    msg = _sub(rdata, "TALLYMESSAGE")
    msg.set("xmlns:UDF", "TallyUDF")

    _view = "Accounting Voucher View" if accounting_only else "Invoice Voucher View"
    vch = _sub(msg, "VOUCHER")
    vch.set("VCHTYPE", vch_type)
    vch.set("ACTION", "Create")
    vch.set("OBJVIEW", _view)

    _sub(vch, "DATE", _fmt_date(voucher_date))
    _sub(vch, "GUID", guid or str(_uuid.uuid4()))
    _sub(vch, "NARRATION", narration)
    _sub(vch, "VOUCHERTYPENAME", vch_type)
    _sub(vch, "VOUCHERNUMBER", voucher_no)
    _sub(vch, "PARTYLEDGERNAME", party_name)
    # BASICBASEPARTYNAME + PERSISTEDVIEW are invoice-view hints; legacy Tally (9)
    # opens the voucher interactively (hangs) when they appear on an accounting
    # voucher, so we omit them in accounting-only mode.
    if not accounting_only:
        _sub(vch, "BASICBASEPARTYNAME", party_name)
        _sub(vch, "PERSISTEDVIEW", _view)

    # Place of supply (state name) for GST — omitted in accounting-only/no-GST mode
    if place_of_supply and not accounting_only:
        _sub(vch, "PLACEOFSUPPLY", place_of_supply)

    # ── Party ledger entry ──────────────────────────────────────────────────
    party_entry = _sub(vch, "ALLLEDGERENTRIES.LIST")
    _sub(party_entry, "LEDGERNAME", party_name)
    _sub(party_entry, "ISDEEMEDPOSITIVE", "Yes" if is_sale else "No")
    _sub(party_entry, "ISPARTYLEDGER", "Yes")
    _sub(party_entry, "AMOUNT", _fmt_amt(grand_total, party_sign))

    # Buyer GSTIN on the party entry (used by Tally for GSTR reports) — omitted in no-GST mode
    if party_gstin and not accounting_only:
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
    _sub(bill_alloc, "NAME", (bill_ref_name if (bill_type != "New Ref" and bill_ref_name)
                              else (voucher_no or str(_uuid.uuid4())[:8])))
    _sub(bill_alloc, "BILLTYPE", bill_type)
    _sub(bill_alloc, "AMOUNT", _fmt_amt(grand_total, party_sign))
    if credit_days > 0 and bill_type == "New Ref" and not accounting_only:
        _sub(bill_alloc, "CREDITPERIOD", f"{credit_days} Days")

    # ── Accounting mode (no stock item / no "Invoice Voucher View") ─────────
    # Post the income/expense ledger + GST/freight/TCS/round-off as plain ledger
    # lines — NO inventory entry. This is the form that legacy Tally (e.g. Tally 9)
    # AND TallyPrime companies that don't accept inventory-in-vouchers ("Integrate
    # Accounts & Inventory" off) take cleanly, while STILL carrying GST. The income
    # ledger is posted at the net value (grand_total minus the add-on ledgers) so
    # the voucher balances by design; a non-GST invoice has zero add-ons → a single
    # income line, identical to the old behaviour (legacy-safe).
    _dpos = "No" if is_sale else "Yes"
    if accounting_only:
        income_ledger = ledgers.sales if (item_ledger_kind or effective_basis) == "sales" else ledgers.purchase
        _gt = grand_total or Decimal("0")
        _addons = ((cgst_amount or 0) + (sgst_amount or 0) + (igst_amount or 0)
                   + (freight or 0) + (tcs_amount or 0) + (round_off or 0))
        inc = _sub(vch, "ALLLEDGERENTRIES.LIST")
        _sub(inc, "LEDGERNAME", income_ledger)
        _sub(inc, "ISDEEMEDPOSITIVE", _dpos)
        _sub(inc, "AMOUNT", _fmt_amt(_gt - _addons, ledger_sign))
        if float(freight or 0) > 0:
            fe = _sub(vch, "ALLLEDGERENTRIES.LIST")
            _sub(fe, "LEDGERNAME", ledgers.freight); _sub(fe, "ISDEEMEDPOSITIVE", _dpos)
            _sub(fe, "AMOUNT", _fmt_amt(freight, ledger_sign))
        if float(igst_amount or 0) > 0:
            ge = _sub(vch, "ALLLEDGERENTRIES.LIST")
            _sub(ge, "LEDGERNAME", ledgers.igst); _sub(ge, "ISDEEMEDPOSITIVE", _dpos)
            _sub(ge, "AMOUNT", _fmt_amt(igst_amount, ledger_sign))
        else:
            if float(cgst_amount or 0) > 0:
                ce = _sub(vch, "ALLLEDGERENTRIES.LIST")
                _sub(ce, "LEDGERNAME", ledgers.cgst); _sub(ce, "ISDEEMEDPOSITIVE", _dpos)
                _sub(ce, "AMOUNT", _fmt_amt(cgst_amount, ledger_sign))
            if float(sgst_amount or 0) > 0:
                se = _sub(vch, "ALLLEDGERENTRIES.LIST")
                _sub(se, "LEDGERNAME", ledgers.sgst); _sub(se, "ISDEEMEDPOSITIVE", _dpos)
                _sub(se, "AMOUNT", _fmt_amt(sgst_amount, ledger_sign))
        if float(tcs_amount or 0) > 0:
            te = _sub(vch, "ALLLEDGERENTRIES.LIST")
            _sub(te, "LEDGERNAME", ledgers.tcs); _sub(te, "ISDEEMEDPOSITIVE", _dpos)
            _sub(te, "AMOUNT", _fmt_amt(tcs_amount, ledger_sign))
        if abs(float(round_off or 0)) > 0.001:
            roe = _sub(vch, "ALLLEDGERENTRIES.LIST")
            _sub(roe, "LEDGERNAME", ledgers.roundoff); _sub(roe, "ISDEEMEDPOSITIVE", _dpos)
            _sub(roe, "AMOUNT", _fmt_amt(round_off, ledger_sign))
        return _pretty(root)

    # ── Inventory entries (one per line item) ───────────────────────────────
    item_ledger = ledgers.sales if (item_ledger_kind or effective_basis) == "sales" else ledgers.purchase
    for item in items:
        inv_entry = _sub(vch, "INVENTORYENTRIES.LIST")
        _sub(inv_entry, "STOCKITEMNAME", item["name"])
        _sub(inv_entry, "ISDEEMEDPOSITIVE", "No" if is_sale else "Yes")
        _sub(inv_entry, "RATE", f"{_fmt_rate(item['rate'])}/{item['unit']}")
        _sub(inv_entry, "AMOUNT", _fmt_amt(item["amount"], stock_sign))
        _sub(inv_entry, "ACTUALQTY", f"{float(item['qty']):.3f} {item['unit']}")
        _sub(inv_entry, "BILLEDQTY", f"{float(item['qty']):.3f} {item['unit']}")

        # HSN + GST rate for GSTR-1 HSN summary
        if item.get("hsn"):
            _sub(inv_entry, "GSTTAXABILITY", "Taxable")
            _sub(inv_entry, "HSNCODE", item["hsn"])
        if item.get("gst_rate") and float(item["gst_rate"]) > 0:
            _sub(inv_entry, "GSTRATE", f"{float(item['gst_rate']):.2f}")

        # Godown allocation. The godown must exist in Tally under this exact
        # name or the line is rejected. A BATCHNAME is only valid on an item with
        # batching enabled, so it is opt-in per tenant.
        batch = _sub(inv_entry, "BATCHALLOCATIONS.LIST")
        _sub(batch, "GODOWNNAME", godown or "Main Location")
        if batch_name:
            _sub(batch, "BATCHNAME", batch_name)
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
    _current_company(rdesc, tally_company)

    rdata = _sub(imp, "REQUESTDATA")
    msg = _sub(rdata, "TALLYMESSAGE")
    msg.set("xmlns:UDF", "TallyUDF")

    ledger = _sub(msg, "LEDGER")
    ledger.set("NAME", party_name)
    ledger.set("ACTION", "Create")

    _sub(ledger, "NAME", party_name)
    _sub(ledger, "PARENT", parent_group)
    # Bill-wise tracking. Sale/purchase vouchers carry BILLALLOCATIONS ("New Ref")
    # and credit/debit notes settle "Agst Ref" the original invoice — Tally only
    # honours those on a ledger with bill-wise details on, so without this the
    # GSTR-1 CDNR link between a note and its invoice is silently lost.
    _sub(ledger, "ISBILLWISEON", "Yes")

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
    tally_company = _tally_company_name(company)
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
    tally_company = _tally_company_name(company)
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


def build_ledger_master_xml(name: str, parent: str, company, gst_duty_head: str | None = None) -> str:
    """Build Tally XML for a GL ledger (Sales/Purchase/CGST/SGST/IGST/Round Off…).

    ``parent`` = Tally group (e.g. "Sales Accounts", "Duties & Taxes").
    ``gst_duty_head`` = "Central Tax" / "State Tax" / "Integrated Tax" for GST
    ledgers (sets TAXTYPE=GST so TallyPrime treats them as tax ledgers).
    """
    tally_company = _tally_company_name(company)
    root = ET.Element("ENVELOPE")
    _sub(_sub(root, "HEADER"), "TALLYREQUEST", "Import Data")
    imp = _sub(_sub(root, "BODY"), "IMPORTDATA")
    rdesc = _sub(imp, "REQUESTDESC")
    _sub(rdesc, "REPORTNAME", "All Masters")
    _current_company(rdesc, tally_company)
    msg = _sub(_sub(imp, "REQUESTDATA"), "TALLYMESSAGE")
    msg.set("xmlns:UDF", "TallyUDF")
    led = _sub(msg, "LEDGER")
    led.set("NAME", name)
    led.set("ACTION", "Create")
    _sub(led, "NAME", name)
    _sub(led, "PARENT", parent)
    if gst_duty_head:
        _sub(led, "TAXTYPE", "GST")
        _sub(led, "GSTDUTYHEAD", gst_duty_head)
    return _pretty(root)


WALKIN_LEDGER = "Walk-in Customer"


def gl_ledger_specs(ledgers: "TallyLedgerMap",
                    walkin_ledger: str = WALKIN_LEDGER) -> list[tuple[str, str, str | None]]:
    """The GL ledgers Tally needs for vouchers → (name, parent_group, gst_duty_head).

    Includes the walk-in party ledger: a B2C sale with no party record posts to
    ``invoice.customer_name or "Walk-in Customer"``, and nothing else ever creates
    that ledger, so those vouchers failed "Ledger does not exist". A named walk-in
    customer still needs its own ledger — this covers the unnamed default.
    """
    return [
        (walkin_ledger, "Sundry Debtors", None),
        (ledgers.sales,    "Sales Accounts",    None),
        (ledgers.purchase, "Purchase Accounts", None),
        (ledgers.cgst,     "Duties & Taxes",    "Central Tax"),
        (ledgers.sgst,     "Duties & Taxes",    "State Tax"),
        (ledgers.igst,     "Duties & Taxes",    "Integrated Tax"),
        (ledgers.roundoff, "Indirect Expenses", None),
        (ledgers.freight,  "Indirect Expenses", None),
        (ledgers.discount, "Indirect Expenses", None),
        (ledgers.tcs,      "Duties & Taxes",    None),
    ]


def build_unit_xml(symbol: str, company, decimals: int = 3) -> str:
    """Build Tally XML to create a simple Unit of Measure (e.g. MT, Nos, Qtl)."""
    tally_company = _tally_company_name(company)
    root = ET.Element("ENVELOPE")
    _sub(_sub(root, "HEADER"), "TALLYREQUEST", "Import Data")
    imp = _sub(_sub(root, "BODY"), "IMPORTDATA")
    rdesc = _sub(imp, "REQUESTDESC")
    _sub(rdesc, "REPORTNAME", "All Masters")
    _current_company(rdesc, tally_company)
    msg = _sub(_sub(imp, "REQUESTDATA"), "TALLYMESSAGE")
    msg.set("xmlns:UDF", "TallyUDF")
    unit = _sub(msg, "UNIT")
    unit.set("NAME", symbol)
    unit.set("ACTION", "Create")
    _sub(unit, "NAME", symbol)
    _sub(unit, "ISSIMPLEUNIT", "Yes")
    _sub(unit, "DECIMALPLACES", str(decimals))
    return _pretty(root)


def build_stock_item_xml(product, company, volume_unit: str = "CUM",
                         opening_qty=None) -> str:
    """Build Tally XML to create a Stock Item master.

    Minimal by default (name + base unit + HSN) so it imports on legacy Tally too.
    When the product carries a GST rate, the item is **GST-classified** (HSN +
    taxability + CGST/SGST/IGST rate split) — TallyPrime validates GST vouchers
    against the item's own rate, so without this a full GST invoice referencing the
    item is rejected with EXCEPTIONS=1. The base unit must already exist in Tally
    (push build_unit_xml first when seeding a fresh company).

    An **alternate unit** is added when the product has a ``bulk_density``: the
    same material is routinely billed by volume as well as by weight (live data:
    ~48% of sss's sale lines are CBM/CUM against MT items), and Tally rejects a
    quantity in a unit the item does not know. One alternate is all Tally allows,
    so it is the tenant's canonical volume unit for a weight item and MT for a
    volume item; ``tally_units.convert_line`` then maps every billed unit of that
    dimension onto it exactly. Both units must exist in Tally first.
    """
    tally_company = _tally_company_name(company)
    name = getattr(product, "name", None) or "Item"
    unit = getattr(product, "unit", None) or "Nos"
    _hsn = (getattr(product, "hsn_code", None) or "").strip()
    try:
        _gst_rate = float(getattr(product, "gst_rate", None) or 0)
    except (TypeError, ValueError):
        _gst_rate = 0.0
    root = ET.Element("ENVELOPE")
    _sub(_sub(root, "HEADER"), "TALLYREQUEST", "Import Data")
    imp = _sub(_sub(root, "BODY"), "IMPORTDATA")
    rdesc = _sub(imp, "REQUESTDESC")
    _sub(rdesc, "REPORTNAME", "All Masters")
    _current_company(rdesc, tally_company)
    msg = _sub(_sub(imp, "REQUESTDATA"), "TALLYMESSAGE")
    msg.set("xmlns:UDF", "TallyUDF")
    item = _sub(msg, "STOCKITEM")
    item.set("NAME", name)
    item.set("ACTION", "Create")
    _sub(item, "NAME", name)
    _sub(item, "BASEUNITS", unit)
    _alt = tally_units.alternate_unit(product, volume_unit)
    if _alt is not None:
        # 1 <alt> = <conversion> <base> — lets Tally accept a quantity billed in
        # the other dimension and show the stock in both.
        _alt_sym, _conv = _alt
        _sub(item, "ADDITIONALUNITS", _alt_sym)
        _sub(item, "CONVERSION", tally_units.format_conversion(_conv))
        _sub(item, "DENOMINATOR", "1")
    if opening_qty is not None and float(opening_qty) > 0:
        # Only the deliberate one-time seed passes this. An ordinary item re-sync
        # must never carry it, or it would reset a balance Tally has since moved.
        _sub(item, "OPENINGBALANCE", f"{float(opening_qty):.3f} {unit}")
    if _hsn:
        _sub(item, "HSNCODE", _hsn)          # for GSTR-1 HSN summary (harmless in no-GST)
    if _gst_rate > 0:
        # GST-classify the item so TallyPrime can validate GST vouchers using it.
        _sub(item, "GSTAPPLICABLE", "Applicable")
        _sub(item, "GSTTYPEOFSUPPLY", "Goods")
        gd = _sub(item, "GSTDETAILS.LIST")
        _sub(gd, "APPLICABLEFROM", "20170701")     # GST rollout — a safe floor date
        _sub(gd, "CALCULATIONTYPE", "On Value")
        _sub(gd, "TAXABILITY", "Taxable")
        if _hsn:
            _sub(gd, "HSNCODE", _hsn)
        sw = _sub(gd, "STATEWISEDETAILS.LIST")
        _sub(sw, "STATENAME", "Any")
        half = _gst_rate / 2.0
        for head, rate in (("CGST", half), ("SGST/UTGST", half), ("IGST", _gst_rate)):
            rd = _sub(sw, "RATEDETAILS.LIST")
            _sub(rd, "GSTRATEDUTYHEAD", head)
            _sub(rd, "GSTRATE", f"{rate:g}")
    return _pretty(root)


def build_stock_journal_xml(
    cycle,
    company,
    consumed: list[dict],      # [{name, unit, qty}] raw material used
    produced: list[dict],      # [{name, unit, qty}] finished goods made
    godown: str | None = None,
    batch_name: str | None = None,
) -> str:
    """Build a Tally **Stock Journal** for one production cycle.

    A crusher's finished goods are MANUFACTURED, not bought — so a sales voucher
    takes stock out of Tally while nothing ever puts it in, and Tally's inventory
    runs permanently negative. This is the missing inflow: raw material out,
    finished goods in, as one voucher.

    Quantity only. Weighbridge holds no cost for produced goods, so no value is
    asserted — Tally values the transfer by its own costing method rather than a
    number we would have to invent.
    """
    tally_company = _tally_company_name(company)
    root = ET.Element("ENVELOPE")
    _sub(_sub(root, "HEADER"), "TALLYREQUEST", "Import Data")
    imp = _sub(_sub(root, "BODY"), "IMPORTDATA")
    rdesc = _sub(imp, "REQUESTDESC")
    _sub(rdesc, "REPORTNAME", "Vouchers")
    _current_company(rdesc, tally_company)

    msg = _sub(_sub(imp, "REQUESTDATA"), "TALLYMESSAGE")
    msg.set("xmlns:UDF", "TallyUDF")
    vch = _sub(msg, "VOUCHER")
    vch.set("VCHTYPE", "Stock Journal")
    vch.set("ACTION", "Create")
    vch.set("OBJVIEW", "Consumption Voucher View")

    _sub(vch, "DATE", _fmt_date(cycle.cycle_date))
    # Same GUID rule as invoices: re-sending a corrected cycle ALTERs the voucher
    # instead of adding a second one (needs Tally's overwrite-same-GUID setting).
    _sub(vch, "GUID", str(cycle.id))
    _sub(vch, "VOUCHERTYPENAME", "Stock Journal")
    _sub(vch, "VOUCHERNUMBER", f"CYC/{cycle.cycle_date}/{getattr(cycle, 'cycle_no', '')}".rstrip("/"))
    _sub(vch, "NARRATION", f"Production cycle {cycle.cycle_date}")

    def _leg(tag: str, row: dict) -> None:
        e = _sub(vch, tag)
        _sub(e, "STOCKITEMNAME", row["name"])
        qty = f"{float(row['qty']):.3f} {row['unit']}"
        _sub(e, "ACTUALQTY", qty)
        _sub(e, "BILLEDQTY", qty)
        b = _sub(e, "BATCHALLOCATIONS.LIST")
        _sub(b, "GODOWNNAME", godown or "Main Location")
        if batch_name:
            _sub(b, "BATCHNAME", batch_name)
        _sub(b, "ACTUALQTY", qty)
        _sub(b, "BILLEDQTY", qty)

    for row in consumed:
        if float(row.get("qty") or 0) > 0:
            _leg("INVENTORYENTRIESOUT.LIST", row)
    for row in produced:
        if float(row.get("qty") or 0) > 0:
            _leg("INVENTORYENTRIESIN.LIST", row)

    return _pretty(root)


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

    tally_company = _tally_company_name(company)
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
    _current_company(rdesc, tally_company)

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
    _current_company(rdesc, tally_company)

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


def voucher_guid(invoice) -> str:
    """The GUID Tally files this invoice's voucher under.

    A revision is a NEW invoice row in the app, but commercially it is the SAME
    document as the version it supersedes — so it must reach Tally as an ALTER
    of that voucher, never as a second voucher beside it. Keying the GUID on the
    ROOT of the revision chain (``original_invoice_id`` — every revision carries
    it and it always points at v1) gives every version one GUID; with Tally's
    "Overwrite voucher when a voucher with same GUID exists = Yes" the newest
    finalised revision replaces the voucher in place, voucher number included.

    A credit/debit note is a separate document (it links to its invoice through
    ``reference_invoice_id``, never ``original_invoice_id``) so it keeps its own
    id. A plain, never-revised invoice is unchanged: ``original_invoice_id`` is
    NULL and the GUID is its own id, exactly as before.
    """
    root = getattr(invoice, "original_invoice_id", None)
    return str(root or invoice.id)


def build_sales_xml(
    invoice,
    company,
    party,
    ledgers: TallyLedgerMap | None = None,
    narration_opts: NarrationOptions | None = None,
    accounting_only: bool = False,
    godown: str | None = None,
    batch_name: str | None = None,
    volume_unit: str = "CUM",
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
        accounting_only=accounting_only,
        godown=godown,
        batch_name=batch_name,
        voucher_no=invoice.invoice_no or "",
        voucher_date=invoice.invoice_date,
        due_date=getattr(invoice, "due_date", None),
        payment_terms_days=getattr(party, "payment_terms_days", 0) or 0,
        narration=narration,
        party_name=_party_name(invoice, party),
        party_gstin=_party_gstin(party),
        place_of_supply=_place_of_supply(party),
        tally_company=_tally_company(invoice, company),
        items=_extract_items(invoice, volume_unit),
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
        guid=voucher_guid(invoice),
    )


def build_purchase_xml(
    invoice,
    company,
    party,
    ledgers: TallyLedgerMap | None = None,
    narration_opts: NarrationOptions | None = None,
    accounting_only: bool = False,
    godown: str | None = None,
    batch_name: str | None = None,
    volume_unit: str = "CUM",
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
        accounting_only=accounting_only,
        godown=godown,
        batch_name=batch_name,
        voucher_no=invoice.invoice_no or "",
        voucher_date=invoice.invoice_date,
        due_date=getattr(invoice, "due_date", None),
        payment_terms_days=getattr(party, "payment_terms_days", 0) or 0,
        narration=narration,
        party_name=_party_name(invoice, party),
        party_gstin=_party_gstin(party),
        place_of_supply=_place_of_supply(party),
        tally_company=_tally_company(invoice, company),
        items=_extract_items(invoice, volume_unit),
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
        guid=voucher_guid(invoice),
    )


def _note_narration(vch_type, invoice, narration_opts, ref_no):
    narration = _build_narration(
        vch_type=vch_type,
        invoice_no=invoice.invoice_no or "Draft",
        opts=narration_opts,
        vehicle_no=getattr(invoice, "vehicle_no", None),
        token_no=getattr(invoice, "token_no", None),
        net_weight_kg=getattr(invoice, "net_weight", None),
    )
    reason = getattr(invoice, "note_reason", None)
    if ref_no and reason:
        return f"{narration} | vs {ref_no}: {reason}"
    if ref_no:
        return f"{narration} | vs {ref_no}"
    return narration


def build_credit_note_xml(
    invoice,
    company,
    party,
    ledgers: TallyLedgerMap | None = None,
    narration_opts: NarrationOptions | None = None,
    reference_invoice_no: str | None = None,
    accounting_only: bool = False,
    godown: str | None = None,
    batch_name: str | None = None,
    volume_unit: str = "CUM",
) -> str:
    """Build Tally XML for a Credit Note (seller-issued, against a SALE invoice).

    A credit note reverses a sale: the customer is CREDITED (receivable down) and
    Sales + output-GST are DEBITED. Hence purchase-direction signs, but the goods
    still post to the "Sales" income ledger, and the bill settles "Agst Ref" the
    original invoice so GSTR-1 CDNR links correctly.
    """
    ledgers = ledgers or TallyLedgerMap()
    narration_opts = narration_opts or NarrationOptions()
    ref_no = reference_invoice_no or invoice.invoice_no or ""
    return _build_voucher_xml(
        vch_type="Credit Note",
        accounting_only=accounting_only,
        godown=godown,
        batch_name=batch_name,
        sign_basis="purchase",
        item_ledger_kind="sales",
        bill_type="Agst Ref",
        bill_ref_name=ref_no,
        voucher_no=invoice.invoice_no or "",
        voucher_date=invoice.invoice_date,
        narration=_note_narration("Credit Note", invoice, narration_opts, ref_no),
        party_name=_party_name(invoice, party),
        party_gstin=_party_gstin(party),
        place_of_supply=_place_of_supply(party),
        tally_company=_tally_company(invoice, company),
        items=_extract_items(invoice, volume_unit),
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
        guid=voucher_guid(invoice),
    )


def build_debit_note_xml(
    invoice,
    company,
    party,
    ledgers: TallyLedgerMap | None = None,
    narration_opts: NarrationOptions | None = None,
    reference_invoice_no: str | None = None,
    accounting_only: bool = False,
    godown: str | None = None,
    batch_name: str | None = None,
    volume_unit: str = "CUM",
) -> str:
    """Build Tally XML for a Debit Note (seller-issued supplementary, against a
    SALE invoice). A debit note increases the sale: the customer is DEBITED
    (receivable up) and Sales + output-GST are CREDITED — same direction as a
    sale, settled "Agst Ref" the original invoice.
    """
    ledgers = ledgers or TallyLedgerMap()
    narration_opts = narration_opts or NarrationOptions()
    ref_no = reference_invoice_no or invoice.invoice_no or ""
    return _build_voucher_xml(
        vch_type="Debit Note",
        accounting_only=accounting_only,
        godown=godown,
        batch_name=batch_name,
        sign_basis="sales",
        item_ledger_kind="sales",
        bill_type="Agst Ref",
        bill_ref_name=ref_no,
        voucher_no=invoice.invoice_no or "",
        voucher_date=invoice.invoice_date,
        narration=_note_narration("Debit Note", invoice, narration_opts, ref_no),
        party_name=_party_name(invoice, party),
        party_gstin=_party_gstin(party),
        place_of_supply=_place_of_supply(party),
        tally_company=_tally_company(invoice, company),
        items=_extract_items(invoice, volume_unit),
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
        guid=voucher_guid(invoice),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────

def _party_name(invoice, party) -> str:
    if party and (getattr(party, "tally_ledger_name", None) or party.name):
        return party.tally_ledger_name or party.name
    return invoice.customer_name or WALKIN_LEDGER


def _party_gstin(party) -> str | None:
    if party and getattr(party, "gstin", None):
        return party.gstin
    return None


def _place_of_supply(party) -> str | None:
    """Return state name for Place of Supply field in Tally."""
    if party and getattr(party, "billing_state", None):
        return party.billing_state
    return None


def _tally_company_name(company) -> str:
    """The company name Tally should file this document under — or "" for none.

    Deliberately does NOT fall back to the app's own ``company.name``. Tally rejects
    the ENTIRE import with "Could not set 'SVCurrentCompany'" when the name is not a
    company it has open, and the client's Tally company is very rarely spelled the
    way the app's company is. Blank means "whichever company is open in Tally",
    which is what a single-company site wants and is far likelier to succeed than a
    guess (see _current_company).

    The value is stamped onto the Company instance by ``routers.tally._get_company``
    from ``tally_config.tally_company_name`` — the column lives on TallyConfig, not
    on Company, so reading it here without that stamp silently yields nothing.
    """
    return (getattr(company, "tally_company_name", None) or "").strip()


def _tally_company(invoice, company) -> str:
    return _tally_company_name(company)


def _fmt_rate(rate) -> str:
    """Rate for a voucher line: 2 dp as always, more only when the extra digits
    are real. A converted line's rate is derived from the amount and can need 4
    dp for qty x rate to still equal it; an unconverted line prints exactly as
    it always has."""
    d = Decimal(str(rate or 0))
    q2 = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if d == q2:
        return f"{q2:.2f}"
    return f"{d.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP):.4f}"


def _extract_items(invoice, volume_unit: str = "CUM") -> list[dict]:
    """Voucher lines, each expressed in a unit its Tally Stock Item knows.

    A line can be billed in any unit of the app's list (155 of sss's 208 final
    sale lines are in a unit that is NOT the product's base unit), but Tally only
    accepts the item's base or its one alternate. Each line is therefore converted
    exactly onto whichever of those shares its dimension — the AMOUNT is never
    touched, the rate scales inversely, so qty x rate still foots. The caller
    attaches ``_product`` (name/unit/bulk_density) in ``routers.tally``; without
    it the line passes through unchanged, exactly as before.
    """
    items = []
    for it in (invoice.items or []):
        prod = getattr(it, "_product", None)
        qty, rate, unit, note = it.quantity, it.rate, (it.unit or "Nos"), None
        if prod is not None:
            qty, rate, unit, note = tally_units.convert_line(
                it.quantity, it.rate, it.unit, prod, volume_unit, amount=it.amount)
        items.append({
            "name": getattr(it, "_product_name", None) or it.description or "Item",
            "unit": unit,
            "qty": qty,
            "rate": rate,
            "amount": it.amount,
            "hsn": it.hsn_code or "",
            "gst_rate": getattr(it, "gst_rate", Decimal("0")),
            "unit_note": note,
        })
    return items

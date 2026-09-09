"""
Tally Prime integration router.

Endpoints:
  GET  /api/v1/tally/config                 — Get Tally config
  PUT  /api/v1/tally/config                 — Update Tally config
  POST /api/v1/tally/test-connection        — Test connectivity to Tally
  GET  /api/v1/tally/companies              — List companies open in Tally
  POST /api/v1/tally/sync/invoice/{id}      — Push one invoice to Tally
  POST /api/v1/tally/sync/bulk              — Push multiple invoices (date range)
  GET  /api/v1/tally/pending                — List invoices not yet synced to Tally
"""
import uuid
from datetime import datetime, timezone, date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.company import Company
from app.models.settings import TallyConfig
from app.models.invoice import Invoice
from app.models.party import Party
from app.integrations.tally.client import TallyClient
from app.models.quotation import Quotation, QuotationItem
from app.models.inventory import InventoryPurchaseOrder, InventoryPOItem
from app.integrations.tally.xml_builder import (
    build_sales_xml, build_purchase_xml,
    build_credit_note_xml, build_debit_note_xml,
    build_customer_master_xml, build_supplier_master_xml,
    build_stock_item_xml, build_unit_xml,
    build_ledger_master_xml, gl_ledger_specs,
    build_sales_order_xml, build_purchase_order_xml,
    TallyLedgerMap, NarrationOptions,
)
from app.integrations.tally import units as tally_units
from app.services.pricing import VOLUME_UNITS
from app.models.product import Product

router = APIRouter(prefix="/api/v1/tally", tags=["Tally"])


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class TallyConfigIn(BaseModel):
    host: str = "localhost"
    port: int = 9002
    tally_company_name: Optional[str] = None
    auto_sync: bool = False
    is_enabled: bool = False
    # Ledger name mappings
    ledger_sales: str = "Sales"
    ledger_purchase: str = "Purchase"
    ledger_cgst: str = "CGST"
    ledger_sgst: str = "SGST"
    ledger_igst: str = "IGST"
    ledger_freight: str = "Freight Outward"
    ledger_discount: str = "Trade Discount"
    ledger_tcs: str = "TCS Payable"
    ledger_roundoff: str = "Round Off"
    # Narration options
    narration_vehicle: bool = True
    narration_token: bool = True
    narration_weight: bool = True
    # No-GST / accounting-only export (legacy Tally + non-GST demo companies).
    accounting_only: bool = False
    # Also sync non-GST (Bill of Supply) invoices to Tally.
    sync_non_gst: bool = False
    # Volume unit Tally stock items carry as their alternate unit (CUM default).
    volume_unit: Optional[str] = None
    # Invoice-number prefix filter (comma-separated; blank = sync all). Only
    # invoices whose number starts with one of these prefixes go to Tally.
    sync_invoice_prefix: Optional[str] = None
    # Transport mode override (admin/provisioning only): 'direct' | 'relay' |
    # None. The normal Settings save omits it (None) → left unchanged.
    mode: Optional[str] = None


class TallyConfigOut(BaseModel):
    id: uuid.UUID
    host: str
    port: int
    tally_company_name: Optional[str]
    auto_sync: bool
    is_enabled: bool
    # Ledger name mappings
    ledger_sales: str
    ledger_purchase: str
    ledger_cgst: str
    ledger_sgst: str
    ledger_igst: str
    ledger_freight: str
    ledger_discount: str
    ledger_tcs: str
    ledger_roundoff: str
    # Narration options
    narration_vehicle: bool
    narration_token: bool
    narration_weight: bool
    accounting_only: bool = False
    sync_non_gst: bool = False
    volume_unit: Optional[str] = None
    sync_invoice_prefix: Optional[str] = None
    mode: Optional[str] = None

    class Config:
        from_attributes = True


class BulkSyncRequest(BaseModel):
    invoice_type: Optional[str] = None   # "sale" | "purchase" | None = both
    from_date: Optional[str] = None      # YYYY-MM-DD
    to_date: Optional[str] = None        # YYYY-MM-DD
    include_synced: bool = False         # re-sync already-synced invoices


class SyncResult(BaseModel):
    invoice_id: str
    invoice_no: str
    success: bool
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _get_config(db: AsyncSession, company_id: uuid.UUID) -> TallyConfig:
    result = await db.execute(
        select(TallyConfig).where(TallyConfig.company_id == company_id)
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        cfg = TallyConfig(company_id=company_id)
        db.add(cfg)
        await db.flush()
    return cfg


async def _get_company(db: AsyncSession, company_id: uuid.UUID) -> Company:
    """The company, stamped with the Tally company its documents file under.

    ``tally_company_name`` is a column on **TallyConfig**, but every XML builder
    reads it off the Company object — so without this stamp the Settings → Tally
    "Tally company name" field never reached a single voucher and the builders
    silently fell back to the app's own company name. Since the client's Tally
    company is rarely spelled the same, Tally rejected the whole import with
    "Could not set 'SVCurrentCompany'".

    Stamped here rather than at each of the ten call sites so every builder, and
    the connector's rebuild-on-retry path, pick it up. The attribute is unmapped,
    so SQLAlchemy never persists it.
    """
    company = (await db.execute(select(Company).where(Company.id == company_id))).scalar_one()
    configured = (await db.execute(
        select(TallyConfig.tally_company_name).where(TallyConfig.company_id == company_id)
    )).scalar_one_or_none()
    # Blank stays blank: the builders then omit SVCURRENTCOMPANY so Tally imports
    # into whichever company is open. Never guess with company.name.
    company.tally_company_name = (configured or "").strip() or None
    return company


async def _allow_non_gst(db: AsyncSession, company_id: uuid.UUID) -> bool:
    """Whether non-GST (Bill of Supply) invoices are eligible for Tally sync."""
    row = (await db.execute(
        select(TallyConfig.sync_non_gst).where(TallyConfig.company_id == company_id)
    )).scalar_one_or_none()
    return bool(row)


def _tax_filter(allow_non_gst: bool):
    """SQL clause for which invoice tax_types flow to Tally."""
    if allow_non_gst:
        return Invoice.tax_type.in_(["gst", "non_gst"])
    return Invoice.tax_type == "gst"


def _make_client(cfg: TallyConfig) -> TallyClient:
    return TallyClient(
        host=cfg.host or "localhost",
        port=cfg.port or 9002,
        company=cfg.tally_company_name or "",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Invoice-number prefix filter
#   Only invoices whose number starts with one of the configured prefixes are
#   sent to Tally. Blank/None = sync all (backward compatible). Comma-separated
#   list, e.g. "INV,PUR". Applied uniformly at the _push_invoice chokepoint
#   (manual + bulk + auto-sync) and SQL-side on the pending/bulk worklists.
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_prefixes(raw: str | None) -> list[str]:
    """Split the configured comma-separated prefix string into a clean list."""
    if not raw or not raw.strip():
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _invoice_matches_prefix(invoice_no: str | None, raw_prefix: str | None) -> bool:
    """True if ``invoice_no`` should sync to Tally given the prefix filter.

    Empty/blank filter → every invoice matches. Otherwise the number must start
    with one of the configured prefixes (case-insensitive).
    """
    prefixes = _normalize_prefixes(raw_prefix)
    if not prefixes:
        return True
    if not invoice_no:
        return False
    inv = invoice_no.strip().lower()
    return any(inv.startswith(p.lower()) for p in prefixes)


def _prefix_sql_clause(raw_prefix: str | None):
    """Build an OR of ``invoice_no ILIKE 'prefix%'`` for SQL filtering, or None."""
    prefixes = _normalize_prefixes(raw_prefix)
    if not prefixes:
        return None
    from sqlalchemy import or_ as _or
    return _or(*[Invoice.invoice_no.ilike(f"{p}%") for p in prefixes])


async def _dispatch_xml(
    cfg: TallyConfig,
    entity_type: str,
    entity_id: uuid.UUID,
    company_name: str,
    xml: str,
    db: AsyncSession,
) -> tuple[bool, str, bool]:
    """Send the built XML via the tenant's configured transport.

    Returns ``(operation_ok, message, mark_synced)``:
      • direct mode → operation_ok = Tally confirmed; mark_synced = same.
      • relay mode  → operation_ok = True (queued); mark_synced = False (the
        connector's later report flips ``tally_synced``).
    The single seam shared by manual, bulk, and auto-sync.
    """
    from app.integrations.tally.transport import get_transport
    result = await get_transport(cfg).dispatch(
        entity_type=entity_type,
        entity_id=entity_id,
        company_name=company_name,
        xml=xml,
        idempotency_key=f"{entity_type}:{entity_id}",
        db=db,
    )
    return (result.synced or result.queued), result.message, result.synced


async def _build_invoice_xml(
    invoice: Invoice,
    company: Company,
    cfg: TallyConfig,
    db: AsyncSession,
) -> tuple[str | None, str]:
    """Build the Tally voucher XML for a sale/purchase invoice using the saved
    ledger map + narration options. Returns ``(xml, "")`` on success, or
    ``(None, reason)`` for unsupported invoice types. No dispatch / no DB writes
    — shared by the live sync path and the Tier-0 'Download Tally XML' export.
    """
    party = None
    if invoice.party_id:
        party = (await db.execute(select(Party).where(Party.id == invoice.party_id))).scalar_one_or_none()

    # Ensure items are loaded
    if not invoice.items:
        inv_with_items = (await db.execute(
            select(Invoice).options(selectinload(Invoice.items)).where(Invoice.id == invoice.id)
        )).scalar_one_or_none()
        if inv_with_items:
            invoice = inv_with_items
    # Resolve the real product NAME + UNIT for each line so the Tally inventory
    # entry's STOCKITEMNAME matches the synced Stock Item master. Without this the
    # builder fell back to the literal "Item", and full-mode (with-qty) invoices
    # failed in Tally with "Stock Item 'Item' does not exist!".
    _items = list(invoice.items or [])
    _pids = {getattr(it, "product_id", None) for it in _items if getattr(it, "product_id", None)}
    _pmap: dict = {}
    if _pids:
        for _p in (await db.execute(
            select(Product).where(Product.id.in_(_pids))
        )).scalars().all():
            _pmap[_p.id] = _p
    for item in _items:
        _prod = _pmap.get(getattr(item, "product_id", None))
        _pname = getattr(_prod, "name", None) if _prod is not None else None
        _punit = getattr(_prod, "unit", None) if _prod is not None else None
        # STOCKITEMNAME = product name (matches the master); description is a fallback.
        item._product_name = _pname or getattr(item, "description", None) or "Item"
        if _punit and not getattr(item, "unit", None):
            item.unit = _punit
        # The product's base unit + bulk density let _extract_items express the
        # line in a unit the Tally Stock Item actually knows (base or alternate).
        item._product = _prod

    ledger_map = TallyLedgerMap(
        sales=cfg.ledger_sales or "Sales",
        purchase=cfg.ledger_purchase or "Purchase",
        cgst=cfg.ledger_cgst or "CGST",
        sgst=cfg.ledger_sgst or "SGST",
        igst=cfg.ledger_igst or "IGST",
        freight=cfg.ledger_freight or "Freight Outward",
        discount=cfg.ledger_discount or "Trade Discount",
        tcs=cfg.ledger_tcs or "TCS Payable",
        roundoff=cfg.ledger_roundoff or "Round Off",
    )
    narration_opts = NarrationOptions(
        include_vehicle=cfg.narration_vehicle,
        include_token=cfg.narration_token,
        include_weight=cfg.narration_weight,
    )
    acct_only = bool(getattr(cfg, "accounting_only", False))
    vol_unit = tally_units.canonical_volume_unit(cfg)
    if invoice.invoice_type == "sale":
        return build_sales_xml(invoice, company, party, ledger_map, narration_opts,
                               accounting_only=acct_only, volume_unit=vol_unit), ""
    if invoice.invoice_type == "purchase":
        return build_purchase_xml(invoice, company, party, ledger_map, narration_opts,
                                  accounting_only=acct_only, volume_unit=vol_unit), ""
    if invoice.invoice_type in ("credit_note", "debit_note"):
        # Settle the note "Agst Ref" the original invoice number (GSTR-1 CDNR link).
        ref_no = None
        if getattr(invoice, "reference_invoice_id", None):
            ref_no = (await db.execute(
                select(Invoice.invoice_no).where(Invoice.id == invoice.reference_invoice_id)
            )).scalar_one_or_none()
        builder = build_credit_note_xml if invoice.invoice_type == "credit_note" else build_debit_note_xml
        return builder(invoice, company, party, ledger_map, narration_opts,
                       reference_invoice_no=ref_no, accounting_only=acct_only,
                       volume_unit=vol_unit), ""
    return None, (
        f"Invoice type '{invoice.invoice_type}' cannot be exported to Tally. "
        "Only sale, purchase, credit_note and debit_note are supported."
    )


def _tally_cfg_company(cfg, company=None) -> str:
    """The configured Tally company name — "" when unset (never the app's name)."""
    return (getattr(cfg, "tally_company_name", None) or "").strip()


def _static_vars(tally_company: str | None) -> str:
    """The STATICVARIABLES block for a re-built envelope, or "" when unnamed.

    A merge discards the source envelopes and writes a new one, so without this the
    company name the individual builders set is silently dropped — masters would
    import into whichever company happens to be open while vouchers targeted the
    configured one. Blank stays blank (see xml_builder._current_company).
    """
    name = (tally_company or "").strip()
    if not name:
        return ""
    from xml.sax.saxutils import escape
    return f"<STATICVARIABLES><SVCURRENTCOMPANY>{escape(name)}</SVCURRENTCOMPANY></STATICVARIABLES>"


def _merge_voucher_xmls(xmls: list[str], tally_company: str | None = None) -> str:
    """Bundle N single-voucher ENVELOPEs into one importable Tally ENVELOPE by
    collecting their TALLYMESSAGE blocks under one REQUESTDATA (REPORTNAME=Vouchers).
    """
    from xml.etree import ElementTree as ET
    messages: list[str] = []
    for x in xmls:
        try:
            root = ET.fromstring(x)
        except ET.ParseError:
            continue
        for tm in root.findall(".//TALLYMESSAGE"):
            messages.append(ET.tostring(tm, encoding="unicode"))
    body = "".join(messages)
    return (
        '<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>'
        '<BODY><IMPORTDATA>'
        f'<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME>{_static_vars(tally_company)}</REQUESTDESC>'
        f'<REQUESTDATA>{body}</REQUESTDATA>'
        '</IMPORTDATA></BODY></ENVELOPE>'
    )


def _merge_master_xmls(xmls: list[str], tally_company: str | None = None) -> str:
    """Bundle N master ENVELOPEs into one importable Tally 'All Masters' ENVELOPE.

    Order is preserved, so a Unit master can precede the Stock Item that
    references it (Tally needs the base unit to exist before the item).
    """
    from xml.etree import ElementTree as ET
    messages: list[str] = []
    for x in xmls:
        try:
            root = ET.fromstring(x)
        except ET.ParseError:
            continue
        for tm in root.findall(".//TALLYMESSAGE"):
            messages.append(ET.tostring(tm, encoding="unicode"))
    body = "".join(messages)
    return (
        '<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>'
        '<BODY><IMPORTDATA>'
        f'<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME>{_static_vars(tally_company)}</REQUESTDESC>'
        f'<REQUESTDATA>{body}</REQUESTDATA>'
        '</IMPORTDATA></BODY></ENVELOPE>'
    )


async def _push_invoice(
    invoice: Invoice,
    company: Company,
    db: AsyncSession,
) -> tuple[bool, str]:
    """Build XML and push to Tally. Updates tally_synced on the invoice."""
    # Ensure company has tally config
    cfg_result = await db.execute(
        select(TallyConfig).where(TallyConfig.company_id == company.id)
    )
    cfg = cfg_result.scalar_one_or_none()
    if not cfg or not cfg.is_enabled:
        return False, "Tally integration is not enabled. Enable it in Settings → Tally."

    # Invoice-number prefix filter — the single chokepoint for manual, bulk and
    # auto-sync. Blank filter → everything matches (backward compatible).
    if not _invoice_matches_prefix(invoice.invoice_no, cfg.sync_invoice_prefix):
        return False, (
            f"Invoice {invoice.invoice_no} does not match the Tally sync prefix "
            f"filter ('{cfg.sync_invoice_prefix}'). Change it in Settings → Tally "
            f"if this invoice should sync."
        )

    # Build the voucher XML (shared with the Tier-0 export)
    xml, build_err = await _build_invoice_xml(invoice, company, cfg, db)
    if xml is None:
        return False, build_err

    # Dispatch via the configured transport (direct push, or relay queue in SaaS)
    company_name = cfg.tally_company_name or getattr(company, "name", "") or ""
    op_ok, message, synced = await _dispatch_xml(cfg, "invoice", invoice.id, company_name, xml, db)

    # In relay mode `synced` is False (stays in /tally/pending until the
    # connector confirms); in direct mode it reflects the Tally result.
    invoice.tally_synced = synced
    invoice.tally_sync_at = datetime.now(timezone.utc)
    await db.flush()

    return op_ok, message


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

def _effective_mode(cfg) -> str:
    """Resolved transport mode ('direct'|'relay'). Imported lazily like the
    transport itself, so this router never imports the queue at module load."""
    from app.integrations.tally.transport import effective_mode
    return effective_mode(cfg)


def _config_out(cfg) -> TallyConfigOut:
    """Serialise the config reporting the EFFECTIVE transport mode.

    ``mode`` is stored as an OVERRIDE — NULL means "derive from the deployment"
    (cloud → relay, on-prem → direct). Returning the raw NULL made the Settings
    page treat every cloud tenant as on-premise: it showed Host/Port and a "Test
    Connection" button that makes the CLOUD dial its own localhost (always fails,
    and reads as if the client's Tally were unreachable), while hiding the
    connector queue that tenant actually needs. Report what will really happen.
    """
    out = TallyConfigOut.model_validate(cfg)
    return out.model_copy(update={"mode": _effective_mode(cfg)})


@router.get("/config", response_model=TallyConfigOut)
async def get_tally_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cfg = await _get_config(db, current_user.company_id)
    return _config_out(cfg)


@router.put("/config", response_model=TallyConfigOut)
async def update_tally_config(
    payload: TallyConfigIn,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    cfg = await _get_config(db, current_user.company_id)
    cfg.host = payload.host
    cfg.port = payload.port
    cfg.tally_company_name = payload.tally_company_name
    cfg.auto_sync = payload.auto_sync
    cfg.is_enabled = payload.is_enabled
    # Ledger name mappings
    cfg.ledger_sales = payload.ledger_sales
    cfg.ledger_purchase = payload.ledger_purchase
    cfg.ledger_cgst = payload.ledger_cgst
    cfg.ledger_sgst = payload.ledger_sgst
    cfg.ledger_igst = payload.ledger_igst
    cfg.ledger_freight = payload.ledger_freight
    cfg.ledger_discount = payload.ledger_discount
    cfg.ledger_tcs = payload.ledger_tcs
    cfg.ledger_roundoff = payload.ledger_roundoff
    # Narration options
    cfg.narration_vehicle = payload.narration_vehicle
    cfg.narration_token = payload.narration_token
    cfg.narration_weight = payload.narration_weight
    cfg.accounting_only = payload.accounting_only
    cfg.sync_non_gst = payload.sync_non_gst
    _vu = (payload.volume_unit or "").strip().upper()
    cfg.volume_unit = _vu if _vu in VOLUME_UNITS else None
    # Invoice prefix filter — normalise blank → NULL (means "sync all")
    cfg.sync_invoice_prefix = (payload.sync_invoice_prefix or "").strip() or None
    # Transport mode is set by provisioning/admin; the normal Settings save omits
    # it (None) → leave unchanged so a relay tenant isn't flipped back to direct.
    if payload.mode is not None:
        cfg.mode = (payload.mode or "").strip().lower() or None
    try:
        await db.commit()
    except Exception as e:  # surface the real DB error instead of a silent 500
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Could not save Tally settings: {str(e)[:300]}")
    await db.refresh(cfg)
    return cfg


@router.post("/test-connection")
async def test_tally_connection(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cfg = await _get_config(db, current_user.company_id)
    if _effective_mode(cfg) == "relay":
        # There is nothing meaningful to test from here: this server would be
        # dialling its OWN localhost, not the client's Tally PC.
        return {
            "success": False,
            "message": ("This company syncs through the Tally Connector running on your own "
                        "PC — the cloud cannot reach your Tally directly, so there is nothing "
                        "to test from here. On the Tally PC run:  tally_connector.exe --test"),
            "host": cfg.host, "port": cfg.port,
        }
    client = _make_client(cfg)
    success, message = await client.test_connection()
    return {"success": success, "message": message, "host": cfg.host, "port": cfg.port}


@router.get("/companies")
async def list_tally_companies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cfg = await _get_config(db, current_user.company_id)
    client = _make_client(cfg)
    ok, companies = await client.get_companies()
    return {"success": ok, "companies": companies}


@router.get("/sync-log")
async def tally_sync_log(
    status: Optional[str] = None,          # delivered | waiting | failed
    entity_type: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every record sent to Tally, and whether Tally accepted it.

    Answers the only question that matters day to day — "did this actually land?"
    — from Tally's OWN reply, not from our intent to send. `delivered` means Tally
    reported it created or altered the record; `failed` carries Tally's exact
    words (missing ledger, refused company, timeout) so the cause is actionable.

    Reads the connector queue, so it is populated in cloud (relay) mode. On-prem
    direct mode pushes synchronously and keeps no queue — the caller is told so
    rather than being shown a misleading empty log.
    """
    cid = str(current_user.company_id)
    mode = _effective_mode(await _get_config(db, cid))

    where = ["j.company_id = :cid"]
    params: dict = {"cid": cid}
    status_sql = {
        "delivered": "j.status = 'done'",
        "waiting": "j.status IN ('pending','in_progress')",
        "failed": "j.status IN ('dead','failed')",
    }
    if status in status_sql:
        where.append(status_sql[status])
    if entity_type:
        where.append("j.entity_type = :et")
        params["et"] = entity_type

    # One readable name per row, whatever kind of record it is.
    label = (
        "COALESCE(i.invoice_no, pa.name, pr.name, "
        "substring(j.xml from '<VOUCHERNUMBER>([^<]*)</VOUCHERNUMBER>'), "
        "substring(j.xml from '<LEDGER NAME=\"([^\"]*)\"'), "
        "substring(j.xml from '<STOCKITEM NAME=\"([^\"]*)\"'), "
        "j.entity_type)"
    )
    if search:
        where.append(f"{label} ILIKE :q")
        params["q"] = f"%{search.strip()}%"

    joins = (
        "FROM tally_sync_jobs j "
        "LEFT JOIN invoices i ON i.id = j.entity_id "
        "LEFT JOIN parties  pa ON pa.id = j.entity_id "
        "LEFT JOIN products pr ON pr.id = j.entity_id "
    )
    clause = " WHERE " + " AND ".join(where)

    total = (await db.execute(text(f"SELECT count(*) {joins}{clause}"), params)).scalar() or 0
    params["lim"] = max(1, min(int(page_size or 100), 500))
    params["off"] = max(0, (max(1, int(page or 1)) - 1) * params["lim"])

    rows = (await db.execute(text(
        f"SELECT j.id, j.entity_type, {label} AS label, j.status, j.attempts, "
        f"j.last_error, j.company_name, j.created_at, j.completed_at, j.next_attempt_at "
        f"{joins}{clause} ORDER BY COALESCE(j.completed_at, j.created_at) DESC "
        f"LIMIT :lim OFFSET :off"
    ), params)).fetchall()

    counts = dict((r[0], r[1]) for r in (await db.execute(text(
        f"SELECT j.status, count(*) {joins} WHERE j.company_id = :cid GROUP BY j.status"
    ), {"cid": cid})).fetchall())

    def outcome(st: str) -> str:
        if st == "done":
            return "delivered"
        if st in ("dead", "failed"):
            return "failed"
        return "waiting"

    return {
        "mode": mode,
        "total": int(total),
        "summary": {
            "delivered": int(counts.get("done", 0)),
            "waiting": int(counts.get("pending", 0)) + int(counts.get("in_progress", 0)),
            "failed": int(counts.get("dead", 0)) + int(counts.get("failed", 0)),
        },
        "items": [
            {
                "id": str(r.id),
                "entity_type": r.entity_type,
                "label": r.label,
                "outcome": outcome(r.status),
                "status": r.status,
                "attempts": r.attempts,
                "reason": r.last_error,
                "tally_company": r.company_name,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "next_attempt_at": r.next_attempt_at.isoformat() if r.next_attempt_at else None,
            }
            for r in rows
        ],
    }


@router.get("/pending")
async def list_pending_invoices(
    invoice_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return finalised invoices not yet pushed to Tally.

    Excludes non-GST invoices (Bill of Supply) — those are cash-mode
    parties that don't go through the GST books.
    """
    q = select(Invoice).where(
        Invoice.company_id == current_user.company_id,
        Invoice.status == "final",
        _tax_filter(await _allow_non_gst(db, current_user.company_id)),
        Invoice.tally_synced == False,  # noqa: E712
    )
    if invoice_type:
        q = q.where(Invoice.invoice_type == invoice_type)
    # Restrict the worklist to invoices that match the configured prefix filter
    _cfg = (await db.execute(
        select(TallyConfig).where(TallyConfig.company_id == current_user.company_id)
    )).scalar_one_or_none()
    _pfx = _prefix_sql_clause(_cfg.sync_invoice_prefix if _cfg else None)
    if _pfx is not None:
        q = q.where(_pfx)
    q = q.order_by(Invoice.invoice_date.desc())
    rows = (await db.execute(q)).scalars().all()
    return {
        "total": len(rows),
        "items": [
            {
                "id": str(r.id),
                "invoice_no": r.invoice_no,
                "invoice_type": r.invoice_type,
                "invoice_date": str(r.invoice_date),
                "grand_total": float(r.grand_total),
                "tally_synced": r.tally_synced,
                "tally_sync_at": r.tally_sync_at.isoformat() if r.tally_sync_at else None,
            }
            for r in rows
        ],
    }


@router.post("/sync/invoice/{invoice_id}")
async def sync_invoice_to_tally(
    invoice_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Push a single finalised invoice to Tally."""
    invoice = (await db.execute(
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(
            Invoice.id == invoice_id,
            Invoice.company_id == current_user.company_id,
        )
    )).scalar_one_or_none()

    if not invoice:
        raise HTTPException(404, "Invoice not found")
    if invoice.status != "final":
        raise HTTPException(400, "Only finalised invoices can be synced to Tally")
    # Block non-GST invoices (Bill of Supply) — these are cash-mode and
    # shouldn't appear in the GST books that Tally is sync'd to.
    if invoice.tax_type != "gst" and not await _allow_non_gst(db, current_user.company_id):
        raise HTTPException(
            400,
            f"Invoice {invoice.invoice_no} is non-GST (Bill of Supply). Enable "
            f"'Also sync non-GST invoices' in Settings → Tally to sync it.",
        )

    company = await _get_company(db, current_user.company_id)
    success, message = await _push_invoice(invoice, company, db)
    await db.commit()

    return {
        "success": success,
        "message": message,
        "invoice_no": invoice.invoice_no,
        "tally_synced": invoice.tally_synced,
        "tally_sync_at": invoice.tally_sync_at.isoformat() if invoice.tally_sync_at else None,
    }


@router.get("/pending/parties")
async def list_pending_parties(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return active parties not yet pushed to Tally as master ledgers."""
    q = select(Party).where(
        Party.company_id == current_user.company_id,
        Party.is_active == True,  # noqa: E712
        Party.tally_synced == False,  # noqa: E712
    ).order_by(Party.name.asc())
    rows = (await db.execute(q)).scalars().all()
    return {
        "total": len(rows),
        "items": [
            {
                "id": str(r.id),
                "name": r.name,
                "party_type": r.party_type,
                "gstin": r.gstin,
                "tally_synced": r.tally_synced,
                "tally_sync_at": r.tally_sync_at.isoformat() if r.tally_sync_at else None,
            }
            for r in rows
        ],
    }


@router.get("/pending/orders")
async def list_pending_orders(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return quotations and approved POs not yet pushed to Tally."""
    # Quotations: accepted status, not yet synced
    quot_q = select(Quotation).where(
        Quotation.company_id == current_user.company_id,
        Quotation.status == "accepted",
        Quotation.tally_synced == False,  # noqa: E712
    ).order_by(Quotation.quotation_date.desc())
    quotations = (await db.execute(quot_q)).scalars().all()

    # Purchase orders: approved status, not yet synced
    po_q = select(InventoryPurchaseOrder).where(
        InventoryPurchaseOrder.company_id == current_user.company_id,
        InventoryPurchaseOrder.status == "approved",
        InventoryPurchaseOrder.tally_synced == False,  # noqa: E712
    ).order_by(InventoryPurchaseOrder.created_at.desc())
    pos = (await db.execute(po_q)).scalars().all()

    return {
        "quotations": {
            "total": len(quotations),
            "items": [
                {
                    "id": str(q.id),
                    "quotation_no": q.quotation_no,
                    "quotation_date": str(q.quotation_date),
                    "grand_total": float(q.grand_total),
                    "tally_synced": q.tally_synced,
                }
                for q in quotations
            ],
        },
        "purchase_orders": {
            "total": len(pos),
            "items": [
                {
                    "id": str(p.id),
                    "po_no": p.po_no,
                    "supplier_name": p.supplier_name,
                    "status": p.status,
                    "tally_synced": p.tally_synced,
                }
                for p in pos
            ],
        },
    }


async def _party_master_xml(db, party, company) -> str:
    """Build a party's Tally ledger master, grouped by how the party is ACTUALLY used.

    Tally holds one ledger per name, so a ``both``-type party cannot sit under
    Sundry Debtors and Sundry Creditors at once. Routing every ``both`` party to
    Debtors (the old rule) mis-grouped parties we only ever buy from, so the group
    is taken from their finalised invoices: purchases but no sales → Creditors,
    otherwise Debtors. A party used both ways stays a Debtor — a Tally limitation,
    not a choice — and purchase vouchers against it still post correctly.
    """
    ptype = (party.party_type or "").lower()
    if ptype == "customer":
        return build_customer_master_xml(party, company)
    if ptype == "supplier":
        return build_supplier_master_xml(party, company)
    kinds = set((await db.execute(
        select(Invoice.invoice_type).where(
            Invoice.party_id == party.id,
            Invoice.company_id == party.company_id,
            Invoice.status == "final",
        ).distinct()
    )).scalars().all())
    if "purchase" in kinds and "sale" not in kinds:
        return build_supplier_master_xml(party, company)
    return build_customer_master_xml(party, company)


@router.post("/sync/party/{party_id}")
async def sync_party_to_tally(
    party_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Push a single party as a Customer or Supplier master ledger to Tally."""
    party = (await db.execute(
        select(Party).where(
            Party.id == party_id,
            Party.company_id == current_user.company_id,
        )
    )).scalar_one_or_none()
    if not party:
        raise HTTPException(404, "Party not found")

    cfg = await _get_config(db, current_user.company_id)
    if not cfg or not cfg.is_enabled:
        raise HTTPException(400, "Tally integration is not enabled. Enable it in Settings → Tally.")

    company = await _get_company(db, current_user.company_id)

    xml = await _party_master_xml(db, party, company)

    company_name = cfg.tally_company_name or getattr(company, "name", "") or ""
    op_ok, message, synced = await _dispatch_xml(cfg, "party", party.id, company_name, xml, db)

    party.tally_synced = synced
    party.tally_sync_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "success": op_ok,
        "message": message,
        "party_id": str(party.id),
        "party_name": party.name,
        "party_type": party.party_type,
        "tally_synced": party.tally_synced,
        "tally_sync_at": party.tally_sync_at.isoformat() if party.tally_sync_at else None,
    }


@router.post("/sync/product/{product_id}")
async def sync_product_to_tally(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Push a single Product to Tally as a Stock Item master (with its Unit of Measure).

    Sends the Unit master first (the Stock Item references it), then the item,
    bundled into one 'All Masters' import. No GST/HSN — imports on legacy Tally too.
    """
    product = (await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.company_id == current_user.company_id,
        )
    )).scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    cfg = await _get_config(db, current_user.company_id)
    if not cfg or not cfg.is_enabled:
        raise HTTPException(400, "Tally integration is not enabled. Enable it in Settings → Tally.")

    company = await _get_company(db, current_user.company_id)

    unit = (getattr(product, "unit", None) or "Nos").strip() or "Nos"
    vol_unit = tally_units.canonical_volume_unit(cfg)
    # Every unit the item references must exist in Tally BEFORE the item does —
    # the base, and the alternate unit that lets Tally accept a quantity billed in
    # the other dimension (e.g. an MT item sold by the cubic metre).
    _alt = tally_units.alternate_unit(product, vol_unit)
    _units = [unit] + ([_alt[0]] if _alt and _alt[0].upper() != unit.upper() else [])
    xml = _merge_master_xmls(
        [build_unit_xml(u, company) for u in _units]
        + [build_stock_item_xml(product, company, volume_unit=vol_unit)],
        tally_company=_tally_cfg_company(cfg, company),
    )

    company_name = cfg.tally_company_name or getattr(company, "name", "") or ""
    op_ok, message, _synced = await _dispatch_xml(cfg, "product", product.id, company_name, xml, db)
    await db.commit()   # persist the relay job (no-op in direct mode)

    return {
        "success": op_ok,
        "message": message,
        "product_id": str(product.id),
        "product_name": product.name,
        "unit": unit,
        "alternate_unit": _alt[0] if _alt else None,
        "conversion": tally_units.format_conversion(_alt[1]) if _alt else None,
    }


@router.post("/sync/ledgers")
async def sync_ledgers_to_tally(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create the GL ledgers Tally needs for vouchers — Sales, Purchase, CGST, SGST,
    IGST, Round Off, Freight, Trade Discount, TCS — under the right groups (GST
    ledgers get a duty head). Run ONCE so both GST and no-GST invoices have their
    ledgers (otherwise GST invoices fail "Ledger 'CGST' does not exist")."""
    cfg = await _get_config(db, current_user.company_id)
    if not cfg or not cfg.is_enabled:
        raise HTTPException(400, "Tally integration is not enabled. Enable it in Settings → Tally.")
    company = await _get_company(db, current_user.company_id)
    lmap = TallyLedgerMap(
        sales=cfg.ledger_sales or "Sales",
        purchase=cfg.ledger_purchase or "Purchase",
        cgst=cfg.ledger_cgst or "CGST",
        sgst=cfg.ledger_sgst or "SGST",
        igst=cfg.ledger_igst or "IGST",
        freight=cfg.ledger_freight or "Freight Outward",
        discount=cfg.ledger_discount or "Trade Discount",
        tcs=cfg.ledger_tcs or "TCS Payable",
        roundoff=cfg.ledger_roundoff or "Round Off",
    )
    specs = gl_ledger_specs(lmap)
    # Seed the Units of Measure too: a Stock Item import fails outright if its
    # unit does not exist yet, and lines are billed in units beyond the product
    # masters' own (CBM/CUM/CFT/BRASS/QUINTAL…). Cheap and idempotent.
    vol_unit = tally_units.canonical_volume_unit(cfg)
    prod_units = [u for (u,) in (await db.execute(
        select(Product.unit).where(
            Product.company_id == current_user.company_id, Product.unit.isnot(None)
        ).distinct()
    )).all() if (u or "").strip()]
    unit_syms, _seen = [], set()
    for u in [*prod_units, vol_unit, "MT"]:
        k = u.strip().upper()
        if k and k not in _seen:
            _seen.add(k)
            unit_syms.append(u.strip())
    xml = _merge_master_xmls(
        [build_unit_xml(u, company) for u in unit_syms]
        + [build_ledger_master_xml(n, parent, company, gst_duty_head=duty)
           for (n, parent, duty) in specs],
        tally_company=_tally_cfg_company(cfg, company),
    )
    company_name = cfg.tally_company_name or getattr(company, "name", "") or ""
    eid = uuid.uuid5(uuid.NAMESPACE_URL, f"tally-ledgers:{current_user.company_id}")
    op_ok, message, _synced = await _dispatch_xml(cfg, "ledger", eid, company_name, xml, db)
    await db.commit()
    return {"success": op_ok, "message": message,
            "ledgers": [n for (n, _, _) in specs], "units": unit_syms}


@router.post("/sync/parties")
async def bulk_sync_parties_to_tally(
    include_synced: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk push all (unsynced) active parties to Tally as master ledgers."""
    cfg = await _get_config(db, current_user.company_id)
    if not cfg or not cfg.is_enabled:
        raise HTTPException(400, "Tally integration is not enabled.")

    company = await _get_company(db, current_user.company_id)
    company_name = cfg.tally_company_name or getattr(company, "name", "") or ""

    q = select(Party).where(
        Party.company_id == current_user.company_id,
        Party.is_active == True,  # noqa: E712
    )
    if not include_synced:
        q = q.where(Party.tally_synced == False)  # noqa: E712
    q = q.order_by(Party.name.asc()).limit(200)

    parties = (await db.execute(q)).scalars().all()
    if not parties:
        return {"total": 0, "synced": 0, "failed": 0, "results": []}

    results = []
    synced_count = 0
    failed_count = 0

    for party in parties:
        xml = await _party_master_xml(db, party, company)

        op_ok, message, synced = await _dispatch_xml(cfg, "party", party.id, company_name, xml, db)
        party.tally_synced = synced
        party.tally_sync_at = datetime.now(timezone.utc)
        results.append({
            "party_id": str(party.id),
            "name": party.name,
            "success": op_ok,
            "message": message,
        })
        if op_ok:
            synced_count += 1
        else:
            failed_count += 1

    await db.commit()
    return {
        "total": len(parties),
        "synced": synced_count,
        "failed": failed_count,
        "results": results,
    }


@router.post("/sync/sales-order/{quotation_id}")
async def sync_sales_order_to_tally(
    quotation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Push a quotation to Tally as a Sales Order voucher."""
    quotation = (await db.execute(
        select(Quotation)
        .options(selectinload(Quotation.items))
        .where(
            Quotation.id == quotation_id,
            Quotation.company_id == current_user.company_id,
        )
    )).scalar_one_or_none()
    if not quotation:
        raise HTTPException(404, "Quotation not found")

    cfg = await _get_config(db, current_user.company_id)
    if not cfg or not cfg.is_enabled:
        raise HTTPException(400, "Tally integration is not enabled.")

    company = await _get_company(db, current_user.company_id)

    # Resolve party
    party = None
    if quotation.party_id:
        party = (await db.execute(
            select(Party).where(Party.id == quotation.party_id)
        )).scalar_one_or_none()

    ledger_map = TallyLedgerMap(
        sales=cfg.ledger_sales or "Sales",
        purchase=cfg.ledger_purchase or "Purchase",
        cgst=cfg.ledger_cgst or "CGST",
        sgst=cfg.ledger_sgst or "SGST",
        igst=cfg.ledger_igst or "IGST",
        freight=cfg.ledger_freight or "Freight Outward",
        discount=cfg.ledger_discount or "Trade Discount",
        tcs=cfg.ledger_tcs or "TCS Payable",
        roundoff=cfg.ledger_roundoff or "Round Off",
    )

    xml = build_sales_order_xml(quotation, company, party, ledger_map)
    company_name = cfg.tally_company_name or getattr(company, "name", "") or ""
    op_ok, message, synced = await _dispatch_xml(cfg, "sales_order", quotation.id, company_name, xml, db)

    quotation.tally_synced = synced
    quotation.tally_sync_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "success": op_ok,
        "message": message,
        "quotation_id": str(quotation.id),
        "quotation_no": quotation.quotation_no,
        "tally_synced": quotation.tally_synced,
        "tally_sync_at": quotation.tally_sync_at.isoformat() if quotation.tally_sync_at else None,
    }


@router.post("/sync/purchase-order/{po_id}")
async def sync_purchase_order_to_tally(
    po_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Push an approved inventory purchase order to Tally as a Purchase Order voucher."""
    po = (await db.execute(
        select(InventoryPurchaseOrder).where(
            InventoryPurchaseOrder.id == po_id,
            InventoryPurchaseOrder.company_id == current_user.company_id,
        )
    )).scalar_one_or_none()
    if not po:
        raise HTTPException(404, "Purchase order not found")
    if po.status not in ("approved", "partially_received", "received"):
        raise HTTPException(400, f"PO must be approved before syncing to Tally (current status: {po.status})")

    cfg = await _get_config(db, current_user.company_id)
    if not cfg or not cfg.is_enabled:
        raise HTTPException(400, "Tally integration is not enabled.")

    company = await _get_company(db, current_user.company_id)

    # Load PO line items
    po_items = (await db.execute(
        select(InventoryPOItem).where(InventoryPOItem.po_id == po.id)
    )).scalars().all()

    tally_company = getattr(company, "tally_company_name", None) or company.name
    ledger_map = TallyLedgerMap(
        purchase=cfg.ledger_purchase or "Purchase",
    )

    xml = build_purchase_order_xml(po, po_items, tally_company, ledger_map)
    company_name = cfg.tally_company_name or tally_company or ""
    op_ok, message, synced = await _dispatch_xml(cfg, "purchase_order", po.id, company_name, xml, db)

    po.tally_synced = synced
    po.tally_sync_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "success": op_ok,
        "message": message,
        "po_id": str(po.id),
        "po_no": po.po_no,
        "tally_synced": po.tally_synced,
        "tally_sync_at": po.tally_sync_at.isoformat() if po.tally_sync_at else None,
    }


@router.post("/sync/bulk")
async def bulk_sync_to_tally(
    payload: BulkSyncRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Push multiple finalised invoices to Tally in one call.

    Non-GST invoices (Bill of Supply, tax_type='non_gst') are silently
    excluded — they are cash-mode parties and not part of the GST books.
    """
    q = select(Invoice).options(selectinload(Invoice.items)).where(
        Invoice.company_id == current_user.company_id,
        Invoice.status == "final",
        _tax_filter(await _allow_non_gst(db, current_user.company_id)),  # GST + (opt) non-GST
    )
    if payload.invoice_type:
        q = q.where(Invoice.invoice_type == payload.invoice_type)
    if not payload.include_synced:
        q = q.where(Invoice.tally_synced == False)  # noqa: E712
    if payload.from_date:
        q = q.where(Invoice.invoice_date >= payload.from_date)
    if payload.to_date:
        q = q.where(Invoice.invoice_date <= payload.to_date)
    # Apply the configured invoice-number prefix filter
    _cfg = (await db.execute(
        select(TallyConfig).where(TallyConfig.company_id == current_user.company_id)
    )).scalar_one_or_none()
    _pfx = _prefix_sql_clause(_cfg.sync_invoice_prefix if _cfg else None)
    if _pfx is not None:
        q = q.where(_pfx)
    q = q.order_by(Invoice.invoice_date.asc()).limit(100)

    invoices = (await db.execute(q)).scalars().all()
    if not invoices:
        return {"total": 0, "synced": 0, "failed": 0, "results": []}

    company = await _get_company(db, current_user.company_id)
    results: list[SyncResult] = []
    synced = 0
    failed = 0

    for inv in invoices:
        success, message = await _push_invoice(inv, company, db)
        results.append(SyncResult(
            invoice_id=str(inv.id),
            invoice_no=inv.invoice_no,
            success=success,
            message=message,
        ))
        if success:
            synced += 1
        else:
            failed += 1

    await db.commit()
    return {
        "total": len(invoices),
        "synced": synced,
        "failed": failed,
        "results": [r.model_dump() for r in results],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tier-0 — manual XML export (no connector, no direct push). The user downloads
# the voucher XML and imports it via Tally → Import Data. Works in any mode and
# ignores is_enabled + the prefix filter (an explicit user-requested download).
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/invoices/{invoice_id}/xml")
async def download_invoice_xml(
    invoice_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download one finalised GST invoice as a Tally-importable voucher XML file."""
    invoice = (await db.execute(
        select(Invoice).options(selectinload(Invoice.items)).where(
            Invoice.id == invoice_id,
            Invoice.company_id == current_user.company_id,
        )
    )).scalar_one_or_none()
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    if invoice.status != "final":
        raise HTTPException(400, "Only finalised invoices can be exported to Tally")
    if invoice.tax_type != "gst" and not await _allow_non_gst(db, current_user.company_id):
        raise HTTPException(400, "Non-GST (Bill of Supply) invoices are not exported. Enable 'Also sync non-GST invoices' in Settings → Tally.")

    cfg = await _get_config(db, current_user.company_id)
    company = await _get_company(db, current_user.company_id)
    xml, err = await _build_invoice_xml(invoice, company, cfg, db)
    if xml is None:
        raise HTTPException(400, err)
    safe = (invoice.invoice_no or str(invoice.id)).replace("/", "-").replace("\\", "-")
    return Response(
        content=xml, media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="tally-{safe}.xml"'},
    )


@router.get("/export-xml")
async def export_vouchers_xml(
    invoice_type: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    include_synced: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download finalised GST invoices as ONE importable Tally XML (Tier-0
    fallback for clients with no connector). Defaults to not-yet-synced."""
    def _pd(s: str):
        try:
            return _date.fromisoformat(s)
        except ValueError:
            raise HTTPException(400, f"Invalid date '{s}' (use YYYY-MM-DD)")

    q = select(Invoice).options(selectinload(Invoice.items)).where(
        Invoice.company_id == current_user.company_id,
        Invoice.status == "final",
        _tax_filter(await _allow_non_gst(db, current_user.company_id)),
    )
    if invoice_type:
        q = q.where(Invoice.invoice_type == invoice_type)
    if not include_synced:
        q = q.where(Invoice.tally_synced == False)  # noqa: E712
    if from_date:
        q = q.where(Invoice.invoice_date >= _pd(from_date))
    if to_date:
        q = q.where(Invoice.invoice_date <= _pd(to_date))
    # Apply the same prefix filter the sync worklist uses, for consistency.
    _cfg = (await db.execute(
        select(TallyConfig).where(TallyConfig.company_id == current_user.company_id)
    )).scalar_one_or_none()
    _pfx = _prefix_sql_clause(_cfg.sync_invoice_prefix if _cfg else None)
    if _pfx is not None:
        q = q.where(_pfx)
    q = q.order_by(Invoice.invoice_date.asc())
    invoices = (await db.execute(q)).scalars().all()

    cfg = _cfg or await _get_config(db, current_user.company_id)
    company = await _get_company(db, current_user.company_id)
    xmls: list[str] = []
    for inv in invoices:
        x, _err = await _build_invoice_xml(inv, company, cfg, db)
        if x:
            xmls.append(x)
    merged = _merge_voucher_xmls(xmls, _tally_cfg_company(cfg, company))
    fname = f"tally-vouchers-{datetime.now().strftime('%Y%m%d')}.xml"
    return Response(
        content=merged, media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-Voucher-Count": str(len(xmls)),
        },
    )

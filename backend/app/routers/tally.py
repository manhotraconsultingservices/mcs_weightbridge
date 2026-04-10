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

from fastapi import APIRouter, Depends, HTTPException
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
    build_customer_master_xml, build_supplier_master_xml,
    build_sales_order_xml, build_purchase_order_xml,
    TallyLedgerMap, NarrationOptions,
)

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
    return (await db.execute(select(Company).where(Company.id == company_id))).scalar_one()


def _make_client(cfg: TallyConfig) -> TallyClient:
    return TallyClient(
        host=cfg.host or "localhost",
        port=cfg.port or 9002,
        company=cfg.tally_company_name or "",
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

    # Resolve party
    party = None
    if invoice.party_id:
        party = (await db.execute(select(Party).where(Party.id == invoice.party_id))).scalar_one_or_none()

    # Ensure items are loaded
    if not invoice.items:
        inv_with_items = (await db.execute(
            select(Invoice)
            .options(selectinload(Invoice.items))
            .where(Invoice.id == invoice.id)
        )).scalar_one_or_none()
        if inv_with_items:
            invoice = inv_with_items

    # Attach product names to items (best-effort)
    for item in (invoice.items or []):
        if not item.description:
            item._product_name = "Item"

    # Build ledger map from saved config
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

    # Build narration options from saved config
    narration_opts = NarrationOptions(
        include_vehicle=cfg.narration_vehicle,
        include_token=cfg.narration_token,
        include_weight=cfg.narration_weight,
    )

    # Build XML
    if invoice.invoice_type == "sale":
        xml = build_sales_xml(invoice, company, party, ledger_map, narration_opts)
    else:
        xml = build_purchase_xml(invoice, company, party, ledger_map, narration_opts)

    # Push to Tally
    client = _make_client(cfg)
    success, message = await client.push_xml(xml)

    # Update invoice sync status
    invoice.tally_synced = success
    invoice.tally_sync_at = datetime.now(timezone.utc)
    await db.flush()

    return success, message


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/config", response_model=TallyConfigOut)
async def get_tally_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cfg = await _get_config(db, current_user.company_id)
    return cfg


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
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.post("/test-connection")
async def test_tally_connection(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cfg = await _get_config(db, current_user.company_id)
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


@router.get("/pending")
async def list_pending_invoices(
    invoice_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return finalised invoices not yet pushed to Tally."""
    q = select(Invoice).where(
        Invoice.company_id == current_user.company_id,
        Invoice.status == "final",
        Invoice.tally_synced == False,  # noqa: E712
    )
    if invoice_type:
        q = q.where(Invoice.invoice_type == invoice_type)
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

    # Route to customer or supplier builder
    if party.party_type in ("customer", "both"):
        xml = build_customer_master_xml(party, company)
    else:
        xml = build_supplier_master_xml(party, company)

    client = _make_client(cfg)
    success, message = await client.push_xml(xml)

    party.tally_synced = success
    party.tally_sync_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "success": success,
        "message": message,
        "party_id": str(party.id),
        "party_name": party.name,
        "party_type": party.party_type,
        "tally_synced": party.tally_synced,
        "tally_sync_at": party.tally_sync_at.isoformat() if party.tally_sync_at else None,
    }


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
    client = _make_client(cfg)

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
        if party.party_type in ("customer", "both"):
            xml = build_customer_master_xml(party, company)
        else:
            xml = build_supplier_master_xml(party, company)

        success, message = await client.push_xml(xml)
        party.tally_synced = success
        party.tally_sync_at = datetime.now(timezone.utc)
        results.append({
            "party_id": str(party.id),
            "name": party.name,
            "success": success,
            "message": message,
        })
        if success:
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
    client = _make_client(cfg)
    success, message = await client.push_xml(xml)

    quotation.tally_synced = success
    quotation.tally_sync_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "success": success,
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
    client = _make_client(cfg)
    success, message = await client.push_xml(xml)

    po.tally_synced = success
    po.tally_sync_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "success": success,
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
    """Push multiple finalised invoices to Tally in one call."""
    q = select(Invoice).options(selectinload(Invoice.items)).where(
        Invoice.company_id == current_user.company_id,
        Invoice.status == "final",
    )
    if payload.invoice_type:
        q = q.where(Invoice.invoice_type == payload.invoice_type)
    if not payload.include_synced:
        q = q.where(Invoice.tally_synced == False)  # noqa: E712
    if payload.from_date:
        q = q.where(Invoice.invoice_date >= payload.from_date)
    if payload.to_date:
        q = q.where(Invoice.invoice_date <= payload.to_date)
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
        "results": [r.dict() for r in results],
    }

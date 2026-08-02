"""
Invoice router — Sales & Purchase invoices with GST.

Gap-free numbering:
  invoice_no is assigned ONLY at POST /{id}/finalise (not at draft creation).
  Draft invoices display invoice_no=None until the user decides to finalise.

Move-to-Supplement:
  POST /{id}/move-to-supplement — USB-gated. Migrates draft invoice + token data
  out of normal tables into the encrypted supplementary_entries table.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from sqlalchemy import select, func, and_, text
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, require_role, get_current_branch_id
from app.models.invoice import Invoice, InvoiceItem
from app.models.party import Party
from app.models.product import Product
from app.models.token import Token
from app.models.company import Company, FinancialYear
from app.models.settings import NumberSequence
from app.models.user import User
from app.schemas.invoice import (
    InvoiceCreate, InvoiceUpdate, InvoiceResponse, InvoiceListResponse,
    CreateRevisionRequest, InvoiceRevisionChain, InvoiceCompare,
    WriteOffRequest, InvoiceSplitRequest,
)
from app.services.gst_service import calculate_invoice_totals, is_intra_state, party_place_of_supply
from app.utils.pdf_generator import generate_pdf, invoice_context, render_html

router = APIRouter(prefix="/api/v1/invoices", tags=["Invoices"])


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

async def _get_company_fy(db: AsyncSession):
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not co:
        raise HTTPException(500, "Company not configured")
    fy = (await db.execute(
        select(FinancialYear).where(FinancialYear.is_active == True).limit(1)
    )).scalar_one_or_none()
    if not fy:
        raise HTTPException(500, "No active financial year")
    return co, fy


def _invoice_prefix(invoice_type: str, tax_type: str | None = None) -> str:
    """Number-series prefix per document type.
    Cash/non-GST sale invoices use 'CINV' (separate sequence, not sent to Tally).
    GST sale invoices use 'INV'.
    """
    if invoice_type == "sale" and tax_type == "non_gst":
        return "CINV"
    return {
        "sale": "INV", "purchase": "PUR",
        "credit_note": "CN", "debit_note": "DN",
    }.get(invoice_type, "INV")


async def _next_invoice_no(
    db: AsyncSession, company_id: uuid.UUID, fy_id: uuid.UUID,
    invoice_type: str, prefix: str, branch_id: uuid.UUID | None = None,
) -> str:
    """
    Assign the next sequential invoice number with row-level locking.
    Called at FINALISE — not at draft creation — to prevent numbering gaps.
    Per-branch: branch_id == None → IS NULL (default branch keeps its existing
    series untouched); each branch gets its own gap-free series.
    """
    # Cash (non-GST) sale invoices get their own gap-free sequence so that
    # CINV numbers don't create gaps in the INV series and vice versa.
    seq_type = "cash_sale_invoice" if prefix == "CINV" else f"{invoice_type}_invoice"
    result = await db.execute(
        select(NumberSequence)
        .where(
            NumberSequence.company_id == company_id,
            NumberSequence.fy_id == fy_id,
            NumberSequence.branch_id == branch_id,
            NumberSequence.sequence_type == seq_type,
        )
        .with_for_update()
    )
    seq = result.scalar_one_or_none()
    if not seq:
        seq = NumberSequence(
            company_id=company_id, fy_id=fy_id, branch_id=branch_id,
            sequence_type=seq_type, prefix=prefix,
            last_number=0, reset_daily=False,
        )
        db.add(seq)
    seq.last_number += 1
    await db.flush()
    fy_label = (await db.get(FinancialYear, fy_id)).label  # type: ignore[arg-type]
    short_fy = fy_label[-5:] if fy_label else "25-26"
    return f"{prefix}/{short_fy}/{seq.last_number:04d}"


async def _load_invoice(db: AsyncSession, invoice_id: uuid.UUID) -> Invoice:
    result = await db.execute(
        select(Invoice)
        .options(
            selectinload(Invoice.items).selectinload(InvoiceItem.product),
            selectinload(Invoice.party),
        )
        .where(Invoice.id == invoice_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


async def _capture_draft_baseline(db: AsyncSession, invoice_id: uuid.UUID) -> None:
    """Store the invoice's snapshot as `draft_snapshot` at draft creation, so
    finalise can diff draft→final (what the operator changed between drafting and
    finalising) for the finalize notification. Best-effort — never blocks invoice
    creation; captured once (won't overwrite an existing baseline)."""
    import logging as _log
    from app.utils.invoice_diff import invoice_to_snapshot
    try:
        inv = await _load_invoice(db, invoice_id)
        if inv.draft_snapshot:
            return
        inv.draft_snapshot = invoice_to_snapshot(inv)
        await db.flush()
    except Exception as e:  # noqa: BLE001
        _log.getLogger(__name__).warning("draft baseline capture failed: %s", e)


def _format_diff_for_telegram(diff: dict) -> str:
    """Compact per-field 'Label: old → new' list for a Telegram message body,
    from a compute_invoice_diff() result. Empty when nothing meaningful changed."""
    lines: list[str] = []
    for c in diff.get("header", []):
        lines.append(f"• {c['label']}: {c.get('old') or '—'} → {c.get('new') or '—'}")
    for c in diff.get("amounts", []):
        lines.append(f"• {c['label']}: ₹{c.get('old_str') or '0'} → ₹{c.get('new_str') or '0'}")
    items = diff.get("items", {}) or {}
    for it in items.get("modified", []):
        for c in it.get("changes", []):
            lines.append(f"• {c['label']}: {c.get('old_str') or '—'} → {c.get('new_str') or '—'}")
    for it in items.get("added", []):
        lines.append(f"• Item added: {it.get('description') or ''}")
    for it in items.get("removed", []):
        lines.append(f"• Item removed: {it.get('description') or ''}")
    return "\n".join(lines[:12])  # cap to keep the message short


def _get_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _invoice_to_dict(inv: Invoice, token_no: int | None = None,
                     token_date: date | None = None) -> dict:
    """Build a dict from an ORM Invoice, injecting denormalized token fields."""
    d = {c.name: getattr(inv, c.name) for c in inv.__table__.columns}
    d["items"] = inv.items
    d["party"] = inv.party
    d["token_no"] = token_no
    d["token_date"] = token_date
    return d


# ------------------------------------------------------------------ #
# CRUD Endpoints
# ------------------------------------------------------------------ #

@router.post("", response_model=InvoiceResponse, status_code=201)
async def create_invoice(
    payload: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    branch_id=Depends(get_current_branch_id),
):
    co, fy = await _get_company_fy(db)

    # invoice_no intentionally left NULL — assigned at finalise for gap-free numbering
    prefix = "INV" if payload.invoice_type == "sale" else "PUR"

    party = None
    if payload.party_id:
        party = (await db.execute(select(Party).where(Party.id == payload.party_id))).scalar_one_or_none()
        if not party:
            raise HTTPException(404, "Party not found")

    intra = is_intra_state(co.state_code, party_place_of_supply(party) if party else co.state_code)

    # Payment mode deterministically drives the tax type for a party:
    #   default_payment_mode == 'cash'   → non-GST (Bill of Supply), no GST
    #   default_payment_mode == 'online' → GST invoice
    # The party's mode wins over the form, so a cash party can never produce a
    # GST bill and an online party always charges GST. Walk-in invoices (no
    # party) honour the form's tax_type, since there's no party mode to read.
    if party:
        effective_tax_type = "non_gst" if party.default_payment_mode == "cash" else "gst"
    else:
        effective_tax_type = payload.tax_type

    items_data = [i.model_dump() for i in payload.items]

    # Server-side safety net: if the client sent rate=0 or omitted it for a
    # (party, product) combo where a party-specific rate exists, swap it in.
    # Applies to BOTH sales (customer rate) and purchases (supplier/farmer rate)
    # — party_rates is keyed by party, not type. The UI should also do this, but
    # we don't trust the client.
    if payload.party_id and payload.invoice_type in ("sale", "purchase"):
        from app.services.pricing import resolve_rate
        for it in items_data:
            sent_rate = Decimal(str(it.get("rate") or 0))
            if sent_rate > 0:
                continue   # caller knew the rate; honour it (could be a one-off override)
            # Unit-aware: fill the rate for THIS line's unit (party rate → product
            # per-unit default → product.default_rate → 0).
            r = await resolve_rate(db, payload.party_id, it["product_id"], it.get("unit"))
            if r and r > 0:
                it["rate"] = float(r)

    totals = calculate_invoice_totals(
        items=items_data,
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        freight=payload.freight,
        tcs_rate=payload.tcs_rate,
        intra_state=intra,
        tax_type=effective_tax_type,
        vehicle_rent=payload.vehicle_rent or Decimal("0"),
        royalty=payload.royalty_amount or Decimal("0"),
    )

    gross_weight = payload.gross_weight
    tare_weight = payload.tare_weight
    net_weight = payload.net_weight
    vehicle_no = payload.vehicle_no

    if payload.token_id:
        token = (await db.execute(select(Token).where(Token.id == payload.token_id))).scalar_one_or_none()
        if token:
            gross_weight = gross_weight or token.gross_weight
            tare_weight = tare_weight or token.tare_weight
            net_weight = net_weight or token.net_weight
            vehicle_no = vehicle_no or token.vehicle_no

    # Compute due_date from party's payment_terms_days (if available).
    # This drives the dashboard "Overdue customers" exception card. Falls back
    # to invoice_date itself (so it counts as due immediately) when the party
    # has no terms or there's no party (B2C walk-in).
    due_date = payload.invoice_date
    if party and party.payment_terms_days and party.payment_terms_days > 0:
        from datetime import timedelta as _td
        due_date = payload.invoice_date + _td(days=int(party.payment_terms_days))

    invoice = Invoice(
        company_id=co.id,
        branch_id=branch_id,
        fy_id=fy.id,
        invoice_type=payload.invoice_type,
        tax_type=effective_tax_type,
        invoice_no=None,          # gap-free: assigned at finalise
        invoice_date=payload.invoice_date,
        due_date=due_date,
        party_id=payload.party_id,
        customer_name=payload.customer_name,
        token_id=payload.token_id,
        quotation_id=payload.quotation_id,
        agent_id=payload.agent_id,
        vehicle_no=vehicle_no,
        transporter_name=payload.transporter_name,
        eway_bill_no=payload.eway_bill_no,
        gross_weight=gross_weight,
        tare_weight=tare_weight,
        net_weight=net_weight,
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        payment_mode=payload.payment_mode,
        notes=payload.notes,
        tcs_rate=payload.tcs_rate,
        vehicle_rent=payload.vehicle_rent or Decimal("0"),   # transport rent → billed (in grand_total)
        royalty_amount=payload.royalty_amount or Decimal("0"),  # royalty → billed (in grand_total)
        # Transport & dispatch metadata
        royalty_no=payload.royalty_no,
        delivery_note=payload.delivery_note,
        supplier_ref=payload.supplier_ref,
        buyer_order_no=payload.buyer_order_no,
        buyer_order_date=payload.buyer_order_date,
        dispatch_doc_no=payload.dispatch_doc_no,
        dispatch_through=payload.dispatch_through,
        destination=payload.destination,
        lr_rr_no=payload.lr_rr_no,
        terms_of_delivery=payload.terms_of_delivery,
        driver_name=payload.driver_name,
        created_by=current_user.id,
        status="draft",
        payment_status="unpaid",
        amount_paid=Decimal("0"),
        **{k: v for k, v in totals.items() if k != "computed_items"},
    )
    db.add(invoice)
    await db.flush()

    for i, item_data in enumerate(totals["computed_items"]):
        db.add(InvoiceItem(
            invoice_id=invoice.id,
            product_id=item_data["product_id"],
            description=item_data.get("description"),
            hsn_code=item_data.get("hsn_code"),
            quantity=Decimal(str(item_data["quantity"])),
            unit=item_data["unit"],
            rate=Decimal(str(item_data["rate"])),
            amount=item_data["amount"],
            gst_rate=Decimal(str(item_data.get("gst_rate", 0))),
            cgst_amount=item_data["cgst_amount"],
            sgst_amount=item_data["sgst_amount"],
            igst_amount=item_data["igst_amount"],
            total_amount=item_data["total_amount"],
            sort_order=item_data.get("sort_order", i),
        ))

    from app.routers.audit import log_action
    await log_action(db, co.id, current_user.id, "create", "invoice",
                     entity_id=str(invoice.id),
                     details={"type": payload.invoice_type, "status": "draft"})
    await db.commit()
    # Baseline snapshot for the draft→final diff (#205). Best-effort.
    if getattr(invoice, "status", "draft") == "draft":
        await _capture_draft_baseline(db, invoice.id)
        await db.commit()
    return await _load_invoice(db, invoice.id)


class IssueNoteRequest(BaseModel):
    note_type: str                 # 'credit' | 'debit'
    reason: str
    invoice_date: date | None = None


@router.post("/{invoice_id}/issue-note", response_model=InvoiceResponse, status_code=201)
async def issue_note(
    invoice_id: uuid.UUID,
    payload: IssueNoteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "accountant")),
):
    """Issue a GST Credit or Debit Note against a finalised invoice.

    Creates a DRAFT note (invoice_type credit_note|debit_note) cloning the source
    invoice's party, items and tax settings. The draft is editable before
    finalise; finalise assigns the CN/DN number. Notes live in the invoices
    table but every financial query filters invoice_type IN ('sale','purchase'),
    so notes never pollute sales/GSTR-1-B2B/P&L/receivables — they're surfaced
    explicitly (GSTR-1 CDNR + the party-level receivable adjustment).
    """
    note_type = (payload.note_type or "").lower()
    if note_type not in ("credit", "debit"):
        raise HTTPException(400, "note_type must be 'credit' or 'debit'")
    if not (payload.reason or "").strip():
        raise HTTPException(400, "A reason is required for a credit/debit note")

    src = await _load_invoice(db, invoice_id)
    if src.status != "final":
        raise HTTPException(400, "Notes can only be issued against a finalised invoice")
    if src.invoice_type not in ("sale", "purchase"):
        raise HTTPException(400, "Notes can only be issued against a sale or purchase invoice")

    co, fy = await _get_company_fy(db)
    inv_type = "credit_note" if note_type == "credit" else "debit_note"

    intra = is_intra_state(co.state_code, party_place_of_supply(src.party) if src.party else co.state_code)
    items_data = [{
        "product_id": it.product_id, "description": it.description, "hsn_code": it.hsn_code,
        "quantity": float(it.quantity), "unit": it.unit, "rate": float(it.rate),
        "gst_rate": float(it.gst_rate or 0), "sort_order": it.sort_order,
    } for it in src.items]
    totals = calculate_invoice_totals(
        items=items_data, discount_type=None, discount_value=Decimal("0"),
        freight=Decimal("0"), tcs_rate=Decimal("0"), intra_state=intra,
        tax_type=src.tax_type,
    )

    note = Invoice(
        company_id=co.id, fy_id=fy.id,
        invoice_type=inv_type, tax_type=src.tax_type,
        invoice_no=None,
        invoice_date=(payload.invoice_date or date.today()),
        party_id=src.party_id, customer_name=src.customer_name,
        vehicle_no=src.vehicle_no, transporter_name=src.transporter_name,
        reference_invoice_id=src.id, note_reason=payload.reason.strip(),
        created_by=current_user.id, status="draft",
        payment_status="unpaid", amount_paid=Decimal("0"),
        notes=f"{note_type.title()} note against {src.invoice_no or 'invoice'}",
        **{k: v for k, v in totals.items() if k != "computed_items"},
    )
    db.add(note)
    await db.flush()
    for i, item_data in enumerate(totals["computed_items"]):
        db.add(InvoiceItem(
            invoice_id=note.id, product_id=item_data["product_id"],
            description=item_data.get("description"), hsn_code=item_data.get("hsn_code"),
            quantity=Decimal(str(item_data["quantity"])), unit=item_data["unit"],
            rate=Decimal(str(item_data["rate"])), amount=item_data["amount"],
            gst_rate=Decimal(str(item_data.get("gst_rate", 0))),
            cgst_amount=item_data["cgst_amount"], sgst_amount=item_data["sgst_amount"],
            igst_amount=item_data["igst_amount"], total_amount=item_data["total_amount"],
            sort_order=item_data.get("sort_order", i),
        ))

    from app.routers.audit import log_action
    await log_action(db, co.id, current_user.id, "create", "invoice",
                     entity_id=str(note.id),
                     details={"type": inv_type, "reason": payload.reason, "against": src.invoice_no})
    await db.commit()
    return await _load_invoice(db, note.id)


def _round2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def _create_split_child(
    db: AsyncSession, src: Invoice, co: Company, fy: FinancialYear,
    tax_type: str, item_qtys: list[Decimal], freight: Decimal,
    discount_value, payment_mode: str | None, user_id: uuid.UUID,
) -> Invoice:
    """Create one DRAFT child invoice from a source draft, using per-item split
    quantities and an explicit tax_type.

    item_qtys is aligned with src.items (this child's share of each line). Lines
    with a zero share are dropped. tax_type is set EXPLICITLY here — this path
    intentionally bypasses the party default_payment_mode → tax_type lock so a
    single sale can produce one GST Tax Invoice + one non-GST Bill of Supply.
    Everything else (GST math, round-off, numbering at finalise) reuses the
    normal invoice machinery, so the child behaves like any other invoice.
    """
    intra = is_intra_state(
        co.state_code,
        party_place_of_supply(src.party) if src.party else co.state_code,
    )
    items_data = []
    for it, q in zip(src.items, item_qtys):
        if q <= 0:
            continue
        items_data.append({
            "product_id": it.product_id, "description": it.description,
            "hsn_code": it.hsn_code, "quantity": float(q), "unit": it.unit,
            "rate": float(it.rate), "gst_rate": float(it.gst_rate or 0),
            "sort_order": it.sort_order,
        })
    if not items_data:
        raise HTTPException(400, "Split ratio produces an empty invoice — adjust the split.")

    totals = calculate_invoice_totals(
        items=items_data,
        discount_type=src.discount_type,
        discount_value=(discount_value or Decimal("0")),
        freight=(freight or Decimal("0")),
        tcs_rate=(src.tcs_rate or Decimal("0")),
        intra_state=intra,
        tax_type=tax_type,
    )

    child = Invoice(
        company_id=co.id,
        branch_id=src.branch_id,
        fy_id=fy.id,
        invoice_type=src.invoice_type,
        tax_type=tax_type,
        invoice_no=None,                 # gap-free: assigned at finalise
        invoice_date=src.invoice_date,
        due_date=src.due_date,
        party_id=src.party_id,
        customer_name=src.customer_name,
        token_id=src.token_id,           # both children keep the same token link
        quotation_id=src.quotation_id,
        vehicle_no=src.vehicle_no,
        transporter_name=src.transporter_name,
        gross_weight=src.gross_weight,
        tare_weight=src.tare_weight,
        net_weight=src.net_weight,
        discount_type=src.discount_type,
        discount_value=(discount_value if discount_value is not None else src.discount_value),
        payment_mode=(payment_mode or src.payment_mode),
        notes=src.notes,
        tcs_rate=src.tcs_rate,
        # Transport & dispatch metadata carried over
        royalty_no=src.royalty_no,
        delivery_note=src.delivery_note,
        supplier_ref=src.supplier_ref,
        buyer_order_no=src.buyer_order_no,
        buyer_order_date=src.buyer_order_date,
        dispatch_doc_no=src.dispatch_doc_no,
        dispatch_through=src.dispatch_through,
        destination=src.destination,
        lr_rr_no=src.lr_rr_no,
        terms_of_delivery=src.terms_of_delivery,
        driver_name=src.driver_name,
        created_by=user_id,
        status="draft",
        payment_status="unpaid",
        amount_paid=Decimal("0"),
        **{k: v for k, v in totals.items() if k != "computed_items"},
    )
    db.add(child)
    await db.flush()

    for i, item_data in enumerate(totals["computed_items"]):
        db.add(InvoiceItem(
            invoice_id=child.id,
            product_id=item_data["product_id"],
            description=item_data.get("description"),
            hsn_code=item_data.get("hsn_code"),
            quantity=Decimal(str(item_data["quantity"])),
            unit=item_data["unit"],
            rate=Decimal(str(item_data["rate"])),
            amount=item_data["amount"],
            gst_rate=Decimal(str(item_data.get("gst_rate", 0))),
            cgst_amount=item_data["cgst_amount"],
            sgst_amount=item_data["sgst_amount"],
            igst_amount=item_data["igst_amount"],
            total_amount=item_data["total_amount"],
            sort_order=item_data.get("sort_order", i),
        ))
    return child


@router.post("/{invoice_id}/split", response_model=list[InvoiceResponse], status_code=201)
async def split_invoice(
    invoice_id: uuid.UUID,
    payload: InvoiceSplitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Split ONE draft sale invoice into two child drafts by quantity ratio.

    Use case: a load paid part cash / part UPI where the client wants the cash
    share billed as a non-GST Bill of Supply (CINV) and the UPI share as a GST
    Tax Invoice (INV). The split is by QUANTITY — each line's qty is apportioned
    by the part ratios (last part gets the exact remainder so qty re-sums), the
    same rate applies on both, and GST is charged only on the GST part. Both
    children keep the source token link; the source draft is deleted. Each child
    is a normal draft — finalise assigns its number and drives Tally/GSTR-1 from
    its tax_type exactly as any other invoice.
    """
    src = await _load_invoice(db, invoice_id)
    if src.invoice_type != "sale":
        raise HTTPException(400, "Only sale invoices can be split")
    if src.status != "draft":
        raise HTTPException(400, "Only draft invoices can be split (finalise each child afterwards)")
    if not src.items:
        raise HTTPException(400, "Invoice has no line items to split")

    parts = payload.parts or []
    if len(parts) != 2:
        raise HTTPException(400, "Provide exactly two parts to split into")
    for p in parts:
        if p.tax_type not in ("gst", "non_gst"):
            raise HTTPException(400, "Each part's tax_type must be 'gst' or 'non_gst'")
        if not (0 < p.ratio < 1):
            raise HTTPException(400, "Each part ratio must be between 0 and 1 (exclusive)")
    if abs(sum(p.ratio for p in parts) - 1.0) > 0.001:
        raise HTTPException(400, "Part ratios must sum to 1.0")

    co, fy = await _get_company_fy(db)

    # Per-item split quantities: first part rounded to 3dp, second = remainder
    # (so qty_part0 + qty_part1 == original qty exactly per line).
    r0 = Decimal(str(parts[0].ratio))
    qtys_0, qtys_1 = [], []
    for it in src.items:
        q_total = Decimal(str(it.quantity))
        q0 = (q_total * r0).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        qtys_0.append(q0)
        qtys_1.append(q_total - q0)

    # Apportion freight + flat discount by ratio (percentage discount scales
    # automatically per child, so it's passed through unchanged).
    freight = src.freight or Decimal("0")
    f0 = _round2(freight * r0)
    f1 = freight - f0
    if src.discount_type == "flat":
        dv = src.discount_value or Decimal("0")
        d0 = _round2(dv * r0)
        d1 = dv - d0
    else:
        d0 = d1 = src.discount_value

    child0 = await _create_split_child(
        db, src, co, fy, parts[0].tax_type, qtys_0, f0, d0, parts[0].payment_mode, current_user.id)
    child1 = await _create_split_child(
        db, src, co, fy, parts[1].tax_type, qtys_1, f1, d1, parts[1].payment_mode, current_user.id)

    # Remove the source draft (children now carry the token link + amounts)
    for it in list(src.items):
        await db.delete(it)
    await db.flush()
    await db.delete(src)

    from app.routers.audit import log_action
    await log_action(db, co.id, current_user.id, "split", "invoice", entity_id=str(invoice_id),
                     details={
                         "parts": [{"tax_type": p.tax_type, "ratio": p.ratio} for p in parts],
                         "children": [str(child0.id), str(child1.id)],
                     })
    await db.commit()
    return [await _load_invoice(db, child0.id), await _load_invoice(db, child1.id)]


class GenerateEwbRequest(BaseModel):
    distance_km: int | None = None
    vehicle_no: str | None = None


class CancelEwbRequest(BaseModel):
    reason: str = "2"          # 1=Duplicate 2=Order Cancelled 3=Data entry 4=Others
    remark: str = ""


@router.post("/{invoice_id}/generate-ewb", response_model=InvoiceResponse)
async def generate_invoice_ewb(
    invoice_id: uuid.UUID,
    payload: GenerateEwbRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate (or retry) the E-Way Bill for a finalised invoice via the NIC EWB API."""
    from app.services.eway_service import load_eway_config, generate_for_invoice
    inv = await _load_invoice(db, invoice_id)
    if inv.status != "final":
        raise HTTPException(400, "E-Way Bill can only be generated for a finalised invoice")
    if inv.ewb_status == "generated" and inv.eway_bill_no:
        raise HTTPException(400, f"E-Way Bill {inv.eway_bill_no} already exists for this invoice")
    cfg = await load_eway_config(db)
    if not cfg or not cfg.is_enabled:
        raise HTTPException(400, "E-Way Bill is not configured/enabled (Settings → E-Way Bill)")
    co, _ = await _get_company_fy(db)
    result = await generate_for_invoice(
        db, inv, co, cfg,
        distance_km=(payload.distance_km if payload and payload.distance_km else 0),
        vehicle_no=(payload.vehicle_no if payload else None),
    )
    from app.routers.audit import log_action
    await log_action(db, co.id, current_user.id, "generate_ewb", "invoice", entity_id=str(invoice_id),
                     details={"ewb_no": inv.eway_bill_no, "success": result.success})
    await db.commit()
    if not result.success:
        raise HTTPException(502, result.error_message or "EWB generation failed")
    return await _load_invoice(db, invoice_id)


@router.post("/{invoice_id}/cancel-ewb", response_model=InvoiceResponse)
async def cancel_invoice_ewb(
    invoice_id: uuid.UUID,
    payload: CancelEwbRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "accountant")),
):
    """Cancel the invoice's E-Way Bill within 24h of generation."""
    from app.services.eway_service import load_eway_config, cancel_ewb as _cancel
    inv = await _load_invoice(db, invoice_id)
    if not inv.eway_bill_no or inv.ewb_status != "generated":
        raise HTTPException(400, "No active E-Way Bill to cancel")
    cfg = await load_eway_config(db)
    if not cfg or not cfg.is_enabled:
        raise HTTPException(400, "E-Way Bill is not configured/enabled")
    result = await _cancel(cfg, inv.eway_bill_no,
                           reason=(payload.reason if payload else "2"),
                           remark=(payload.remark if payload else ""))
    if result.success:
        inv.ewb_status = "cancelled"
        inv.ewb_error = None
    else:
        inv.ewb_error = result.error_message
    await db.commit()
    if not result.success:
        raise HTTPException(502, result.error_message or "EWB cancellation failed")
    return await _load_invoice(db, invoice_id)


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    invoice_type: str | None = None,
    status: str | None = None,
    party_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    branch_id=Depends(get_current_branch_id),
):
    co, fy = await _get_company_fy(db)

    filters = [Invoice.company_id == co.id]
    if branch_id is not None:
        filters.append(Invoice.branch_id == branch_id)   # None = all/default branch
    if invoice_type:
        filters.append(Invoice.invoice_type == invoice_type)
    if status:
        filters.append(Invoice.status == status)
    if party_id:
        filters.append(Invoice.party_id == party_id)
    if date_from:
        filters.append(Invoice.invoice_date >= date_from)
    if date_to:
        filters.append(Invoice.invoice_date <= date_to)
    if search:
        filters.append(Invoice.invoice_no.ilike(f"%{search}%"))

    # Hide older revisions — only show the latest revision per invoice chain.
    # An invoice is "superseded" if another invoice exists with a higher revision_no
    # pointing to the same original_invoice_id (or to this invoice as original).
    from sqlalchemy import exists, literal
    NewerRevision = Invoice.__table__.alias("newer")
    superseded = exists(
        select(literal(1)).select_from(NewerRevision).where(
            and_(
                NewerRevision.c.original_invoice_id == func.coalesce(
                    Invoice.original_invoice_id, Invoice.id
                ),
                NewerRevision.c.revision_no > Invoice.revision_no,
            )
        )
    )
    filters.append(~superseded)

    total = (await db.execute(
        select(func.count()).select_from(Invoice).where(and_(*filters))
    )).scalar()

    invoices = (await db.execute(
        select(Invoice)
        .options(selectinload(Invoice.items), selectinload(Invoice.party))
        .where(and_(*filters))
        .order_by(Invoice.invoice_date.desc(), Invoice.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()

    # Batch-resolve creator names (created_by → full_name/username) in one query.
    creator_ids = {inv.created_by for inv in invoices if inv.created_by}
    creators: dict = {}
    if creator_ids:
        for uid, uname, fname in (await db.execute(
            select(User.id, User.username, User.full_name).where(User.id.in_(creator_ids))
        )).all():
            creators[uid] = fname or uname

    # Denormalize token_no and token_date for each invoice
    enriched = []
    for inv in invoices:
        token_no = None
        token_date = None
        if inv.token_id:
            tok = (await db.execute(
                select(Token.token_no, Token.token_date).where(Token.id == inv.token_id)
            )).first()
            if tok:
                token_no, token_date = tok
        # Inject token fields into the pydantic response
        inv_dict = InvoiceResponse.model_validate(inv)
        inv_dict.token_no = token_no
        inv_dict.token_date = token_date
        inv_dict.created_by_name = creators.get(inv.created_by)
        enriched.append(inv_dict)

    return {"items": enriched, "total": total, "page": page, "page_size": page_size}


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = await _load_invoice(db, invoice_id)
    resp = InvoiceResponse.model_validate(inv)
    if inv.token_id:
        tok = (await db.execute(
            select(Token.token_no, Token.token_date).where(Token.id == inv.token_id)
        )).first()
        if tok:
            resp.token_no, resp.token_date = tok
    return resp


@router.put("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: uuid.UUID,
    payload: InvoiceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = await _load_invoice(db, invoice_id)
    if inv.status == "cancelled":
        raise HTTPException(400, "Cannot edit a cancelled invoice")
    if inv.status == "final":
        raise HTTPException(400, "Finalise a new invoice; editing is not allowed after finalisation")

    # Header fields — only editable on draft invoices
    if inv.status == "draft":
        if payload.party_id is not None:
            inv.party_id = payload.party_id
            inv.customer_name = None          # clear walk-in name when party is set
        if payload.customer_name is not None:
            inv.customer_name = payload.customer_name
            inv.party_id = None               # clear party when walk-in name is set
        if payload.invoice_date is not None:
            inv.invoice_date = payload.invoice_date
        if payload.tax_type is not None:
            inv.tax_type = payload.tax_type

    for field in ("vehicle_no", "transporter_name", "eway_bill_no",
                  "discount_type", "discount_value", "freight", "vehicle_rent",
                  "royalty_amount",
                  "tcs_rate", "payment_mode", "notes",
                  "royalty_no", "delivery_note", "supplier_ref",
                  "buyer_order_no", "buyer_order_date",
                  "dispatch_doc_no", "dispatch_through", "destination",
                  "lr_rr_no", "terms_of_delivery", "driver_name"):
        val = getattr(payload, field, None)
        if val is not None:
            setattr(inv, field, val)

    if payload.items is not None:
        for item in list(inv.items):
            await db.delete(item)
        await db.flush()

        co, _ = await _get_company_fy(db)
        party = (await db.execute(select(Party).where(Party.id == inv.party_id))).scalar_one_or_none()
        intra = is_intra_state(co.state_code, party_place_of_supply(party) if party else None)

        items_data = [i.model_dump() for i in payload.items]
        totals = calculate_invoice_totals(
            items=items_data,
            discount_type=inv.discount_type,
            discount_value=inv.discount_value,
            freight=inv.freight,
            tcs_rate=inv.tcs_rate,
            intra_state=intra,
            tax_type=inv.tax_type,
            vehicle_rent=inv.vehicle_rent or Decimal("0"),
            royalty=inv.royalty_amount or Decimal("0"),
        )
        for k, v in totals.items():
            if k != "computed_items":
                setattr(inv, k, v)

        for i, item_data in enumerate(totals["computed_items"]):
            db.add(InvoiceItem(
                invoice_id=inv.id,
                product_id=item_data["product_id"],
                description=item_data.get("description"),
                hsn_code=item_data.get("hsn_code"),
                quantity=Decimal(str(item_data["quantity"])),
                unit=item_data["unit"],
                rate=Decimal(str(item_data["rate"])),
                amount=item_data["amount"],
                gst_rate=Decimal(str(item_data.get("gst_rate", 0))),
                cgst_amount=item_data["cgst_amount"],
                sgst_amount=item_data["sgst_amount"],
                igst_amount=item_data["igst_amount"],
                total_amount=item_data["total_amount"],
                sort_order=item_data.get("sort_order", i),
            ))

    await db.commit()
    return await _load_invoice(db, invoice_id)


# ------------------------------------------------------------------ #
# Advances / prepayments — auto-exhaust against finalised invoices
# ------------------------------------------------------------------ #
async def _advance_auto_apply_enabled(db: AsyncSession) -> bool:
    """Company setting `advance.auto_apply` (app_settings). Default True."""
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key = 'advance.auto_apply'")
        )).scalar()
    except Exception:
        return True
    if row is None:
        return True
    return str(row).strip().lower() not in ("false", "0", "no", "off")


async def _apply_party_advances(db: AsyncSession, inv: Invoice, respect_setting: bool = True) -> Decimal:
    """Exhaust a party's UNALLOCATED advances against `inv` (FIFO, oldest first).

    Sale invoice  → consume the customer's unallocated RECEIPTS.
    Purchase invoice → consume the supplier's unallocated VOUCHERS.

    Reuses the existing settlement primitives verbatim: one InvoicePayment row
    per draw + `_settle_invoice`. Returns the total amount applied. No-op when
    auto-apply is disabled (unless respect_setting=False — the manual path),
    there's no party, the doc isn't sale/purchase, or the invoice is already
    settled. The party's balance is unchanged by this (money moves from receipt
    remainder into amount_paid), so the caller still recomputes once after.
    """
    if not inv.party_id or inv.invoice_type not in ("sale", "purchase"):
        return Decimal("0")
    if respect_setting and not await _advance_auto_apply_enabled(db):
        return Decimal("0")

    from app.models.payment import PaymentReceipt, PaymentVoucher, InvoicePayment
    from app.routers.payments import _settle_invoice

    outstanding = (
        (inv.grand_total or Decimal("0"))
        - (inv.amount_paid or Decimal("0"))
        - (inv.write_off_amount or Decimal("0"))
    )
    if outstanding <= Decimal("0.01"):
        return Decimal("0")

    if inv.invoice_type == "sale":
        Model, link_col, date_col = PaymentReceipt, InvoicePayment.receipt_id, PaymentReceipt.receipt_date
    else:
        Model, link_col, date_col = PaymentVoucher, InvoicePayment.voucher_id, PaymentVoucher.voucher_date

    pays = (await db.execute(
        select(Model)
        .where(Model.party_id == inv.party_id)
        .order_by(date_col.asc(), Model.created_at.asc())
        .with_for_update()
    )).scalars().all()
    if not pays:
        return Decimal("0")

    alloc_rows = (await db.execute(
        select(link_col, func.coalesce(func.sum(InvoicePayment.amount), 0))
        .where(link_col.in_([p.id for p in pays]))
        .group_by(link_col)
    )).all()
    allocated = {r[0]: Decimal(str(r[1] or 0)) for r in alloc_rows}

    applied_total = Decimal("0")
    for p in pays:
        if outstanding <= Decimal("0.01"):
            break
        remaining = (p.amount or Decimal("0")) - allocated.get(p.id, Decimal("0"))
        if remaining <= Decimal("0.01"):
            continue
        amt = min(remaining, outstanding)
        if inv.invoice_type == "sale":
            db.add(InvoicePayment(invoice_id=inv.id, receipt_id=p.id, amount=amt))
        else:
            db.add(InvoicePayment(invoice_id=inv.id, voucher_id=p.id, amount=amt))
        _settle_invoice(inv, amt)
        outstanding -= amt
        applied_total += amt
    return applied_total


async def _sweep_party_deposit(
    db: AsyncSession,
    party_id,
    invoice_type: str,
    background_tasks,
    current_user,
) -> dict:
    """A prepaid DEPOSIT immediately clears the party's OPEN bills oldest-first —
    FINALISING any draft bills as it goes.

    Invoked right after a deposit is recorded: create_receipt (customer →
    'sale') and create_voucher (supplier → 'purchase', non-expense). Gated by the
    `advance.auto_apply` app-setting (default ON). For each open bill oldest-first,
    while the party still holds an unallocated advance from the deposit:
      • draft → **finalise it** (assigns a number + all normal finalise side
        effects — stock, IRN, Tally, notification); finalise then auto-consumes
        the advance against the new invoice (FIFO).
      • final with a balance → apply the advance directly (per-invoice FIFO).
    Stops as soon as the deposit is exhausted, so a bill the deposit can't reach
    is left untouched (drafts are only finalised when the deposit pays for them).
    NEVER raises — a sweep failure must not undo the already-recorded deposit.
    Returns a summary {finalised: [...], cleared: [...], applied: ₹}.
    """
    from app.services.balances import party_advance_remaining, recompute_party_balance
    out: dict = {"finalised": [], "cleared": [], "applied": Decimal("0")}
    if not party_id or invoice_type not in ("sale", "purchase"):
        return out
    if not await _advance_auto_apply_enabled(db):
        return out
    adv_key = "receipt_adv" if invoice_type == "sale" else "voucher_adv"

    # Candidate open bills (drafts + finals), oldest first.
    inv_ids = (await db.execute(
        select(Invoice.id)
        .where(
            Invoice.party_id == party_id,
            Invoice.invoice_type == invoice_type,
            Invoice.status.in_(("draft", "final")),
        )
        .order_by(Invoice.invoice_date.asc(), Invoice.created_at.asc())
    )).scalars().all()

    for inv_id in inv_ids:
        adv = (await party_advance_remaining(db, party_id)).get(adv_key, Decimal("0"))
        if adv <= Decimal("0.01"):
            break  # deposit fully used up
        try:
            inv = await _load_invoice(db, inv_id)
            if inv.status == "draft":
                if not inv.items:
                    continue  # can't finalise an empty draft
                draft_out = (inv.grand_total or Decimal("0")) - (inv.amount_paid or Decimal("0"))
                if draft_out <= Decimal("0.01"):
                    continue  # zero-value draft — never finalise it on a deposit
                if adv < draft_out:
                    continue  # deposit can't FULLY clear this draft → leave it a draft
                before_paid = Decimal(str(inv.amount_paid or 0))
                await finalise_invoice(inv_id, background_tasks, db, current_user)
                fresh = await _load_invoice(db, inv_id)  # post-finalise state
                out["finalised"].append(fresh.invoice_no or str(inv_id))
                out["applied"] += max(Decimal("0"), Decimal(str(fresh.amount_paid or 0)) - before_paid)
                if Decimal(str(fresh.amount_due or 0)) <= Decimal("0.01"):
                    out["cleared"].append(fresh.invoice_no or str(inv_id))
            else:  # already final — apply the advance to any remaining balance
                outstanding = (
                    (inv.grand_total or Decimal("0"))
                    - (inv.amount_paid or Decimal("0"))
                    - (inv.write_off_amount or Decimal("0"))
                )
                if outstanding <= Decimal("0.01"):
                    continue
                applied = await _apply_party_advances(db, inv, respect_setting=False)
                if applied > Decimal("0"):
                    out["applied"] += applied
                    await recompute_party_balance(db, party_id)
                    await db.commit()
                    if Decimal(str(inv.amount_due or 0)) <= Decimal("0.01"):
                        out["cleared"].append(inv.invoice_no or str(inv_id))
        except Exception as e:  # never let the sweep undo the deposit
            import logging
            logging.getLogger(__name__).warning("deposit sweep skipped invoice %s: %s", inv_id, e)
            try:
                await db.rollback()
            except Exception:
                pass
            continue
    return out


async def _supersede_prior_revisions(db: AsyncSession, inv: Invoice, current_user) -> None:
    """A revision REPLACES its predecessor — void the prior finalised version(s)
    of the same invoice so revenue / receivables / GSTR-1 aren't double-counted.

    Sets each prior version's status to **'superseded'**. Every financial query
    filters ``status='final'``, so a superseded row drops out of the party
    balance, sales register, P&L and GST reports automatically — no query
    changes needed. Its payments are released back to the party's advance pool
    (deleted ``InvoicePayment`` links + zeroed paid/due), so the caller's
    ``_apply_party_advances`` re-applies them to this revision. The append-only
    stock ledger is left untouched: the original posted the single physical
    movement once (revisions never re-post at finalise), so it stays correct.
    """
    from sqlalchemy import or_ as _or, delete as _del
    from app.models.payment import InvoicePayment as _IP

    root_id = inv.original_invoice_id or inv.id
    priors = (await db.execute(
        select(Invoice).where(
            _or(Invoice.original_invoice_id == root_id, Invoice.id == root_id),
            Invoice.id != inv.id,
            Invoice.status == "final",
        )
    )).scalars().all()
    for prior in priors:
        await db.execute(_del(_IP).where(_IP.invoice_id == prior.id))
        prior.amount_paid = Decimal("0")
        prior.amount_due = Decimal("0")
        prior.payment_status = "unpaid"
        prior.status = "superseded"
    if priors:
        import logging
        logging.getLogger(__name__).info(
            "Revision %s superseded %d prior version(s)", inv.invoice_no, len(priors))


@router.post("/{invoice_id}/apply-advance", response_model=InvoiceResponse)
async def apply_advance(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually apply the party's advance balance to one finalised invoice."""
    inv = await _load_invoice(db, invoice_id)
    if inv.status != "final":
        raise HTTPException(400, "Advances can only be applied to a finalised invoice")
    if inv.invoice_type not in ("sale", "purchase"):
        raise HTTPException(400, "Advances apply only to sale/purchase invoices")
    if inv.payment_status == "paid":
        raise HTTPException(400, "Invoice is already fully paid")

    applied = await _apply_party_advances(db, inv, respect_setting=False)
    if applied <= 0:
        raise HTTPException(400, "No advance balance available for this party")

    from app.services.balances import recompute_party_balance
    await recompute_party_balance(db, inv.party_id)

    co, _ = await _get_company_fy(db)
    from app.routers.audit import log_action
    await log_action(db, co.id, current_user.id, "apply_advance", "invoice",
                     entity_id=str(invoice_id), details={"applied": str(applied)})
    await db.commit()
    return await _load_invoice(db, invoice_id)


@router.post("/{invoice_id}/approve", response_model=InvoiceResponse)
async def approve_invoice(
    invoice_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "accountant", "store_manager")),
):
    """Approve an invoice's amount and let the SERVER assign its number (P1 #175).

    The offline flow is 'approve now, number at sync': a manager reviews and
    approves the amount during an outage, and when the intent replays the server
    finalises the draft — so the legal GST number is ALWAYS server-assigned, never
    minted offline (zero numbering/compliance surface). Marks the invoice approved
    and, if still a draft, finalises it (assigning invoice_no). Idempotent —
    approving an already-final invoice just stamps the flag.
    """
    inv = await _load_invoice(db, invoice_id)
    if not inv.approved:
        inv.approved = True
        inv.approved_by = current_user.id
        inv.approved_at = datetime.now(timezone.utc)
    if inv.status == "draft":
        # finalise_invoice commits (persisting the approved flag on the same row).
        return await finalise_invoice(invoice_id, background_tasks, db, current_user)
    await db.commit()
    return await _load_invoice(db, invoice_id)


async def find_token_invoice(db: AsyncSession, token_id: uuid.UUID) -> Invoice | None:
    """The draft/finalised sale-or-purchase invoice auto-created for a token.

    Shared by the token-keyed approve endpoint and the offline `invoice.approve`
    replay op (which can only key on token_id — the edge invoice id differs from
    the cloud one)."""
    return (await db.execute(
        select(Invoice)
        .where(Invoice.token_id == token_id)
        .where(Invoice.invoice_type.in_(("sale", "purchase")))
        .order_by(Invoice.created_at.desc()).limit(1)
    )).scalars().first()


@router.post("/approve-token/{token_id}", response_model=InvoiceResponse)
async def approve_token_invoice(
    token_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "accountant", "store_manager")),
):
    """Approve a token's invoice by TOKEN id (P1 #175).

    Same URL shape the edge agent serves offline (`/invoices/approve-token/{id}`),
    so the frontend calls ONE endpoint and the online/offline base-URL switch does
    the rest: online this finds the token's draft invoice and finalises it; offline
    the edge queues an intent that does the same at sync.
    """
    inv = await find_token_invoice(db, token_id)
    if inv is None:
        raise HTTPException(404, "No invoice found for this token yet")
    return await approve_invoice(inv.id, background_tasks, db, current_user)


@router.post("/{invoice_id}/finalise", response_model=InvoiceResponse)
async def finalise_invoice(
    invoice_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inv = await _load_invoice(db, invoice_id)
    if inv.status != "draft":
        raise HTTPException(400, f"Invoice is already {inv.status}")
    if not inv.items:
        raise HTTPException(400, "Cannot finalise an invoice with no items")

    # ── Sanity guard: block physically-impossible / fat-finger lines from the
    #    books & GST (audit #1/#2 — e.g. ₹40-lakh/MT rates, 53,788-MT weights,
    #    the KG-vs-MT 1000× trap). Generous tenant-configurable band; never trips
    #    a realistic invoice. Runs BEFORE a number is assigned, so garbage never
    #    consumes a legal invoice number. The physical weighment + draft survive.
    from app.services.sanity import get_sanity_limits, check_line_sanity
    _slim = await get_sanity_limits(db)
    if _slim.get("enabled", True):
        _problems = check_line_sanity(inv.items, getattr(inv, "net_weight", None), _slim)
        if _problems:
            raise HTTPException(
                400,
                "Invoice failed sanity checks — " + "; ".join(_problems)
                + ". Correct the rate/weight/unit, or an admin can widen the limits "
                "(app_settings → sanity_limits).",
            )

    co, fy = await _get_company_fy(db)

    # Assign invoice_no NOW (gap-free: only finalised invoices consume sequence numbers)
    if not inv.invoice_no:
        if inv.revision_no and inv.revision_no > 1 and inv.original_invoice_id:
            # Revision: append /Rv{n} to the original base number.
            # Each revision gets a distinct invoice_no (e.g. INV/24-25/0001/Rv2),
            # preventing the unique-constraint violation that would occur if two
            # revisions of the same invoice were both assigned the bare base number.
            orig = (await db.execute(
                select(Invoice).where(Invoice.id == inv.original_invoice_id)
            )).scalar_one_or_none()
            if orig and orig.invoice_no:
                base_no = orig.invoice_no.split("/Rv")[0]
                inv.invoice_no = f"{base_no}/Rv{inv.revision_no}"
            else:
                inv.invoice_no = await _next_invoice_no(db, co.id, fy.id, inv.invoice_type, _invoice_prefix(inv.invoice_type, inv.tax_type), branch_id=inv.branch_id)
        else:
            inv.invoice_no = await _next_invoice_no(db, co.id, fy.id, inv.invoice_type, _invoice_prefix(inv.invoice_type, inv.tax_type), branch_id=inv.branch_id)

    inv.status = "final"

    # ── Snapshot agent commission (locks the number against later rate changes) ─
    # Only for the invoice types that earn commission (sale by default; see
    # agents.COMMISSION_INVOICE_TYPES). Skip revisions (share the original's no.).
    if inv.agent_id and not (inv.revision_no and inv.revision_no > 1):
        try:
            from app.routers.agents import COMMISSION_INVOICE_TYPES
            if inv.invoice_type in COMMISSION_INVOICE_TYPES:
                from app.models.agent import Agent
                from app.services.commission import compute_commission
                agent = (await db.execute(
                    select(Agent).where(Agent.id == inv.agent_id)
                )).scalar_one_or_none()
                inv.commission_amount = compute_commission(agent, inv)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Commission snapshot failed for invoice %s: %s", inv.id, e)

    # ── Auto-post product stock movements (finished goods inventory) ──────────
    # Sale finalise → stock down; purchase finalise → stock up. Skip for revisions
    # (share invoice_no with the original → double-count) and for credit/debit
    # notes (a note is a value adjustment, not a goods movement).
    _stock_warning: str | None = None
    if not (inv.revision_no and inv.revision_no > 1) and inv.invoice_type in ("sale", "purchase"):
        try:
            from app.routers.product_stock import post_invoice_movement
            await post_invoice_movement(
                db, inv, action="finalise",
                user_id=current_user.id,
                user_name=current_user.full_name or current_user.username,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Stock auto-posting failed for invoice %s: %s", inv.id, e)
            _stock_warning = (
                f"Invoice finalised but stock balance update failed — "
                f"please re-check Product Inventory. ({type(e).__name__}: {e})"
            )

    # ── eInvoice IRN generation (if enabled + B2B party with GSTIN) ──────────
    # Skip for credit/debit notes in v1 (note-IRN is a future enhancement).
    if inv.invoice_type in ("sale", "purchase"):
        await _try_generate_irn(db, inv, co)

    # ── If this is a revision, compute diff + SUPERSEDE the prior version(s) ──
    is_revision = inv.revision_no and inv.revision_no > 1 and inv.original_invoice_id
    _rev_info: dict = {}
    if is_revision:
        _rev_info = await _finalize_revision_diff(db, inv) or {}
        # A revision REPLACES its predecessor. Void the prior finalised version(s)
        # in the chain so revenue / receivables / GSTR aren't double-counted (they
        # all filter status='final'; 'superseded' drops out automatically). Runs
        # BEFORE advance-apply so any payment freed from the old version can
        # re-apply to this revision.
        await _supersede_prior_revisions(db, inv, current_user)

    # Draft→final field diff (non-revision): what the operator changed between
    # drafting and finalising, for the finalize notification. Computed BEFORE the
    # commit (while inv + items are still loaded). Best-effort — never blocks.
    _draft_changes = ""
    if not is_revision and getattr(inv, "draft_snapshot", None):
        try:
            from app.utils.invoice_diff import compute_invoice_diff, invoice_to_snapshot
            _d = compute_invoice_diff(inv.draft_snapshot, invoice_to_snapshot(inv))
            if _d.get("has_changes"):
                _draft_changes = _format_diff_for_telegram(_d)
        except Exception as _e:  # noqa: BLE001
            import logging as _log
            _log.getLogger(__name__).warning("draft→final diff failed: %s", _e)

    # Finalising creates a receivable/payable (or a note adjustment) → recompute
    # the party's stored balance from source. Covers sale/purchase + credit/debit
    # notes (all finalise through here). First exhaust any advance the party has
    # on account against this new invoice (FIFO) — "advance consumed as they take
    # material". The balance is invariant under this, so recompute runs once after.
    if inv.party_id:
        from app.services.balances import recompute_party_balance
        await _apply_party_advances(db, inv)
        await recompute_party_balance(db, inv.party_id)

    from app.routers.audit import log_action
    await log_action(db, co.id, current_user.id, "finalize", "invoice",
                     entity_id=str(invoice_id),
                     details={
                         "invoice_no": inv.invoice_no,
                         "grand_total": str(inv.grand_total),
                         "revision_no": inv.revision_no,
                     })
    await db.commit()

    # ── Fire invoice_finalized / invoice_revised notification ─────────────────
    event_type = "invoice_revised" if is_revision else "invoice_finalized"
    # Enrich with material + qty from the first line (weighbridge invoices are single-line).
    # grand_total already folds in GST + royalty + vehicle_rent.
    _first_item = (await db.execute(
        select(InvoiceItem).where(InvoiceItem.invoice_id == inv.id).order_by(InvoiceItem.sort_order).limit(1)
    )).scalars().first()
    _material = (_first_item.description if (_first_item and _first_item.description) else "—")
    _qty = (f"{float(_first_item.quantity):g} {_first_item.unit or ''}".strip()
            if _first_item else "—")
    _roy = float(inv.royalty_amount or 0)
    _rent = float(inv.vehicle_rent or 0)
    _notify_ctx = {
        "invoice_no": inv.invoice_no or "—",
        "invoice_date": inv.invoice_date.strftime("%d-%m-%Y") if inv.invoice_date else "—",
        "grand_total": f"{float(inv.grand_total or 0):,.2f}",
        "party_name": inv.party.name if inv.party else "—",
        "party_email": inv.party.email or "" if inv.party else "",
        "party_phone": inv.party.phone or "" if inv.party else "",
        "material": _material,
        "qty": _qty,
        "royalty": f"{_roy:,.2f}" if _roy > 0 else "",
        "vehicle_rent": f"{_rent:,.2f}" if _rent > 0 else "",
        "taxable_amount": f"{float(inv.taxable_amount or 0):,.2f}",
        "tax_amount": f"{float((inv.cgst_amount or 0) + (inv.sgst_amount or 0) + (inv.igst_amount or 0)):,.2f}",
        "freight": f"{float(inv.freight or 0):,.2f}" if float(inv.freight or 0) > 0 else "",
        "company_name": co.name,
        "revision_no": str(inv.revision_no),
        # WHO finalised + WHAT changed (revision: diff vs previous + remark).
        "finalized_by": (current_user.full_name or current_user.username) if current_user else "—",
        "changes": _rev_info.get("changes", "") or _draft_changes,
        "remark": _rev_info.get("remark", ""),
    }
    # Capture tenant slug for background task routing
    _bg_tenant = None
    try:
        from app.multitenancy.context import current_tenant_slug
        _bg_tenant = current_tenant_slug.get()
    except Exception:
        pass

    background_tasks.add_task(
        _send_notification_bg,
        co.id, event_type, _notify_ctx, "invoice", str(invoice_id), _bg_tenant,
    )
    # Always also send invoice_finalized so standard triggers still fire
    if is_revision:
        background_tasks.add_task(
            _send_notification_bg,
            co.id, "invoice_finalized", _notify_ctx, "invoice", str(invoice_id), _bg_tenant,
        )

    # ── GAP-1: Auto-sync finalised GST invoice to Tally (fire-and-forget) ──────
    # Only when Tally is enabled AND auto_sync is on. Mirrors the manual-sync
    # guards (final + tax_type=gst + sale/purchase — non-GST Bills of Supply and
    # credit/debit notes never go to the GST books). The push runs in its own
    # tenant-routed session and never blocks or rolls back the finalisation; on
    # failure tally_synced stays False so the invoice remains in /tally/pending
    # for the accountant to retry manually.
    if inv.invoice_type in ("sale", "purchase", "credit_note", "debit_note"):
        try:
            from app.models.settings import TallyConfig
            _tcfg = (await db.execute(
                select(TallyConfig).where(TallyConfig.company_id == co.id)
            )).scalar_one_or_none()
            # GST invoices always; non-GST only when the tenant opted in.
            _tax_ok = inv.tax_type == "gst" or bool(_tcfg and getattr(_tcfg, "sync_non_gst", False))
            if _tcfg and _tcfg.is_enabled and _tcfg.auto_sync and _tax_ok:
                # Honour the invoice-number prefix filter — don't spawn a task for
                # an invoice that the chokepoint would reject anyway.
                from app.routers.tally import _invoice_matches_prefix
                if _invoice_matches_prefix(inv.invoice_no, getattr(_tcfg, "sync_invoice_prefix", None)):
                    background_tasks.add_task(
                        _auto_sync_tally_bg, co.id, invoice_id, _bg_tenant,
                    )
        except Exception:
            pass

    _inv_orm = await _load_invoice(db, invoice_id)
    from app.schemas.invoice import InvoiceResponse as _InvResp
    _resp = _InvResp.model_validate(_inv_orm)
    if _stock_warning:
        _resp.warnings = [_stock_warning]
    return _resp


@router.post("/{invoice_id}/convert-to-gst", response_model=InvoiceResponse)
async def convert_invoice_to_gst(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upgrade a draft CINV (non-GST/cash) invoice to a GST INV invoice.
    One-way only: INV cannot be downgraded to CINV.
    Recalculates all amounts with the stored per-item GST rates.
    """
    inv = await _load_invoice(db, invoice_id)
    if inv.status != "draft":
        raise HTTPException(400, "Only draft invoices can be converted — finalise and cancel/revise a finalised one")
    if inv.tax_type != "non_gst":
        raise HTTPException(400, "Invoice is already a GST invoice")
    if inv.invoice_type != "sale":
        raise HTTPException(400, "Only sale invoices can be converted to GST")

    co, _ = await _get_company_fy(db)

    # Determine intra-state for CGST+SGST vs IGST split
    intra = is_intra_state(
        co.state_code,
        party_place_of_supply(inv.party) if inv.party else None,
    )

    # Recalculate totals with GST enabled
    items_data = [
        {
            "quantity": item.quantity,
            "rate": item.rate,
            "gst_rate": item.gst_rate or Decimal("0"),
        }
        for item in inv.items
    ]
    totals = calculate_invoice_totals(
        items=items_data,
        discount_type=inv.discount_type,
        discount_value=inv.discount_value or Decimal("0"),
        freight=inv.freight or Decimal("0"),
        tcs_rate=inv.tcs_rate or Decimal("0"),
        intra_state=intra,
        tax_type="gst",
    )

    inv.tax_type = "gst"
    inv.taxable_amount = totals["taxable_amount"]
    inv.cgst_amount = totals["cgst_amount"]
    inv.sgst_amount = totals["sgst_amount"]
    inv.igst_amount = totals["igst_amount"]
    inv.total_amount = totals["total_amount"]
    inv.round_off = totals["round_off"]
    inv.grand_total = totals["grand_total"]
    inv.amount_due = totals["grand_total"] - inv.amount_paid
    inv.tally_synced = False  # mark for re-sync now that it's a GST invoice

    # Update per-item amounts (amount = qty × rate; GST amounts recalculated from it)
    for item, ci in zip(inv.items, totals["computed_items"]):
        item.amount = ci["amount"]
        item.cgst_amount = ci["cgst_amount"]
        item.sgst_amount = ci["sgst_amount"]
        item.igst_amount = ci["igst_amount"]
        item.total_amount = ci["total_amount"]

    from app.routers.audit import log_action
    await log_action(db, co.id, current_user.id, "convert_to_gst", "invoice",
                     entity_id=str(invoice_id),
                     details={"grand_total": str(inv.grand_total)})
    await db.commit()
    return await _load_invoice(db, invoice_id)


async def _load_einvoice_config(db: AsyncSession):
    """Load eInvoice config from app_settings. Returns EInvoiceConfig or None."""
    import json as _json
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key = 'einvoice_config'")
        )).fetchone()
        if not row:
            return None
        from app.integrations.einvoice import EInvoiceConfig
        cfg = EInvoiceConfig.from_dict(_json.loads(row[0]))
        return cfg
    except Exception:
        return None


def _generate_demo_irn(inv, co):
    """
    Generate demo/sample IRN + QR data for PDF preview.
    No NIC API call — uses deterministic fake data based on invoice number.
    The QR encodes a JSON string mimicking the NIC signed QR format.
    """
    import hashlib
    import json as _json
    from datetime import datetime as _dt

    inv_no = inv.invoice_no or "DRAFT"
    # Deterministic fake IRN (64-char hex hash)
    irn_hash = hashlib.sha256(f"DEMO-{inv_no}-{inv.id}".encode()).hexdigest()

    # Fake ack number (numeric, 12 digits)
    ack_no = str(abs(hash(f"ACK-{inv.id}")) % 10**12).zfill(12)

    # QR content mimics NIC signed QR JSON structure
    seller_gstin = getattr(co, "gstin", None) or "29AABCT1332L1ZN"
    buyer_gstin = ""
    if inv.party and hasattr(inv.party, "gstin") and inv.party.gstin:
        buyer_gstin = inv.party.gstin

    qr_data = _json.dumps({
        "SellerGstin": seller_gstin,
        "BuyerGstin": buyer_gstin,
        "DocNo": inv_no,
        "DocTyp": "INV",
        "DocDt": inv.invoice_date.strftime("%d/%m/%Y") if inv.invoice_date else "",
        "TotVal": float(inv.grand_total or 0),
        "Irn": irn_hash,
        "IrnDt": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "DEMO": "This is a demo IRN for preview purposes only",
    }, separators=(",", ":"))

    inv.irn = irn_hash
    inv.irn_ack_no = ack_no
    inv.irn_ack_date = _dt.now()
    inv.irn_qr_code = qr_data
    inv.einvoice_status = "success"
    inv.einvoice_error = None


async def _try_generate_irn(db: AsyncSession, inv, co):
    """
    Attempt eInvoice IRN generation during finalization.
    CRITICAL: Failure does NOT block finalization — invoice stays status=final.
    """
    import logging as _log
    try:
        config = await _load_einvoice_config(db)
        if not config or not config.is_enabled or not config.auto_generate_on_finalize:
            return

        # IRN is ONLY for a GST tax invoice issued to a registered (B2B) party.
        # NEVER for a Bill of Supply / cash (non_gst) invoice, and never for a B2C
        # party with no GSTIN. Checked BEFORE the demo branch so a demo IRN is
        # never stamped on a non-GST / cash invoice either.
        if getattr(inv, "tax_type", None) != "gst":
            return
        if not inv.party or not getattr(inv.party, "gstin", None):
            return

        # Demo mode — generate fake IRN+QR for PDF preview, no NIC API call
        if config.demo_mode:
            _generate_demo_irn(inv, co)
            _log.getLogger(__name__).info("Demo IRN generated for invoice %s", inv.invoice_no)
            return

        from app.integrations.einvoice import EInvoiceClient, build_einvoice_payload

        payload = build_einvoice_payload(inv, co, inv.party)
        client = EInvoiceClient(config)
        result = await client.generate_irn(payload)

        if result.success:
            inv.irn = result.irn
            inv.irn_ack_no = result.ack_no
            inv.irn_ack_date = result.ack_date
            inv.irn_qr_code = result.signed_qr_code
            inv.irn_signed_invoice = result.signed_invoice
            inv.einvoice_status = "success"
            inv.einvoice_error = None
            # IRN-integrated E-Way Bill: NIC returns the EWB no. when EwbDtls
            # (distance) was included in the IRN payload — capture it so the
            # invoice carries both IRN and EWB from a single call.
            if getattr(result, "ewb_no", None):
                inv.eway_bill_no = result.ewb_no
                inv.ewb_date = result.ewb_date
                inv.ewb_valid_till = result.ewb_valid_till
                inv.ewb_status = "generated"
                inv.ewb_error = None
            _log.getLogger(__name__).info("IRN generated: %s for invoice %s", result.irn, inv.invoice_no)
        else:
            inv.einvoice_status = "failed"
            inv.einvoice_error = f"{result.error_code}: {result.error_message}"[:500]
            _log.getLogger(__name__).warning("IRN generation failed for %s: %s", inv.invoice_no, inv.einvoice_error)
    except Exception as e:
        inv.einvoice_status = "failed"
        inv.einvoice_error = str(e)[:500]
        import logging as _log2
        _log2.getLogger(__name__).warning("IRN generation exception for invoice: %s", e)


@router.post("/{invoice_id}/generate-irn", response_model=InvoiceResponse)
async def generate_irn(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually generate or retry IRN for a finalized invoice.
    Used when auto-generation failed or was skipped.
    """
    inv = await _load_invoice(db, invoice_id)
    if inv.status != "final":
        raise HTTPException(400, "Only finalized invoices can have IRN generated")
    if inv.einvoice_status == "success" and inv.irn:
        raise HTTPException(400, f"IRN already exists: {inv.irn}")

    config = await _load_einvoice_config(db)
    if not config or not config.is_enabled:
        raise HTTPException(400, "eInvoice is not configured or not enabled")

    # IRN only applies to a GST tax invoice issued to a registered (B2B) party —
    # never a Bill of Supply / cash invoice, never a B2C party with no GSTIN.
    if getattr(inv, "tax_type", None) != "gst":
        raise HTTPException(400, "IRN applies only to GST tax invoices, not a Bill of Supply / cash invoice")
    if not inv.party or not inv.party.gstin:
        raise HTTPException(400, "eInvoice requires a party with GSTIN (B2B)")

    co, _ = await _get_company_fy(db)

    # Demo mode — generate fake IRN+QR for PDF preview
    if config.demo_mode:
        _generate_demo_irn(inv, co)
        await db.commit()
        return await _load_invoice(db, invoice_id)

    from app.integrations.einvoice import EInvoiceClient, build_einvoice_payload

    payload = build_einvoice_payload(inv, co, inv.party)
    client = EInvoiceClient(config)
    result = await client.generate_irn(payload)

    if result.success:
        inv.irn = result.irn
        inv.irn_ack_no = result.ack_no
        inv.irn_ack_date = result.ack_date
        inv.irn_qr_code = result.signed_qr_code
        inv.irn_signed_invoice = result.signed_invoice
        inv.einvoice_status = "success"
        inv.einvoice_error = None
    else:
        inv.einvoice_status = "failed"
        inv.einvoice_error = f"{result.error_code}: {result.error_message}"[:500]

    await db.commit()
    return await _load_invoice(db, invoice_id)


class CancelIRNRequest(BaseModel):
    reason: str = "1"   # "1" = Duplicate, "2" = Data Entry Mistake
    remark: str = ""


@router.post("/{invoice_id}/cancel-irn", response_model=InvoiceResponse)
async def cancel_irn(
    invoice_id: uuid.UUID,
    body: CancelIRNRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel IRN within 24 hours of generation."""
    inv = await _load_invoice(db, invoice_id)
    if inv.einvoice_status != "success" or not inv.irn:
        raise HTTPException(400, "No active IRN to cancel")

    config = await _load_einvoice_config(db)
    if not config or not config.is_enabled:
        raise HTTPException(400, "eInvoice is not configured or not enabled")

    from app.integrations.einvoice import EInvoiceClient
    client = EInvoiceClient(config)
    result = await client.cancel_irn(inv.irn, body.reason, body.remark)

    if result.success:
        inv.einvoice_status = "cancelled"
        from datetime import datetime as _dt, timezone as _tz
        inv.irn_cancelled_at = _dt.now(_tz.utc)
        inv.einvoice_error = None
    else:
        raise HTTPException(400, f"Failed to cancel IRN: {result.error_message}")

    await db.commit()
    return await _load_invoice(db, invoice_id)


async def _send_notification_bg(
    company_id: uuid.UUID,
    event_type: str,
    context: dict,
    entity_type: str | None = None,
    entity_id: str | None = None,
    tenant_slug: str | None = None,
) -> None:
    """Background-task wrapper: opens its own DB session and fires a notification."""
    import logging as _logging
    try:
        from app.database import get_tenant_session
        from app.integrations.notifications.service import send_notification
        async with await get_tenant_session(tenant_slug) as db:
            await send_notification(db, company_id, event_type, context, entity_type, entity_id)
    except Exception as exc:
        _logging.getLogger(__name__).warning("Background notification failed [%s]: %s", event_type, exc)


async def _auto_sync_tally_bg(
    company_id: uuid.UUID,
    invoice_id: uuid.UUID,
    tenant_slug: str | None = None,
) -> None:
    """GAP-1 — background-task wrapper that pushes a finalised GST invoice to Tally.

    Fire-and-forget: opens its own tenant-routed session, re-checks the guards
    (status=final, tax_type=gst, sale/purchase), reuses the canonical
    ``routers.tally._push_invoice`` builder + HTTP push, and commits the
    ``tally_synced`` flag. NEVER raises — a Tally outage must not affect the
    already-committed finalisation. On failure ``tally_synced`` stays False so
    the invoice still surfaces in ``GET /api/v1/tally/pending`` for manual retry.

    ``_push_invoice`` independently re-reads TallyConfig and returns False if the
    integration was disabled between enqueue and execution, so the auto_sync flag
    is checked both here (to avoid spawning the task) and there (race-safe).
    """
    import logging as _logging
    try:
        from sqlalchemy.orm import selectinload as _selectinload
        from app.database import get_tenant_session
        from app.models.invoice import Invoice as _Invoice
        from app.models.company import Company as _Company
        from app.routers.tally import _push_invoice
        async with await get_tenant_session(tenant_slug) as db:
            inv = (await db.execute(
                select(_Invoice)
                .options(_selectinload(_Invoice.items))
                .where(_Invoice.id == invoice_id, _Invoice.company_id == company_id)
            )).scalar_one_or_none()
            if (
                inv is None
                or inv.status != "final"
                or inv.invoice_type not in ("sale", "purchase", "credit_note", "debit_note")
            ):
                return
            if inv.tax_type != "gst":
                from app.models.settings import TallyConfig as _TC
                _tc = (await db.execute(
                    select(_TC).where(_TC.company_id == company_id)
                )).scalar_one_or_none()
                if not (_tc and getattr(_tc, "sync_non_gst", False)):
                    return
            company = (await db.execute(
                select(_Company).where(_Company.id == company_id)
            )).scalar_one_or_none()
            if company is None:
                return
            success, message = await _push_invoice(inv, company, db)
            await db.commit()
            if not success:
                _logging.getLogger(__name__).warning(
                    "Tally auto-sync failed for invoice %s: %s", invoice_id, message
                )
    except Exception as exc:
        _logging.getLogger(__name__).warning(
            "Tally auto-sync error [invoice %s]: %s", invoice_id, exc
        )


@router.post("/{invoice_id}/move-to-supplement", status_code=201)
async def move_to_supplement(
    invoice_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Move a draft invoice (and its linked token data) into the encrypted
    supplementary_entries table. Requires USB authorization.
    Deletes the invoice and items from normal tables after migration.
    """
    from app.services.usb_guard import check_usb_authorized
    usb_status = await check_usb_authorized(db, user_id=str(current_user.id))
    if not usb_status["authorized"]:
        raise HTTPException(403, "USB key required to move invoices to Supplement")

    inv = await _load_invoice(db, invoice_id)
    if inv.status != "draft":
        raise HTTPException(400, f"Only draft invoices can be moved to Supplement (current: {inv.status})")

    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()

    # Fetch linked token (if any)
    token = None
    if inv.token_id:
        token = (await db.execute(select(Token).where(Token.id == inv.token_id))).scalar_one_or_none()

    # Load party name for customer_name field
    party_name = None
    if inv.party_id:
        party = (await db.execute(select(Party).where(Party.id == inv.party_id))).scalar_one_or_none()
        if party:
            party_name = party.name
    customer_name = party_name or inv.customer_name or ""

    # Compute total amount from invoice
    amount = float(inv.grand_total or 0)
    net_weight_val = float(inv.net_weight or 0) if inv.net_weight else None
    # Rate from first line item
    rate_val = None
    if inv.items:
        rate_val = float(inv.items[0].rate)

    # Assign gap-free supplement entry number via DB sequence
    from sqlalchemy import text as _text
    entry_no_row = (await db.execute(_text("SELECT nextval('supplement_seq')"))).scalar()
    entry_no = f"SE/{entry_no_row:05d}"

    # Encrypt all sensitive fields
    from app.utils.crypto import encrypt, encrypt_float
    customer_enc   = encrypt(customer_name)
    vehicle_enc    = encrypt(inv.vehicle_no or (token.vehicle_no if token else None))
    nw_enc         = encrypt_float(net_weight_val)
    rate_enc       = encrypt_float(rate_val)
    amount_enc     = encrypt_float(amount)
    notes_enc      = encrypt(inv.notes)
    pm_enc         = encrypt(inv.payment_mode or "credit")

    # Encrypt token context
    token_no_enc   = encrypt(str(token.token_no) if token and token.token_no else None)
    token_date_enc = encrypt(str(token.token_date) if token else None)
    gross_enc      = encrypt_float(float(token.gross_weight) if token and token.gross_weight else None)
    tare_enc       = encrypt_float(float(token.tare_weight) if token and token.tare_weight else None)

    import hmac as hmac_mod, hashlib, os
    server_secret = os.environ.get("PRIVATE_DATA_KEY", os.environ.get("SECRET_KEY", "fallback"))
    ihash_data = f"{entry_no}|{inv.invoice_date}|{amount_enc}|{str(current_user.id)}"
    ihash = hmac_mod.new(server_secret.encode(), ihash_data.encode(), hashlib.sha256).hexdigest()

    await db.execute(
        _text("""
            INSERT INTO supplementary_entries
              (company_id, invoice_no, invoice_date,
               customer_name_enc, vehicle_no_enc, net_weight_enc,
               rate_enc, amount_enc, notes_enc,
               customer_name, vehicle_no, net_weight, rate, amount, notes,
               payment_mode, created_by, integrity_hash,
               token_id, token_no_enc, token_date_enc, gross_weight_enc, tare_weight_enc)
            VALUES
              (:cid, :no, :dt,
               :cn, :vn, :nw,
               :rt, :am, :nt,
               NULL, NULL, NULL, NULL, 0, NULL,
               :pm, :uid, :ih,
               :tid, :tno, :tdt, :tgw, :ttw)
        """),
        {
            "cid": str(co.id), "no": entry_no, "dt": inv.invoice_date,
            "cn": customer_enc, "vn": vehicle_enc, "nw": nw_enc,
            "rt": rate_enc, "am": amount_enc, "nt": notes_enc,
            "pm": pm_enc, "uid": str(current_user.id), "ih": ihash,
            "tid": str(inv.token_id) if inv.token_id else None,
            "tno": token_no_enc, "tdt": token_date_enc,
            "tgw": gross_enc, "ttw": tare_enc,
        }
    )

    # Mark token as supplement (hides from normal invoice lists)
    if token:
        token.is_supplement = True

    # Delete invoice items and invoice from normal tables
    for item in list(inv.items):
        await db.delete(item)
    await db.flush()
    await db.delete(inv)

    # Deliberately NO audit log for supplement invoices — supplement entries are private.
    # Also purge any prior audit logs generated for this invoice (e.g. the auto-create draft log).
    await db.execute(
        _text("DELETE FROM audit_log WHERE entity_id = :eid AND entity_type = 'invoice'"),
        {"eid": str(invoice_id)}
    )
    await db.commit()

    return {"entry_no": entry_no, "message": f"Invoice migrated to Supplement as {entry_no}"}


async def _load_token_for_invoice(db: AsyncSession, inv) -> "Token | None":
    """Load the token linked to an invoice, if any."""
    if not inv.token_id:
        return None
    return (await db.execute(select(Token).where(Token.id == inv.token_id))).scalar_one_or_none()


@router.get("/{invoice_id}/pdf")
async def download_pdf(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import json as _json
    from app.routers.app_settings import INVOICE_PRINT_SETTINGS_KEY, _get_raw
    from app.utils.pdf_generator import DEFAULT_INVOICE_PRINT_SETTINGS

    inv = await _load_invoice(db, invoice_id)
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    tok = await _load_token_for_invoice(db, inv)

    # Fetch print settings
    ps_raw = await _get_raw(db, INVOICE_PRINT_SETTINGS_KEY)
    if ps_raw:
        try:
            stored = _json.loads(ps_raw)
            print_settings = {**DEFAULT_INVOICE_PRINT_SETTINGS}
            for section, defaults in DEFAULT_INVOICE_PRINT_SETTINGS.items():
                if isinstance(defaults, dict) and section in stored and isinstance(stored[section], dict):
                    print_settings[section] = {**defaults, **stored[section]}
                elif section in stored:
                    print_settings[section] = stored[section]
        except Exception:
            print_settings = DEFAULT_INVOICE_PRINT_SETTINGS
    else:
        print_settings = DEFAULT_INVOICE_PRINT_SETTINGS

    ctx = invoice_context(inv, co, token=tok, print_settings=print_settings)
    pdf_bytes = generate_pdf("invoice.html", ctx)
    media_type = "application/pdf" if pdf_bytes[:4] == b"%PDF" else "text/html"
    safe_no = (inv.invoice_no or "draft").replace('/', '-')
    filename = f"invoice_{safe_no}.pdf"
    return Response(
        content=pdf_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{invoice_id}/print", response_class=HTMLResponse)
async def print_invoice(
    invoice_id: uuid.UUID,
    format: str = Query("a4"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return an HTML invoice for printing. format=a4 or thermal."""
    inv = await _load_invoice(db, invoice_id)
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    tok = await _load_token_for_invoice(db, inv)
    ctx = invoice_context(inv, co, token=tok)

    if format == "thermal":
        html = render_html("invoice_thermal.html", ctx)
    else:
        # A4: render the standard invoice template and inject auto-print script
        html = render_html("invoice.html", ctx)
        html = html.replace(
            "</body>",
            "<script>window.onload=function(){window.print();window.onafterprint=function(){window.close();};};</script></body>"
        )
    return HTMLResponse(content=html)


# ══════════════════════════════════════════════════════════════════════════════
# Invoice Revision / Amendment Endpoints
# ══════════════════════════════════════════════════════════════════════════════

async def _finalize_revision_diff(db: AsyncSession, inv: Invoice) -> dict:
    """
    After a revised invoice is finalized, compute the diff vs its predecessor
    and update the InvoiceRevision record. Returns {changes, remark} for the
    notification (empty dict if no revision record / on error).
    """
    import logging as _log
    from datetime import datetime as _dt, timezone as _tz
    from app.utils.invoice_diff import compute_invoice_diff, invoice_to_snapshot
    from app.models.invoice_revision import InvoiceRevision

    try:
        # Find the revision record for this to_invoice
        rev_row = (await db.execute(
            select(InvoiceRevision).where(InvoiceRevision.to_invoice_id == inv.id)
        )).scalar_one_or_none()

        if not rev_row:
            return

        # Current (new) snapshot
        new_snap = invoice_to_snapshot(inv)
        # Old snapshot is what was stored at revision creation time
        old_snap = rev_row.snapshot or {}

        diff = compute_invoice_diff(old_snap, new_snap)
        rev_row.diff = diff
        # Keep the human reason (set at revision creation) as the remark; the diff's
        # summary_text is WHAT changed.
        remark = rev_row.change_summary or ""
        changes = diff.get("summary_text", "")
        rev_row.change_summary = changes or remark
        rev_row.finalized_at = _dt.now(_tz.utc)
        await db.flush()
        return {"changes": changes, "remark": remark}

    except Exception as e:
        _log.getLogger(__name__).warning("Failed to compute revision diff: %s", e)
    return {}


@router.post("/{invoice_id}/create-revision", response_model=InvoiceResponse, status_code=201)
async def create_revision(
    invoice_id: uuid.UUID,
    body: CreateRevisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "accountant")),
):
    """
    Create a new revision/amendment of a finalized invoice.

    - Copies the current invoice to a new draft (revision_no + 1)
    - Stores a snapshot of the current version in invoice_revisions
    - Only admin and accountant roles can create revisions
    - The new draft can be edited then finalized to produce Rv<n> invoice_no
    """
    from app.models.invoice_revision import InvoiceRevision
    from app.utils.invoice_diff import invoice_to_snapshot
    from decimal import Decimal

    inv = await _load_invoice(db, invoice_id)
    if inv.status not in ("final",):
        raise HTTPException(400, "Only finalized invoices can be revised")

    # Determine original_invoice_id (root of revision chain)
    original_id = inv.original_invoice_id or inv.id
    new_revision_no = inv.revision_no + 1

    # ── Snapshot current invoice ───────────────────────────────────────────────
    snapshot = invoice_to_snapshot(inv)

    # ── Copy invoice to a new draft ────────────────────────────────────────────
    new_inv = Invoice(
        company_id=inv.company_id,
        fy_id=inv.fy_id,
        invoice_type=inv.invoice_type,
        tax_type=inv.tax_type,
        invoice_no=None,                    # assigned at finalize
        invoice_date=inv.invoice_date,
        due_date=inv.due_date,
        party_id=inv.party_id,
        customer_name=inv.customer_name,
        token_id=inv.token_id,
        quotation_id=inv.quotation_id,
        vehicle_no=inv.vehicle_no,
        transporter_name=inv.transporter_name,
        eway_bill_no=inv.eway_bill_no,
        gross_weight=inv.gross_weight,
        tare_weight=inv.tare_weight,
        net_weight=inv.net_weight,
        subtotal=inv.subtotal,
        discount_type=inv.discount_type,
        discount_value=inv.discount_value,
        discount_amount=inv.discount_amount,
        taxable_amount=inv.taxable_amount,
        cgst_amount=inv.cgst_amount,
        sgst_amount=inv.sgst_amount,
        igst_amount=inv.igst_amount,
        tcs_rate=inv.tcs_rate,
        tcs_amount=inv.tcs_amount,
        freight=inv.freight,
        total_amount=inv.total_amount,
        round_off=inv.round_off,
        grand_total=inv.grand_total,
        payment_mode=inv.payment_mode,
        payment_status="unpaid",            # reset payment status on revision
        amount_paid=Decimal("0"),
        amount_due=inv.grand_total,
        status="draft",
        notes=body.reason or inv.notes,
        tally_synced=False,
        # eInvoice: reset for new revision (will be regenerated if needed)
        irn=None,
        irn_ack_no=None,
        irn_ack_date=None,
        irn_qr_code=None,
        irn_signed_invoice=None,
        einvoice_status="none",
        einvoice_error=None,
        # Revision fields
        revision_no=new_revision_no,
        original_invoice_id=original_id,
        created_by=current_user.id,
    )
    db.add(new_inv)
    await db.flush()  # get new_inv.id

    # ── Copy invoice items ─────────────────────────────────────────────────────
    for item in inv.items:
        from app.models.invoice import InvoiceItem
        new_item = InvoiceItem(
            invoice_id=new_inv.id,
            product_id=item.product_id,
            description=item.description,
            hsn_code=item.hsn_code,
            quantity=item.quantity,
            unit=item.unit,
            rate=item.rate,
            amount=item.amount,
            gst_rate=item.gst_rate,
            cgst_amount=item.cgst_amount,
            sgst_amount=item.sgst_amount,
            igst_amount=item.igst_amount,
            total_amount=item.total_amount,
            sort_order=item.sort_order,
        )
        db.add(new_item)

    # ── Create revision history record ─────────────────────────────────────────
    rev_record = InvoiceRevision(
        original_invoice_id=original_id,
        from_revision_no=inv.revision_no,
        to_revision_no=new_revision_no,
        from_invoice_id=inv.id,
        to_invoice_id=new_inv.id,
        snapshot=snapshot,
        diff=None,
        change_summary=body.reason or f"Revision {new_revision_no} created",
        revised_by=current_user.id,
    )
    db.add(rev_record)

    # ── Audit log ──────────────────────────────────────────────────────────────
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if co:
        from app.routers.audit import log_action
        await log_action(db, co.id, current_user.id, "revised", "invoice",
                         entity_id=str(invoice_id),
                         details={
                             "from_revision": inv.revision_no,
                             "to_revision": new_revision_no,
                             "original_invoice_no": inv.invoice_no,
                             "reason": body.reason,
                         })

    await db.commit()
    return await _load_invoice(db, new_inv.id)


@router.get("/{invoice_id}/revisions", response_model=InvoiceRevisionChain)
async def get_revision_chain(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return all revisions in the chain for an invoice.
    Works whether invoice_id is the original or any revision.
    """
    from app.models.invoice_revision import InvoiceRevision
    from app.schemas.invoice import RevisionHistoryItem, InvoiceRevisionChain
    from app.models.user import User as UserModel

    # Resolve original_id
    inv = await _load_invoice(db, invoice_id)
    original_id = inv.original_invoice_id or inv.id

    # Fetch all invoices in the chain (original + all revisions)
    all_invoices = (await db.execute(
        select(Invoice)
        .options(selectinload(Invoice.items), selectinload(Invoice.party))
        .where(
            (Invoice.id == original_id) |
            (Invoice.original_invoice_id == original_id)
        )
        .order_by(Invoice.revision_no)
    )).scalars().all()

    # Fetch all revision history records
    rev_records = (await db.execute(
        select(InvoiceRevision)
        .where(InvoiceRevision.original_invoice_id == original_id)
        .order_by(InvoiceRevision.to_revision_no)
    )).scalars().all()

    # Enrich revision records with user names
    user_ids = {r.revised_by for r in rev_records if r.revised_by}
    user_map: dict[uuid.UUID, str] = {}
    if user_ids:
        users = (await db.execute(
            select(UserModel).where(UserModel.id.in_(user_ids))
        )).scalars().all()
        user_map = {u.id: u.full_name or u.username for u in users}

    history = [
        RevisionHistoryItem(
            id=r.id,
            original_invoice_id=r.original_invoice_id,
            from_revision_no=r.from_revision_no,
            to_revision_no=r.to_revision_no,
            from_invoice_id=r.from_invoice_id,
            to_invoice_id=r.to_invoice_id,
            change_summary=r.change_summary,
            revised_by_name=user_map.get(r.revised_by) if r.revised_by else None,
            created_at=r.created_at,
            finalized_at=r.finalized_at,
        )
        for r in rev_records
    ]

    # Find latest finalized revision number
    finalized = [i for i in all_invoices if i.status == "final"]
    current_rev = max((i.revision_no for i in finalized), default=1) if finalized else 1

    # Build InvoiceResponse dicts (include token_no/date denormalization)
    from app.schemas.invoice import InvoiceResponse
    invoice_responses = []
    for i in all_invoices:
        d = _invoice_to_dict(i)
        invoice_responses.append(InvoiceResponse.model_validate(d))

    return InvoiceRevisionChain(
        original_invoice_id=original_id,
        current_revision_no=current_rev,
        invoices=invoice_responses,
        history=history,
    )


@router.get("/{invoice_id}/compare/{other_id}")
async def compare_invoices(
    invoice_id: uuid.UUID,
    other_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Compare two invoice versions side-by-side.
    Returns structured diff showing what changed between them.

    invoice_id = the "before" version
    other_id   = the "after" version
    """
    from app.models.invoice_revision import InvoiceRevision
    from app.schemas.invoice import InvoiceResponse, RevisionHistoryItem, InvoiceCompare
    from app.utils.invoice_diff import compute_invoice_diff, invoice_to_snapshot

    inv_a = await _load_invoice(db, invoice_id)
    inv_b = await _load_invoice(db, other_id)

    # Try to find the revision record between them
    rev_record = (await db.execute(
        select(InvoiceRevision).where(
            InvoiceRevision.from_invoice_id == invoice_id,
            InvoiceRevision.to_invoice_id == other_id,
        )
    )).scalar_one_or_none()

    # Build snapshots for diff
    snap_a = inv_a and rev_record.snapshot if rev_record else invoice_to_snapshot(inv_a)
    snap_b = invoice_to_snapshot(inv_b)
    diff = compute_invoice_diff(snap_a, snap_b)

    rev_item = None
    if rev_record:
        rev_item = RevisionHistoryItem(
            id=rev_record.id,
            original_invoice_id=rev_record.original_invoice_id,
            from_revision_no=rev_record.from_revision_no,
            to_revision_no=rev_record.to_revision_no,
            from_invoice_id=rev_record.from_invoice_id,
            to_invoice_id=rev_record.to_invoice_id,
            change_summary=rev_record.change_summary,
            created_at=rev_record.created_at,
            finalized_at=rev_record.finalized_at,
        )

    return InvoiceCompare(
        invoice_a=InvoiceResponse.model_validate(_invoice_to_dict(inv_a)),
        invoice_b=InvoiceResponse.model_validate(_invoice_to_dict(inv_b)),
        diff=diff,
        revision_record=rev_item,
    )


@router.post("/{invoice_id}/cancel", response_model=InvoiceResponse)
async def cancel_invoice(
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "accountant")),
    request: Request = None,
    _bypass_approval: bool = False,
):
    inv = await _load_invoice(db, invoice_id)
    if inv.status == "cancelled":
        raise HTTPException(400, "Already cancelled")
    if inv.invoice_type in ("credit_note", "debit_note"):
        raise HTTPException(
            400,
            "Credit/debit notes cannot be cancelled directly — "
            "issue a counter-note against the original invoice instead."
        )
    # ── Maker-checker: park for a second admin's approval when the toggle is ON ──
    if not _bypass_approval:
        from app.services.approvals import maker_checker_enabled, submit_approval
        if await maker_checker_enabled(db):
            return await submit_approval(
                db, current_user.company_id, current_user, "invoice_cancel",
                f"Cancel invoice {inv.invoice_no or invoice_id}",
                {"invoice_id": str(invoice_id)},
                amount=float(inv.grand_total or inv.total_amount or 0),
            )
    was_finalised = inv.status == "final"
    inv.status = "cancelled"
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()

    # ── Reverse payment/advance allocations (F4) ──────────────────────────────
    # Any receipt/voucher amount allocated to this invoice (incl. an advance
    # auto-applied at finalise) must be RETURNED to the party's unallocated pool
    # when the invoice is cancelled — otherwise the payment stays stranded on a
    # dead invoice and the party is permanently under-credited. Delete the
    # InvoicePayment links and reset the invoice's paid figures; the payments
    # become advances again (recompute below picks that up).
    from app.models.payment import InvoicePayment as _IP
    from sqlalchemy import delete as _delete
    await db.execute(_delete(_IP).where(_IP.invoice_id == inv.id))
    inv.amount_paid = Decimal("0")
    inv.amount_due = Decimal("0")   # cancelled → nothing collectable
    inv.payment_status = "unpaid"

    # ── Reverse product stock movements if the invoice had been finalised ─────
    # Drafts never posted stock so no reversal needed for those.
    if was_finalised and not (inv.revision_no and inv.revision_no > 1):
        try:
            from app.routers.product_stock import post_invoice_movement
            await post_invoice_movement(
                db, inv, action="cancel",
                user_id=current_user.id,
                user_name=current_user.full_name or current_user.username,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Stock reversal failed for cancelled invoice %s: %s", inv.id, e)

    # Cancelling a finalised invoice removes its receivable/payable → recompute.
    if was_finalised and inv.party_id:
        from app.services.balances import recompute_party_balance
        await recompute_party_balance(db, inv.party_id)

    from app.routers.audit import log_action
    if co:
        await log_action(db, co.id, current_user.id, "cancel", "invoice",
                         entity_id=str(invoice_id), details={"invoice_no": inv.invoice_no})
    await db.commit()
    return await _load_invoice(db, invoice_id)


@router.post("/{invoice_id}/write-off", response_model=InvoiceResponse)
async def write_off_invoice(
    invoice_id: uuid.UUID,
    payload: WriteOffRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "accountant")),
    request: Request = None,
    _bypass_approval: bool = False,
):
    """Write off uncollectable balance on a finalised invoice.

    - Amount defaults to the full current balance (amount_due).
    - Records who/when/reason in the invoice row + audit log.
    - Sets payment_status to 'paid' when balance reaches 0 (or 'partial' when
      previous payments + write-off don't fully close it).
    """
    inv = await _load_invoice(db, invoice_id)
    # Write-off = bad-debt closure of an uncollectable RECEIVABLE (a sale). A
    # purchase invoice is a payable we owe the supplier — it is not written off here.
    if inv.invoice_type != "sale":
        raise HTTPException(400, "Write-off applies only to sales invoices (uncollectable receivables). A purchase invoice is a payable and cannot be written off.")
    if inv.status != "final":
        raise HTTPException(400, f"Cannot write off invoice in status '{inv.status}'. Only finalised invoices can be written off.")
    if not payload.reason or not payload.reason.strip():
        raise HTTPException(400, "Reason is required for write-off.")

    # TRUE remaining = grand_total − amount_paid − already-written-off. Recomputed
    # from source (never trust a possibly-stale amount_due), so a write-off can
    # NEVER push amount_paid + write_off_amount past grand_total (the invariant
    # that a fully-paid invoice can't also be written off — H4).
    balance = (Decimal(str(inv.grand_total or 0))
               - Decimal(str(inv.amount_paid or 0))
               - Decimal(str(inv.write_off_amount or 0)))
    if balance <= Decimal("0.01"):
        raise HTTPException(400, "Nothing left to write off — the invoice is already fully paid or written off.")
    requested = Decimal(str(payload.amount)) if payload.amount is not None else balance
    if requested <= 0:
        raise HTTPException(400, "Write-off amount must be positive.")
    if requested > balance:
        raise HTTPException(400, f"Write-off amount ({requested}) exceeds the ₹{balance} still outstanding on this invoice.")

    # ── Maker-checker: park for a second admin's approval when the toggle is ON ──
    if not _bypass_approval:
        from app.services.approvals import maker_checker_enabled, submit_approval
        if await maker_checker_enabled(db):
            return await submit_approval(
                db, current_user.company_id, current_user, "write_off",
                f"Write off ₹{requested:.2f} on invoice {inv.invoice_no or invoice_id}",
                {"invoice_id": str(invoice_id), "body": payload.model_dump(mode="json")},
                amount=float(requested),
            )

    # Apply write-off
    inv.write_off_amount = (Decimal(str(inv.write_off_amount or 0)) + requested).quantize(Decimal("0.01"))
    inv.write_off_reason = payload.reason.strip()
    inv.write_off_at = datetime.now(timezone.utc)
    inv.write_off_by = current_user.id

    # Close the balance — treat write-off as a settlement
    inv.amount_due = (balance - requested).quantize(Decimal("0.01"))
    if inv.amount_due <= Decimal("0.01"):
        inv.payment_status = "paid"
    elif Decimal(str(inv.amount_paid or 0)) > 0:
        inv.payment_status = "partial"

    # ── Accounting: recompute the party's net balance from source ─────────────
    # (write-off now reduces the still-collectable amount via write_off_amount,
    # which recompute_party_balance accounts for — no manual ± drift.)
    from app.services.balances import recompute_party_balance
    await recompute_party_balance(db, inv.party_id)

    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    from app.routers.audit import log_action
    if co:
        await log_action(
            db, co.id, current_user.id, "write_off", "invoice",
            entity_id=str(invoice_id),
            details={
                "invoice_no": inv.invoice_no,
                "amount": str(requested),
                "reason": payload.reason.strip(),
                "balance_before": str(balance),
                "balance_after": str(inv.amount_due),
            },
        )
    await db.commit()
    # Fire-and-forget write-off notification
    _woff_tenant = None
    try:
        from app.multitenancy.context import current_tenant_slug as _cts
        _woff_tenant = _cts.get()
    except Exception:
        pass
    background_tasks.add_task(
        _send_notification_bg,
        current_user.company_id, "invoice_write_off",
        {
            "invoice_no": inv.invoice_no or "—",
            "party_name": getattr(getattr(inv, "party", None), "name", "") or "",
            "amount": f"{requested:.2f}",
            "reason": payload.reason.strip(),
            "balance_after": f"{Decimal(str(inv.amount_due or 0)):.2f}",
            "company_name": co.name if co else "",
        },
        "invoice", str(invoice_id), _woff_tenant,
    )
    return await _load_invoice(db, invoice_id)


# ── Bulk write-off (mass action from Customer 360) ─────────────────────────

from pydantic import BaseModel as _BulkBaseModel


class _BulkWriteOffRequest(_BulkBaseModel):
    invoice_ids: list[uuid.UUID]
    reason: str


@router.post("/write-off-bulk")
async def write_off_bulk(
    payload: _BulkWriteOffRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "accountant")),
    request: Request = None,
    _bypass_approval: bool = False,
):
    """Write off the full remaining balance on every invoice in the list.

    Use case: an accountant decides to close out an entire customer's
    outstanding (e.g. write off all 14 bad invoices for a defaulting
    customer in one click). The reason is shared across all invoices —
    callers should pre-confirm with the user before invoking.

    Skips invoices that are already paid, cancelled, or not finalised.
    Updates party.current_balance once per affected party. Returns a
    summary { written: N, skipped: N, total_amount: X, errors: [...] }.
    """
    if not payload.invoice_ids:
        raise HTTPException(400, "No invoices selected")
    if not payload.reason or not payload.reason.strip():
        raise HTTPException(400, "Reason is required for write-off.")

    # ── Maker-checker: park for a second admin's approval when the toggle is ON ──
    if not _bypass_approval:
        from app.services.approvals import maker_checker_enabled, submit_approval
        if await maker_checker_enabled(db):
            return await submit_approval(
                db, current_user.company_id, current_user, "write_off_bulk",
                f"Bulk write-off of {len(payload.invoice_ids)} invoice(s)",
                {"body": payload.model_dump(mode="json")},
                amount=None,
            )

    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not co:
        raise HTTPException(500, "Company not configured")

    reason_clean = payload.reason.strip()
    now_utc = datetime.now(timezone.utc)
    written = 0
    skipped: list[str] = []
    total_amount = Decimal("0")
    # Accumulate per-party balance deltas so we only touch each party row once.
    party_deltas: dict[uuid.UUID, Decimal] = {}

    from app.routers.audit import log_action

    for inv_id in payload.invoice_ids:
        try:
            inv = await _load_invoice(db, inv_id)
        except HTTPException:
            skipped.append(f"{inv_id}: not found")
            continue
        if inv.status != "final":
            skipped.append(f"{inv.invoice_no or inv_id}: status={inv.status}")
            continue
        if inv.invoice_type != "sale":
            skipped.append(f"{inv.invoice_no or inv_id}: not a sales invoice")
            continue
        # TRUE remaining (never trust amount_due) — a paid invoice can't be written off (H4).
        balance = (Decimal(str(inv.grand_total or 0))
                   - Decimal(str(inv.amount_paid or 0))
                   - Decimal(str(inv.write_off_amount or 0)))
        if balance <= Decimal("0.01"):
            skipped.append(f"{inv.invoice_no or inv_id}: already settled")
            continue

        inv.write_off_amount = (Decimal(str(inv.write_off_amount or 0)) + balance).quantize(Decimal("0.01"))
        inv.write_off_reason = reason_clean
        inv.write_off_at = now_utc
        inv.write_off_by = current_user.id
        inv.amount_due = Decimal("0")
        inv.payment_status = "paid"

        # Note the affected party so we recompute its balance once afterwards.
        if inv.party_id:
            party_deltas[inv.party_id] = Decimal("0")

        await log_action(
            db, co.id, current_user.id, "write_off", "invoice",
            entity_id=str(inv_id),
            details={
                "invoice_no": inv.invoice_no, "amount": str(balance),
                "reason": reason_clean, "bulk": True,
            },
        )
        written += 1
        total_amount += balance

    # Recompute each affected party's balance from source (idempotent, no drift).
    from app.services.balances import recompute_party_balance
    for pid in party_deltas:
        await recompute_party_balance(db, pid)

    await db.commit()
    # Fire-and-forget one summary write-off notification for the bulk action
    if written > 0:
        _woff_tenant = None
        try:
            from app.multitenancy.context import current_tenant_slug as _cts
            _woff_tenant = _cts.get()
        except Exception:
            pass
        background_tasks.add_task(
            _send_notification_bg,
            current_user.company_id, "invoice_write_off",
            {
                "invoice_no": f"{written} invoice(s) — bulk",
                "party_name": f"{len(party_deltas)} customer(s)",
                "amount": f"{total_amount:.2f}",
                "reason": reason_clean,
                "balance_after": "0.00",
                "company_name": co.name if co else "",
            },
            "invoice", None, _woff_tenant,
        )
    return {
        "written": written,
        "skipped": len(skipped),
        "skipped_details": skipped,
        "total_amount": float(total_amount),
        "parties_affected": len(party_deltas),
    }

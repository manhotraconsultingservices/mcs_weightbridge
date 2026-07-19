"""Edge offline routes — the small subset that must work with no internet.

Deliberately mirrors the cloud API SHAPE (same paths under /api/v1) so the
browser can point at the edge with only a base-URL change. The handlers are a
slim local reimplementation over the SQLite mirror — they do NOT import the
cloud routers (which are wired to Postgres tenant-routing + middleware) but they
reuse the same ORM models, so a token written here is identical to one the
server would write.

Numbers minted here: token_no (offline 9000–9999 band) + gate_pass_no (local
per-terminal daily sequence). Invoice numbers are NOT minted offline — the
server assigns them at sync.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, FinancialYear, Party, Product, Token, Vehicle
from agents.edge import intents, numbering
from agents.edge.db import get_sessionmaker

router = APIRouter(prefix="/api/v1")

_ACTIVE = ("OPEN", "FIRST_WEIGHT", "LOADING", "SECOND_WEIGHT")


async def get_db() -> AsyncSession:  # type: ignore[misc]
    async with get_sessionmaker()() as db:
        yield db


def _dec(v: Any) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise HTTPException(422, f"not a number: {v!r}")


async def _company_and_fy(db: AsyncSession) -> tuple[Company, FinancialYear]:
    """Resolve the operating company + financial year from the mirror.

    A real tenant DB holds exactly one company, but rather than trust row order
    we anchor on the ACTIVE financial year (the year the operator is booking
    into) and take its company — robust even if the mirror ever carried a stray
    second company row. Falls back to the most-recent FY, then any company.
    """
    fy = (await db.execute(
        select(FinancialYear).where(FinancialYear.is_active == True)  # noqa: E712
        .order_by(FinancialYear.end_date.desc()).limit(1)
    )).scalar_one_or_none()
    if fy is None:
        fy = (await db.execute(
            select(FinancialYear).order_by(FinancialYear.end_date.desc()).limit(1)
        )).scalar_one_or_none()
    if fy is None:
        raise HTTPException(503, "No financial year mirrored to this terminal")
    co = (await db.execute(
        select(Company).where(Company.id == fy.company_id)
    )).scalar_one_or_none()
    if co is None:
        co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if co is None:
        raise HTTPException(503, "Master data not yet mirrored to this terminal")
    return co, fy


def _token_dict(t: Token) -> dict:
    return {
        "id": str(t.id),
        "token_no": t.token_no,
        "gate_pass_no": t.gate_pass_no,
        "token_date": t.token_date.isoformat() if t.token_date else None,
        "status": t.status,
        "token_type": t.token_type,
        "direction": t.direction,
        "vehicle_no": t.vehicle_no,
        "party_id": str(t.party_id) if t.party_id else None,
        "product_id": str(t.product_id) if t.product_id else None,
        "gross_weight": str(t.gross_weight) if t.gross_weight is not None else None,
        "tare_weight": str(t.tare_weight) if t.tare_weight is not None else None,
        "net_weight": str(t.net_weight) if t.net_weight is not None else None,
        "weight_method": t.weight_method,
        "source": t.source,
        "custom_fields": t.custom_fields,
        "origin": "edge",
    }


# ── Masters (read from the local mirror) ─────────────────────────────────────
@router.get("/parties")
async def list_parties(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Party).order_by(Party.name))).scalars().all()
    return {"items": [{
        "id": str(p.id), "name": p.name, "party_type": p.party_type,
        "gstin": p.gstin, "phone": p.phone,
        "default_payment_mode": getattr(p, "default_payment_mode", None),
    } for p in rows], "total": len(rows)}


@router.get("/products")
async def list_products(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Product).order_by(Product.name))).scalars().all()
    return {"items": [{
        "id": str(p.id), "name": p.name, "unit": p.unit, "hsn_code": p.hsn_code,
        "default_rate": str(p.default_rate) if p.default_rate is not None else None,
        "gst_rate": str(p.gst_rate) if p.gst_rate is not None else None,
        "bulk_density": str(p.bulk_density) if getattr(p, "bulk_density", None) is not None else None,
    } for p in rows], "total": len(rows)}


@router.get("/vehicles")
async def list_vehicles(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Vehicle).order_by(Vehicle.registration_no))).scalars().all()
    return {"items": [{
        "id": str(v.id), "registration_no": v.registration_no,
        "default_tare_weight": str(v.default_tare_weight) if v.default_tare_weight is not None else None,
    } for v in rows], "total": len(rows)}


# ── Token create + weighments ────────────────────────────────────────────────
class TokenCreate(BaseModel):
    vehicle_no: str
    token_type: str = "sale"
    direction: Optional[str] = None
    party_id: Optional[str] = None
    product_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    billing_unit: Optional[str] = None
    remarks: Optional[str] = None
    custom_fields: Optional[dict[str, Any]] = None


class WeightIn(BaseModel):
    weight: float   # kg


@router.post("/tokens", status_code=201)
async def create_token(body: TokenCreate, db: AsyncSession = Depends(get_db)):
    co, fy = await _company_and_fy(db)
    plate = body.vehicle_no.strip().upper()
    if not plate:
        raise HTTPException(422, "vehicle_no required")

    # Duplicate-active-token guard (mirrors the server): one open token per plate.
    dup = (await db.execute(select(Token).where(and_(
        Token.company_id == co.id,
        Token.vehicle_no == plate,
        Token.status.in_(_ACTIVE),
    )).limit(1))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(
            409,
            f"Vehicle {plate} already has an active token (status: {dup.status}). "
            "Complete or cancel it before creating a new one.",
        )

    today = date.today()
    gate_pass_no = await numbering.next_gate_pass_no(db, co.id, _TERMINAL_TAG[0], today)
    tok = Token(
        id=uuid.uuid4(), company_id=co.id, fy_id=fy.id, branch_id=None,
        token_date=today, status="OPEN", token_type=body.token_type,
        direction=body.direction, vehicle_no=plate,
        party_id=uuid.UUID(body.party_id) if body.party_id else None,
        product_id=uuid.UUID(body.product_id) if body.product_id else None,
        vehicle_id=uuid.UUID(body.vehicle_id) if body.vehicle_id else None,
        billing_unit=body.billing_unit, remarks=body.remarks,
        custom_fields=body.custom_fields, weight_method="weighbridge",
        gate_pass_no=gate_pass_no, source="edge",
    )
    db.add(tok)
    await db.flush()
    # Record the replay intent IN THE SAME TRANSACTION as the token. If the
    # commit fails, neither the token nor its intent survives — no orphans.
    await intents.add_intent(
        db, op_type="token.create", method="POST", url="/api/v1/tokens",
        entity_id=str(tok.id),
        payload={
            "id": str(tok.id),
            "token_date": tok.token_date.isoformat(),
            "token_type": tok.token_type,
            "direction": tok.direction or ("outbound" if tok.token_type == "sale" else "inbound"),
            "vehicle_no": tok.vehicle_no,
            "party_id": str(tok.party_id) if tok.party_id else None,
            "product_id": str(tok.product_id) if tok.product_id else None,
            "vehicle_id": str(tok.vehicle_id) if tok.vehicle_id else None,
            "billing_unit": tok.billing_unit,
            "remarks": tok.remarks,
            "custom_fields": tok.custom_fields,
            # #172: keep the offline-printed gate-pass number at sync.
            "gate_pass_no": tok.gate_pass_no,
        },
    )
    await db.commit()
    await db.refresh(tok)
    return _token_dict(tok)


async def _create_op_id(db: AsyncSession, token_id) -> str | None:
    row = await db.execute(text(
        "SELECT op_id FROM intents WHERE entity_id = :e AND op_type = 'token.create' LIMIT 1"
    ), {"e": str(token_id)})
    return row.scalar_one_or_none()


async def _load_token(db: AsyncSession, token_id: str) -> Token:
    try:
        tid = uuid.UUID(token_id)
    except ValueError:
        raise HTTPException(422, "bad token id")
    t = (await db.execute(select(Token).where(Token.id == tid))).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "token not found")
    return t


@router.post("/tokens/{token_id}/first-weight")
async def first_weight(token_id: str, body: WeightIn, db: AsyncSession = Depends(get_db)):
    t = await _load_token(db, token_id)
    if t.status not in ("OPEN", "LOADING"):
        raise HTTPException(409, f"token is {t.status}, cannot take first weight")
    # sale (outbound): 1st = tare (empty). purchase (inbound): 1st = gross (loaded).
    t.first_weight = _dec(body.weight)
    t.first_weight_type = "tare" if t.token_type == "sale" else "gross"
    t.first_weight_at = datetime.now(timezone.utc)
    t.status = "FIRST_WEIGHT"
    await intents.add_intent(
        db, op_type="token.first_weight", method="POST",
        url=f"/api/v1/tokens/{t.id}/first-weight", entity_id=str(t.id),
        depends_on=await _create_op_id(db, t.id),
        payload={"weight_kg": str(t.first_weight), "is_manual": False},
    )
    await db.commit()
    await db.refresh(t)
    return _token_dict(t)


@router.post("/tokens/{token_id}/second-weight")
async def second_weight(token_id: str, body: WeightIn, db: AsyncSession = Depends(get_db)):
    t = await _load_token(db, token_id)
    if t.status not in ("FIRST_WEIGHT", "SECOND_WEIGHT", "LOADING"):
        raise HTTPException(409, f"token is {t.status}, cannot take second weight")
    if t.first_weight is None:
        raise HTTPException(409, "first weight not recorded")
    t.second_weight = _dec(body.weight)
    w1, w2 = t.first_weight, t.second_weight
    gross, tare = (w1, w2) if w1 >= w2 else (w2, w1)
    t.gross_weight, t.tare_weight = gross, tare
    t.net_weight = gross - tare
    t.second_weight_at = datetime.now(timezone.utc)
    t.token_no = await numbering.next_token_no(db, t.company_id, t.token_date)
    t.status = "COMPLETED"
    t.completed_at = datetime.now(timezone.utc)
    await intents.add_intent(
        db, op_type="token.second_weight", method="POST",
        url=f"/api/v1/tokens/{t.id}/second-weight", entity_id=str(t.id),
        depends_on=await _create_op_id(db, t.id),
        # #172: send the 9000-band token_no printed on the slip so the server
        # keeps it verbatim at sync (slip number == final number).
        payload={"weight_kg": str(t.second_weight), "is_manual": False,
                 "token_no": t.token_no},
    )
    await db.commit()
    await db.refresh(t)
    return _token_dict(t)


@router.post("/invoices/approve-token/{token_id}")
async def approve_token_invoice(token_id: str, db: AsyncSession = Depends(get_db)):
    """Offline invoice approval (P1 #175): a manager reviews a completed token's
    amount and approves it. The edge does not hold the invoice — it emits an
    intent keyed by token_id; at sync the second-weight replay auto-creates the
    draft invoice on the cloud and this intent approves + finalises it, so the
    legal GST number is assigned by the SERVER (never minted offline)."""
    t = await _load_token(db, token_id)
    if t.status != "COMPLETED":
        raise HTTPException(409, "token is not completed — cannot approve its invoice yet")
    # Idempotent: one approve intent per token.
    existing = (await db.execute(text(
        "SELECT op_id FROM intents WHERE entity_id = :e AND op_type = 'invoice.approve' LIMIT 1"
    ), {"e": token_id})).scalar_one_or_none()
    if existing:
        return {"ok": True, "already_queued": True, "op_id": existing}
    sw_op = (await db.execute(text(
        "SELECT op_id FROM intents WHERE entity_id = :e AND op_type = 'token.second_weight' LIMIT 1"
    ), {"e": token_id})).scalar_one_or_none()
    op = await intents.add_intent(
        db, op_type="invoice.approve", method="POST",
        url=f"/api/v1/invoices/approve-token/{token_id}", entity_id=token_id,
        depends_on=sw_op, payload={"token_id": token_id},
    )
    await db.commit()
    return {"ok": True, "op_id": op}


@router.get("/tokens")
async def list_tokens(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Token).where(Token.token_date == date.today())
        .order_by(Token.created_at.desc())
    )).scalars().all()
    return {"items": [_token_dict(t) for t in rows], "total": len(rows)}


# ── helpers ──────────────────────────────────────────────────────────────────
# Module-level holder so the configured terminal tag reaches numbering without
# threading it through every call. Set once by create_app().
_TERMINAL_TAG = ["B1"]


def set_terminal_tag(tag: str) -> None:
    _TERMINAL_TAG[0] = (tag or "B1").strip() or "B1"

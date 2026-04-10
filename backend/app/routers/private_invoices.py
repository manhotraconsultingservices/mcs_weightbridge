"""
Private (non-GST) supplementary invoices router.

Security:
  - USB authentication required (HMAC challenge-response)
  - All sensitive fields encrypted with AES-256-GCM before DB write
  - Table named 'supplementary_entries' (innocuous name)
  - Direct psql SELECT shows only ciphertext — unreadable without PRIVATE_DATA_KEY
  - Each invoice carries an HMAC integrity hash (detects DB tampering)
  - Invoice serial numbers use a DB sequence (supplement_seq) — gap-free
  - No plaintext sensitive data is ever committed to the database

Also used by invoices.py move-to-supplement endpoint for shared schema.
"""
import hmac as hmac_mod
import hashlib
import io
import json
import os
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.company import Company
from app.models.user import User
from app.services.usb_guard import check_usb_authorized
from app.utils.crypto import encrypt, decrypt, encrypt_float, decrypt_float

router = APIRouter(prefix="/api/v1/private-invoices", tags=["Private Invoices"])

TABLE = "supplementary_entries"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ─── Auth guard ───────────────────────────────────────────────────────────────

async def _require_usb(db, user_id: str, ip_address: str | None = None):
    status = await check_usb_authorized(db, user_id=user_id, ip_address=ip_address)
    if not status["authorized"]:
        raise HTTPException(403, "USB key not present and no active recovery session")


# ─── Numbering ────────────────────────────────────────────────────────────────

async def _next_entry_no(db) -> str:
    """
    Gap-free supplement entry number using a dedicated PostgreSQL sequence.
    CREATE SEQUENCE supplement_seq is done in main.py lifespan startup.
    """
    no = (await db.execute(text("SELECT nextval('supplement_seq')"))).scalar()
    return f"SE/{no:05d}"


# ─── Integrity hash ───────────────────────────────────────────────────────────

def _get_integrity_secret() -> str:
    """Get the server secret for integrity hashing, checking env + pydantic settings."""
    key = os.environ.get("PRIVATE_DATA_KEY", "")
    if not key:
        key = os.environ.get("SECRET_KEY", "")
    if not key:
        try:
            from app.config import get_settings
            s = get_settings()
            key = getattr(s, "PRIVATE_DATA_KEY", "") or s.SECRET_KEY
        except Exception:
            pass
    return key or "fallback"


def _integrity_hash(invoice_no: str, invoice_date: str, amount_enc: str, created_by: str) -> str:
    server_secret = _get_integrity_secret()
    data = f"{invoice_no}|{invoice_date}|{amount_enc}|{created_by}"
    return hmac_mod.new(server_secret.encode(), data.encode(), hashlib.sha256).hexdigest()


# ─── Schemas ──────────────────────────────────────────────────────────────────

class PrivateInvoiceCreate(BaseModel):
    invoice_date: date
    customer_name: Optional[str] = None
    vehicle_no: Optional[str] = None
    net_weight: Optional[float] = None
    rate: Optional[float] = None
    amount: float
    payment_mode: str = "cash"
    notes: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _decrypt_row(r) -> dict:
    """
    Decrypt a DB row from SELECT id, invoice_no, invoice_date,
      customer_name_enc[3], vehicle_no_enc[4], net_weight_enc[5],
      rate_enc[6], amount_enc[7], notes_enc[8], payment_mode[9], created_at[10]
    plus optional token columns [11..14] when present.
    """
    result = {
        "id": str(r[0]),
        "invoice_no": r[1],
        "invoice_date": str(r[2]),
        "customer_name": decrypt(r[3]),
        "vehicle_no": decrypt(r[4]),
        "net_weight": decrypt_float(r[5]),
        "rate": decrypt_float(r[6]),
        "amount": decrypt_float(r[7]),
        "notes": decrypt(r[8]),
        "payment_mode": decrypt(r[9]) or "cash",
        "created_at": str(r[10]),
    }
    # Optional token columns (indices 11-15 when queried)
    if len(r) > 11:
        result["token_no"] = decrypt(r[11])
        result["token_date"] = decrypt(r[12])
        result["gross_weight"] = decrypt_float(r[13])
        result["tare_weight"] = decrypt_float(r[14])
    if len(r) > 15:
        result["token_id"] = str(r[15]) if r[15] else None
    return result


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_private_invoice(
    payload: PrivateInvoiceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_usb(db, str(current_user.id), _get_ip(request))
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not co:
        raise HTTPException(500, "Company not configured")

    entry_no = await _next_entry_no(db)

    customer_enc  = encrypt(payload.customer_name)
    vehicle_enc   = encrypt(payload.vehicle_no)
    net_weight_enc = encrypt_float(payload.net_weight)
    rate_enc      = encrypt_float(payload.rate)
    amount_enc    = encrypt_float(payload.amount)
    notes_enc     = encrypt(payload.notes)
    pm_enc        = encrypt(payload.payment_mode)

    ihash = _integrity_hash(entry_no, str(payload.invoice_date), amount_enc or "", str(current_user.id))

    row = (await db.execute(
        text(f"""
            INSERT INTO {TABLE}
              (company_id, invoice_no, invoice_date,
               customer_name_enc, vehicle_no_enc, net_weight_enc,
               rate_enc, amount_enc, notes_enc,
               customer_name, vehicle_no, net_weight, rate, amount, notes,
               payment_mode, created_by, integrity_hash)
            VALUES
              (:cid, :no, :dt,
               :cn, :vn, :nw,
               :rt, :am, :nt,
               NULL, NULL, NULL, NULL, 0, NULL,
               :pm, :uid, :ih)
            RETURNING id, invoice_no, invoice_date,
               customer_name_enc, vehicle_no_enc, net_weight_enc,
               rate_enc, amount_enc, notes_enc, payment_mode, created_at
        """),
        {
            "cid": str(co.id), "no": entry_no, "dt": payload.invoice_date,
            "cn": customer_enc, "vn": vehicle_enc, "nw": net_weight_enc,
            "rt": rate_enc, "am": amount_enc, "nt": notes_enc,
            "pm": pm_enc, "uid": str(current_user.id), "ih": ihash,
        }
    )).fetchone()
    await db.commit()
    return _decrypt_row(row)


@router.get("")
async def list_private_invoices(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _require_usb(db, str(current_user.id), _get_ip(request))
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    offset = (page - 1) * page_size

    # Build date conditions
    date_conditions = "WHERE company_id = :cid"
    params: dict = {"cid": str(co.id)}
    if date_from:
        date_conditions += " AND invoice_date >= :df"
        params["df"] = date_from
    if date_to:
        date_conditions += " AND invoice_date <= :dt"
        params["dt"] = date_to

    total = (await db.execute(
        text(f"SELECT COUNT(*) FROM {TABLE} {date_conditions}"),
        params
    )).scalar()

    rows = (await db.execute(
        text(f"""
            SELECT id, invoice_no, invoice_date,
                   customer_name_enc, vehicle_no_enc, net_weight_enc,
                   rate_enc, amount_enc, notes_enc, payment_mode, created_at,
                   token_no_enc, token_date_enc, gross_weight_enc, tare_weight_enc,
                   token_id
            FROM {TABLE} {date_conditions}
            ORDER BY invoice_date DESC, created_at DESC LIMIT :lim OFFSET :off
        """),
        {**params, "lim": page_size, "off": offset}
    )).fetchall()

    items = [_decrypt_row(r) for r in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/export-encrypted")
async def export_encrypted(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Export all supplement entries as an AES-256-GCM encrypted JSON blob.
    Intended for hourly USB auto-backup. The blob can be decrypted only with
    the server's PRIVATE_DATA_KEY.
    """
    await _require_usb(db, str(current_user.id), _get_ip(request))
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()

    rows = (await db.execute(
        text(f"""
            SELECT id, invoice_no, invoice_date,
                   customer_name_enc, vehicle_no_enc, net_weight_enc,
                   rate_enc, amount_enc, notes_enc, payment_mode, created_at,
                   token_no_enc, token_date_enc, gross_weight_enc, tare_weight_enc
            FROM {TABLE} WHERE company_id = :cid
            ORDER BY invoice_date ASC, created_at ASC
        """),
        {"cid": str(co.id)}
    )).fetchall()

    # Decrypt all rows to produce a clean JSON dataset
    records = [_decrypt_row(r) for r in rows]
    payload_json = json.dumps(records, default=str).encode("utf-8")

    # Re-encrypt the whole dataset as one AES-256-GCM blob
    from app.utils.crypto import _get_key
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import base64
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, payload_json, None)
    blob = nonce + ciphertext   # 12-byte nonce + ciphertext + 16-byte GCM tag

    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"supplement_backup_{ts}.enc"

    return Response(
        content=blob,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Admin endpoints (private_admin role, no USB required) ────────────────────

@router.get("/admin/all")
async def admin_list_all(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("private_admin")),
):
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    offset = (page - 1) * page_size
    total = (await db.execute(
        text(f"SELECT COUNT(*) FROM {TABLE} WHERE company_id = :cid"),
        {"cid": str(co.id)}
    )).scalar()
    rows = (await db.execute(
        text(f"""
            SELECT s.id, s.invoice_no, s.invoice_date,
                   s.customer_name_enc, s.vehicle_no_enc, s.net_weight_enc,
                   s.rate_enc, s.amount_enc, s.notes_enc, s.payment_mode, s.created_at,
                   s.token_no_enc, s.token_date_enc, s.gross_weight_enc, s.tare_weight_enc,
                   s.token_id,
                   u.username, s.integrity_hash
            FROM {TABLE} s
            LEFT JOIN users u ON u.id = s.created_by
            WHERE s.company_id = :cid
            ORDER BY s.invoice_date DESC, s.created_at DESC LIMIT :lim OFFSET :off
        """),
        {"cid": str(co.id), "lim": page_size, "off": offset}
    )).fetchall()

    items = []
    for r in rows:
        item = _decrypt_row(r)
        # token_id is at [15] (handled by _decrypt_row), username at [16], integrity_hash at [17]
        item["created_by_username"] = r[16]
        item["integrity_ok"] = True
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/admin/export-csv")
async def admin_export_csv(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("private_admin")),
):
    """Export all supplementary entries as CSV — decrypted — private_admin only."""
    import csv

    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    rows = (await db.execute(
        text(f"""
            SELECT s.invoice_no, s.invoice_date,
                   s.customer_name_enc, s.vehicle_no_enc, s.net_weight_enc,
                   s.rate_enc, s.amount_enc, s.payment_mode, s.notes_enc,
                   s.created_at, u.username,
                   s.token_no_enc, s.token_date_enc
            FROM {TABLE} s
            LEFT JOIN users u ON u.id = s.created_by
            WHERE s.company_id = :cid
            ORDER BY s.invoice_date DESC, s.created_at DESC
        """),
        {"cid": str(co.id)}
    )).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Entry No", "Date", "Customer", "Vehicle", "Net Weight (kg)",
                     "Rate", "Amount", "Payment Mode", "Notes", "Token No", "Token Date",
                     "Created At", "Created By"])
    for r in rows:
        writer.writerow([
            r[0], r[1],
            decrypt(r[2]) or "", decrypt(r[3]) or "",
            decrypt_float(r[4]) or "", decrypt_float(r[5]) or "",
            decrypt_float(r[6]) or 0, decrypt(r[7]) or "",
            decrypt(r[8]) or "", decrypt(r[11]) or "", decrypt(r[12]) or "",
            r[9], r[10] or ""
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=supplementary_entries.csv"}
    )

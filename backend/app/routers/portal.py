"""Customer self-service portal (Horizon 2).

Separate auth realm from staff. Customers log in with email + password and can
ONLY see their own party's data (party_id is baked into the JWT and enforced on
every query). Tokens carry scope='customer' so they can't be used on staff
endpoints. Read-only in v1 (+ change password); payment is "static UPI" — we
show the company VPA/QR, payments are reconciled manually by staff.
"""
import json
import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Form, Header, status
from fastapi.responses import Response
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import get_db
from app.models.company import Company
from app.models.customer_user import CustomerUser
from app.models.invoice import Invoice
from app.models.party import Party
from app.models.payment import PaymentReceipt
from app.utils.auth import verify_password, hash_password, create_access_token
from app.utils.pdf_generator import generate_pdf, invoice_context

settings = get_settings()
router = APIRouter(prefix="/api/v1/portal", tags=["Customer Portal"])


# ── Customer auth dependency ─────────────────────────────────────────────────
# A standalone bearer check (NOT the staff OAuth2 scheme). Requires
# scope='customer' in the JWT so staff tokens can't reach portal endpoints and
# vice-versa.

async def get_customer(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> CustomerUser:
    cred_exc = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    if not authorization or not authorization.lower().startswith("bearer "):
        raise cred_exc
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise cred_exc
    if payload.get("scope") != "customer" or not payload.get("sub"):
        raise cred_exc
    cu = (await db.execute(
        select(CustomerUser).where(CustomerUser.id == uuid.UUID(payload["sub"]))
    )).scalar_one_or_none()
    if not cu or not cu.is_active:
        raise cred_exc
    return cu


# ── Login ────────────────────────────────────────────────────────────────────

class PortalLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    party_name: str
    email: str


@router.post("/login", response_model=PortalLoginResponse)
async def portal_login(
    email: str = Form(...),
    password: str = Form(...),
    tenant_slug: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    async def _auth(session: AsyncSession):
        cu = (await session.execute(
            select(CustomerUser).where(func.lower(CustomerUser.email) == email.strip().lower())
        )).scalar_one_or_none()
        if not cu or not cu.is_active or not verify_password(password, cu.password_hash):
            raise HTTPException(401, "Invalid email or password")
        party = (await session.execute(select(Party).where(Party.id == cu.party_id))).scalar_one_or_none()
        cu.last_login_at = datetime.now(timezone.utc)
        await session.commit()
        claims = {"sub": str(cu.id), "scope": "customer", "party": str(cu.party_id)}
        if tenant_slug:
            claims["tenant"] = tenant_slug
        token = create_access_token(claims, expires_delta=timedelta(hours=12))
        return PortalLoginResponse(access_token=token,
                                   party_name=(party.name if party else "Customer"),
                                   email=cu.email)

    if settings.MULTI_TENANT and tenant_slug:
        from app.multitenancy.registry import tenant_registry
        tenant = await tenant_registry.get_tenant(tenant_slug)
        if not tenant or not tenant.is_active:
            raise HTTPException(404, "Unknown company code")
        factory = await tenant_registry.get_session_factory(tenant_slug)
        async with factory() as tdb:
            return await _auth(tdb)
    return await _auth(db)


# ── Portal data endpoints (customer-scoped) ──────────────────────────────────

@router.get("/me")
async def portal_me(cu: CustomerUser = Depends(get_customer), db: AsyncSession = Depends(get_db)):
    party = (await db.execute(select(Party).where(Party.id == cu.party_id))).scalar_one_or_none()
    if not party:
        raise HTTPException(404, "Account not found")
    # Outstanding (final unpaid sale invoices net of credit/debit notes)
    invs = (await db.execute(
        select(Invoice).where(
            Invoice.party_id == cu.party_id, Invoice.status == "final",
        )
    )).scalars().all()
    outstanding = Decimal("0")
    for inv in invs:
        if inv.invoice_type == "sale" and inv.payment_status != "paid":
            outstanding += (inv.grand_total or Decimal("0")) - (inv.amount_paid or Decimal("0"))
        elif inv.invoice_type == "credit_note":
            outstanding -= (inv.grand_total or Decimal("0"))
        elif inv.invoice_type == "debit_note":
            outstanding += (inv.grand_total or Decimal("0"))
    if outstanding < 0:
        outstanding = Decimal("0")
    return {
        "party_name": party.name, "email": cu.email,
        "gstin": party.gstin, "phone": party.phone,
        "city": party.billing_city, "state": party.billing_state,
        "outstanding": float(outstanding),
        "credit_limit": float(party.credit_limit or 0),
    }


@router.get("/invoices")
async def portal_invoices(cu: CustomerUser = Depends(get_customer), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Invoice).where(
            Invoice.party_id == cu.party_id,
            Invoice.status == "final",
            Invoice.invoice_type.in_(("sale", "credit_note", "debit_note")),
        ).order_by(Invoice.invoice_date.desc(), Invoice.created_at.desc()).limit(200)
    )).scalars().all()
    return {"items": [{
        "id": str(i.id), "invoice_no": i.invoice_no, "invoice_type": i.invoice_type,
        "invoice_date": i.invoice_date.isoformat() if i.invoice_date else None,
        "due_date": i.due_date.isoformat() if i.due_date else None,
        "grand_total": float(i.grand_total or 0),
        "amount_paid": float(i.amount_paid or 0),
        "amount_due": float((i.grand_total or 0) - (i.amount_paid or 0)),
        "payment_status": i.payment_status,
        "eway_bill_no": i.eway_bill_no,
    } for i in rows]}


@router.get("/invoices/{invoice_id}/pdf")
async def portal_invoice_pdf(invoice_id: uuid.UUID, cu: CustomerUser = Depends(get_customer),
                             db: AsyncSession = Depends(get_db)):
    inv = (await db.execute(
        select(Invoice).options(selectinload(Invoice.items), selectinload(Invoice.party))
        .where(Invoice.id == invoice_id)
    )).scalar_one_or_none()
    if not inv or inv.party_id != cu.party_id:
        raise HTTPException(404, "Invoice not found")   # ownership enforced
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    pdf = generate_pdf("invoice.html", invoice_context(inv, co))
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{inv.invoice_no or "invoice"}.pdf"'})


@router.get("/statement")
async def portal_statement(cu: CustomerUser = Depends(get_customer), db: AsyncSession = Depends(get_db)):
    pays = (await db.execute(
        select(PaymentReceipt).where(PaymentReceipt.party_id == cu.party_id)
        .order_by(PaymentReceipt.created_at.desc()).limit(50)
    )).scalars().all()
    return {"payments": [{
        "receipt_no": p.receipt_no,
        "date": p.payment_date.isoformat() if getattr(p, "payment_date", None) else (p.created_at.date().isoformat() if p.created_at else None),
        "amount": float(p.amount or 0),
        "mode": getattr(p, "payment_mode", None),
    } for p in pays]}


@router.get("/payment-info")
async def portal_payment_info(cu: CustomerUser = Depends(get_customer), db: AsyncSession = Depends(get_db)):
    """Static UPI / bank details for the customer to pay (manual reconciliation)."""
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    upi = {}
    row = (await db.execute(text("SELECT value FROM app_settings WHERE key = 'upi_config'"))).fetchone()
    if row:
        try:
            upi = json.loads(row[0])
        except Exception:
            upi = {}
    return {
        "upi_vpa": upi.get("vpa", ""),
        "payee_name": upi.get("payee_name", co.name if co else ""),
        "upi_enabled": bool(upi.get("enabled", False)) and bool(upi.get("vpa")),
        "bank_name": getattr(co, "bank_name", None) if co else None,
        "account_no": getattr(co, "account_number", None) if co else None,
        "ifsc": getattr(co, "ifsc_code", None) if co else None,
    }


class PortalChangePassword(BaseModel):
    current_password: str
    new_password: str


@router.put("/change-password")
async def portal_change_password(req: PortalChangePassword, cu: CustomerUser = Depends(get_customer),
                                 db: AsyncSession = Depends(get_db)):
    if not verify_password(req.current_password, cu.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if len(req.new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters")
    cu.password_hash = hash_password(req.new_password)
    await db.commit()
    return {"message": "Password updated"}

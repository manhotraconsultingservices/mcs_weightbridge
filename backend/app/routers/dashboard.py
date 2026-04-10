"""
Dashboard router — summary stats, recent tokens, top customers, charts.

When ?include_supplement=true AND the caller has an active USB session,
supplement (private invoice) amounts are merged into revenue, customer totals,
daily trend, and payment pipeline figures.  Tonnage and token counts already
include supplement tokens because those rows remain in the tokens table
(only the linked invoice is deleted on move-to-supplement).
"""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text

from app.database import get_db
from app.dependencies import get_current_user
from app.models.invoice import Invoice
from app.models.token import Token
from app.models.party import Party
from app.models.product import Product
from app.models.payment import PaymentReceipt
from app.models.company import Company, FinancialYear
from app.models.user import User
from app.services.usb_guard import check_usb_authorized
from app.utils.crypto import decrypt, decrypt_float

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])

TABLE = "supplementary_entries"


# ── Supplement helper ─────────────────────────────────────────────────────────

async def _supplement_rows(db: AsyncSession, co_id, date_from=None, date_to=None):
    """
    Return decrypted supplement entries for dashboard aggregation.
    Each row: { date, amount, customer }
    Amount is the supplement invoice amount (cash, treated as revenue).
    """
    conditions = ["company_id = :cid"]
    params: dict = {"cid": str(co_id)}
    if date_from:
        conditions.append("invoice_date >= :df")
        params["df"] = date_from
    if date_to:
        conditions.append("invoice_date <= :dt")
        params["dt"] = date_to

    rows = (await db.execute(
        text(f"""
            SELECT invoice_date, amount_enc, customer_name_enc
            FROM {TABLE}
            WHERE {" AND ".join(conditions)}
        """),
        params,
    )).fetchall()

    result = []
    for r in rows:
        amount = decrypt_float(r[1]) or 0.0
        customer = decrypt(r[2]) or "Unknown"
        result.append({"date": r[0], "amount": amount, "customer": customer})
    return result


async def _usb_ok(db: AsyncSession, user_id: str) -> bool:
    status = await check_usb_authorized(db, user_id=user_id)
    return bool(status.get("authorized"))


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
async def get_summary(
    include_supplement: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = date.today()
    month_start = today.replace(day=1)

    # Resolve whether supplement data may actually be included
    with_supp = include_supplement and await _usb_ok(db, str(current_user.id))

    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()

    # ── Token counts (exclude supplement tokens when USB not active) ──────────
    supp_filter_today = [] if with_supp else [Token.is_supplement == False]
    tokens_today = (await db.execute(
        select(func.count(Token.id))
        .where(Token.token_date == today, *supp_filter_today)
    )).scalar() or 0

    tokens_month = (await db.execute(
        select(func.count(Token.id))
        .where(Token.token_date >= month_start, Token.token_date <= today,
               *supp_filter_today)
    )).scalar() or 0

    # ── Revenue (invoices) ────────────────────────────────────────────────────
    revenue_today = float((await db.execute(
        select(func.coalesce(func.sum(Invoice.grand_total), 0))
        .where(Invoice.invoice_type == "sale", Invoice.invoice_date == today, Invoice.status == "final")
    )).scalar() or Decimal(0))

    revenue_month = float((await db.execute(
        select(func.coalesce(func.sum(Invoice.grand_total), 0))
        .where(
            Invoice.invoice_type == "sale",
            Invoice.invoice_date >= month_start,
            Invoice.invoice_date <= today,
            Invoice.status == "final",
        )
    )).scalar() or Decimal(0))

    # ── Tonnage (exclude supplement tokens when USB not active) ───────────────
    tonnage_today = float((await db.execute(
        select(func.coalesce(func.sum(Token.net_weight), 0))
        .where(Token.token_date == today, Token.status == "COMPLETED",
               *supp_filter_today)
    )).scalar() or Decimal(0))

    # ── Outstanding ───────────────────────────────────────────────────────────
    outstanding = float((await db.execute(
        select(func.coalesce(func.sum(Invoice.amount_due), 0))
        .where(Invoice.invoice_type == "sale", Invoice.status == "final", Invoice.payment_status != "paid")
    )).scalar() or Decimal(0))

    # ── Recent tokens ─────────────────────────────────────────────────────────
    # Include supplement tokens only when USB authorized
    recent_q = (
        select(Token, Party)
        .outerjoin(Party, Token.party_id == Party.id)
        .order_by(Token.created_at.desc())
        .limit(10)
    )
    if not with_supp:
        recent_q = recent_q.where(Token.is_supplement == False)

    recent_tokens = []
    for token, party in (await db.execute(recent_q)).all():
        recent_tokens.append({
            "id": str(token.id),
            "token_no": token.token_no,
            "token_date": token.token_date.isoformat(),
            "status": token.status,
            "token_type": token.token_type,
            "vehicle_no": token.vehicle_no,
            "party_name": party.name if party else None,
            "net_weight": float(token.net_weight) if token.net_weight else None,
            "is_supplement": token.is_supplement,
        })

    # ── Top customers (invoices) ──────────────────────────────────────────────
    top_map: dict[str, float] = {}
    inv_customers = await db.execute(
        select(Party.name, func.sum(Invoice.grand_total).label("total"))
        .join(Invoice, Invoice.party_id == Party.id)
        .where(Invoice.invoice_type == "sale", Invoice.status == "final")
        .group_by(Party.id, Party.name)
    )
    for name, total in inv_customers.all():
        top_map[name] = top_map.get(name, 0.0) + float(total)

    # ── Supplement additions ──────────────────────────────────────────────────
    if with_supp and co:
        supp_today = await _supplement_rows(db, co.id, date_from=today, date_to=today)
        supp_month = await _supplement_rows(db, co.id, date_from=month_start, date_to=today)

        revenue_today += sum(r["amount"] for r in supp_today)
        revenue_month += sum(r["amount"] for r in supp_month)

        for r in supp_month:
            top_map[r["customer"]] = top_map.get(r["customer"], 0.0) + r["amount"]

    top_customers = sorted(
        [{"name": k, "total": v} for k, v in top_map.items()],
        key=lambda x: x["total"],
        reverse=True,
    )[:5]

    return {
        "tokens_today": tokens_today,
        "revenue_today": revenue_today,
        "tonnage_today": tonnage_today,
        "outstanding": outstanding,
        "revenue_month": revenue_month,
        "tokens_month": tokens_month,
        "recent_tokens": recent_tokens,
        "top_customers": top_customers,
        "supplement_included": with_supp,
    }


# ── Charts ────────────────────────────────────────────────────────────────────

@router.get("/charts")
async def get_charts(
    include_supplement: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = date.today()
    day30_ago = today - timedelta(days=29)

    with_supp = include_supplement and await _usb_ok(db, str(current_user.id))

    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()

    # ── 1. Daily revenue + tonnage trend (last 30 days) ──────────────────────
    daily_revenue_rows = await db.execute(
        select(
            Invoice.invoice_date,
            func.coalesce(func.sum(Invoice.grand_total), 0).label("revenue"),
        )
        .where(
            Invoice.invoice_type == "sale",
            Invoice.status == "final",
            Invoice.invoice_date >= day30_ago,
            Invoice.invoice_date <= today,
        )
        .group_by(Invoice.invoice_date)
        .order_by(Invoice.invoice_date)
    )
    revenue_by_date: dict[date, float] = {
        row.invoice_date: float(row.revenue) for row in daily_revenue_rows.all()
    }

    # Add supplement daily revenue
    if with_supp and co:
        supp_30 = await _supplement_rows(db, co.id, date_from=day30_ago, date_to=today)
        for r in supp_30:
            revenue_by_date[r["date"]] = revenue_by_date.get(r["date"], 0.0) + r["amount"]

    daily_tonnage_rows = await db.execute(
        select(
            Token.token_date,
            func.coalesce(func.sum(Token.net_weight), 0).label("tonnage"),
        )
        .where(
            Token.status == "COMPLETED",
            Token.token_date >= day30_ago,
            Token.token_date <= today,
        )
        .group_by(Token.token_date)
        .order_by(Token.token_date)
    )
    tonnage_by_date: dict[date, float] = {
        row.token_date: float(row.tonnage) / 1000 for row in daily_tonnage_rows.all()
    }

    daily_trend = []
    cur = day30_ago
    while cur <= today:
        daily_trend.append({
            "date": cur.strftime("%d %b"),
            "revenue": round(revenue_by_date.get(cur, 0.0), 2),
            "tonnage": round(tonnage_by_date.get(cur, 0.0), 2),
        })
        cur += timedelta(days=1)

    # ── 2. Top products by tonnage (completed tokens) ─────────────────────────
    # Supplement tokens still have product_id in tokens table → already counted
    product_q = (
        select(
            Product.name,
            func.coalesce(func.sum(Token.net_weight), 0).label("net_kg"),
        )
        .join(Token, Token.product_id == Product.id)
        .where(Token.status == "COMPLETED")
    )
    if not with_supp:
        product_q = product_q.where(Token.is_supplement == False)

    product_rows = await db.execute(
        product_q.group_by(Product.id, Product.name)
        .order_by(func.sum(Token.net_weight).desc())
        .limit(8)
    )
    product_tonnage = [
        {"product": row.name, "tonnage": round(float(row.net_kg) / 1000, 2)}
        for row in product_rows.all()
    ]

    # ── 3. Token status distribution (current month) ──────────────────────────
    month_start = today.replace(day=1)
    status_q = (
        select(Token.status, func.count(Token.id).label("cnt"))
        .where(Token.token_date >= month_start, Token.token_date <= today)
    )
    if not with_supp:
        status_q = status_q.where(Token.is_supplement == False)
    status_rows = await db.execute(status_q.group_by(Token.status))
    token_status = {row.status: row.cnt for row in status_rows.all()}

    # ── 4. Payment pipeline (last 6 months) ───────────────────────────────────
    six_months_ago = (today.replace(day=1) - timedelta(days=150)).replace(day=1)
    pipeline_rows = await db.execute(
        select(
            func.extract("year", Invoice.invoice_date).label("yr"),
            func.extract("month", Invoice.invoice_date).label("mo"),
            Invoice.payment_status,
            func.coalesce(func.sum(Invoice.grand_total), 0).label("total"),
        )
        .where(
            Invoice.invoice_type == "sale",
            Invoice.status == "final",
            Invoice.invoice_date >= six_months_ago,
            Invoice.invoice_date <= today,
        )
        .group_by("yr", "mo", Invoice.payment_status)
        .order_by("yr", "mo")
    )
    pipeline_map: dict = {}
    for row in pipeline_rows.all():
        key = (int(row.yr), int(row.mo))
        if key not in pipeline_map:
            pipeline_map[key] = {"paid": 0.0, "unpaid": 0.0}
        if row.payment_status == "paid":
            pipeline_map[key]["paid"] += float(row.total)
        else:
            pipeline_map[key]["unpaid"] += float(row.total)

    # Supplement entries are all cash/immediate → add to "paid"
    if with_supp and co:
        supp_6m = await _supplement_rows(db, co.id, date_from=six_months_ago, date_to=today)
        for r in supp_6m:
            d = r["date"]
            key = (d.year, d.month)
            if key not in pipeline_map:
                pipeline_map[key] = {"paid": 0.0, "unpaid": 0.0}
            pipeline_map[key]["paid"] += r["amount"]

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    payment_pipeline = [
        {
            "month": f"{month_names[mo - 1]} {yr}",
            "paid": round(v["paid"], 2),
            "unpaid": round(v["unpaid"], 2),
        }
        for (yr, mo), v in sorted(pipeline_map.items())
    ]

    return {
        "daily_trend": daily_trend,
        "product_tonnage": product_tonnage,
        "token_status": token_status,
        "payment_pipeline": payment_pipeline,
        "supplement_included": with_supp,
    }

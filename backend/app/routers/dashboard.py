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
    # Tracks both display name → total *and* party_id so the UI can link to /customers/:id.
    top_map: dict[str, float] = {}
    id_map: dict[str, str] = {}   # name → party_id (None for supplement walk-in)
    inv_customers = await db.execute(
        select(Party.id, Party.name, func.sum(Invoice.grand_total).label("total"))
        .join(Invoice, Invoice.party_id == Party.id)
        .where(Invoice.invoice_type == "sale", Invoice.status == "final")
        .group_by(Party.id, Party.name)
    )
    for pid, name, total in inv_customers.all():
        top_map[name] = top_map.get(name, 0.0) + float(total)
        id_map[name] = str(pid)

    # ── Supplement additions ──────────────────────────────────────────────────
    if with_supp and co:
        supp_today = await _supplement_rows(db, co.id, date_from=today, date_to=today)
        supp_month = await _supplement_rows(db, co.id, date_from=month_start, date_to=today)

        revenue_today += sum(r["amount"] for r in supp_today)
        revenue_month += sum(r["amount"] for r in supp_month)

        for r in supp_month:
            top_map[r["customer"]] = top_map.get(r["customer"], 0.0) + r["amount"]

    top_customers = sorted(
        [
            {"name": k, "total": v, "party_id": id_map.get(k)}
            for k, v in top_map.items()
        ],
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


# ── Owner exception aggregator (Sprint 2: exception-first dashboard) ──────────
#
# Returns the 4 exception buckets owners actually act on, plus a
# traffic-light status for the new home page. One round-trip; the new
# OwnerDashboardPage renders entirely from this response.
#
@router.get("/exceptions")
async def dashboard_exceptions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import json
    from app.models.product_stock import ProductStock
    from app.models.compliance import ComplianceItem
    from app.models.production import ProductionCycle

    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not co:
        return {
            "status": "healthy",
            "headline": "No company configured",
            "overdue_customers": {"items": [], "count": 0, "total_balance": 0},
            "low_stock_products": {"items": [], "count": 0},
            "compliance_expiring": {"items": [], "count": 0},
            "yield_variance": None,
            "today_revenue": {"today": 0, "median_30d": 0, "variance_pct": 0},
            "today_purchases": {"today": 0, "median_30d": 0, "variance_pct": 0},
            "payables": {"total": 0, "supplier_count": 0},
        }
    today = date.today()

    # Helper bucket
    def _bucket(days: int) -> str:
        if days <= 0: return "current"
        if days <= 30: return "1-30"
        if days <= 60: return "31-60"
        if days <= 90: return "61-90"
        return "90+"

    # ── 1. Overdue customers (sale invoices past due_date, unpaid) ───────────
    # Use func.min(due_date) and compute days in Python — avoids cross-vendor
    # quirks with `today - column` arithmetic in SQL.
    overdue_items: list[dict] = []
    overdue_total = 0.0
    try:
        overdue_rows = (await db.execute(
            select(
                Invoice.party_id,
                Party.name.label("party_name"),
                Party.phone.label("phone"),
                func.sum(Invoice.grand_total - Invoice.amount_paid).label("balance"),
                func.min(Invoice.due_date).label("oldest_due_date"),
            )
            .join(Party, Invoice.party_id == Party.id)
            .where(
                Invoice.company_id == co.id,
                Invoice.invoice_type == "sale",
                Invoice.status == "final",
                Invoice.payment_status != "paid",
                Invoice.due_date.isnot(None),
                Invoice.due_date < today,
            )
            .group_by(Invoice.party_id, Party.name, Party.phone)
            .order_by(func.min(Invoice.due_date).asc())
        )).all()

        for r in overdue_rows:
            days = (today - r.oldest_due_date).days if r.oldest_due_date else 0
            bal = float(r.balance or 0)
            overdue_items.append({
                "party_id": str(r.party_id),
                "party_name": r.party_name,
                "phone": r.phone,
                "balance": bal,
                "oldest_overdue_days": days,
                "aging_bucket": _bucket(days),
            })
            overdue_total += bal
    except Exception as exc:
        # Don't kill the whole dashboard if this one slice fails — log + continue
        import logging
        logging.getLogger(__name__).warning("dashboard.exceptions: overdue query failed: %s", exc)

    # ── 2. Low product stock ─────────────────────────────────────────────────
    low_stock_items: list[dict] = []
    try:
        stock_rows = (await db.execute(
            select(ProductStock, Product.name, Product.unit)
            .join(Product, ProductStock.product_id == Product.id)
            .where(
                ProductStock.company_id == co.id,
                ProductStock.current_stock <= ProductStock.min_stock_level,
                ProductStock.min_stock_level > 0,   # ignore products with no threshold
            )
            .order_by((ProductStock.current_stock - ProductStock.min_stock_level).asc())
        )).all()
        low_stock_items = [
            {
                "product_id": str(s.ProductStock.product_id),
                "product_name": name,
                "unit": unit,
                "current_stock": float(s.ProductStock.current_stock or 0),
                "min_stock_level": float(s.ProductStock.min_stock_level or 0),
                "deficit": float((s.ProductStock.min_stock_level or 0) - (s.ProductStock.current_stock or 0)),
                "is_out": float(s.ProductStock.current_stock or 0) == 0,
            }
            for s, name, unit in stock_rows
        ]
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("dashboard.exceptions: low-stock query failed: %s", exc)

    # ── 3. Compliance expiring (≤60 days or already expired) ─────────────────
    # Use the same threshold pattern as the compliance router; pull from app_settings.
    def _setting(k: str, default: int) -> int:
        try:
            r = db.sync_session.execute(text("SELECT value FROM app_settings WHERE key = :k"), {"k": k}).fetchone()
            if r and r[0]:
                return int(r[0])
        except Exception:
            pass
        return default
    critical_days = 30
    warning_days = 60
    try:
        for k, default in (("compliance_critical_days", 30), ("compliance_warning_days", 60)):
            r = (await db.execute(
                text("SELECT value FROM app_settings WHERE key = :k"), {"k": k},
            )).fetchone()
            if r and r[0]:
                v = int(r[0])
                if k == "compliance_critical_days": critical_days = v
                else: warning_days = v
    except Exception:
        pass

    comp_items: list[dict] = []
    try:
        comp_rows = (await db.execute(
            select(ComplianceItem)
            .where(
                ComplianceItem.company_id == co.id,
                ComplianceItem.is_active == True,
                ComplianceItem.expiry_date.isnot(None),
                ComplianceItem.expiry_date <= today + timedelta(days=warning_days),
            )
            .order_by(ComplianceItem.expiry_date.asc())
        )).scalars().all()
        for c in comp_rows:
            delta = (c.expiry_date - today).days
            if delta < 0:
                level = "expired"
            elif delta <= critical_days:
                level = "critical"
            else:
                level = "warning"
            comp_items.append({
                "item_id": str(c.id),
                "name": c.name,
                "type": c.item_type,
                "expiry_date": c.expiry_date.isoformat(),
                "days_to_expiry": delta,
                "alert_level": level,
            })
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("dashboard.exceptions: compliance query failed: %s", exc)

    # ── 4. Today's production yield vs target ────────────────────────────────
    yield_variance = None
    target_yield_pct = round(0.975 * 0.97 * 0.94 * 0.91 * 100, 2)  # industry default
    try:
        stage_row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key = 'production.stage_defaults'")
        )).fetchone()
        if stage_row and stage_row[0]:
            stages = json.loads(stage_row[0])
            if isinstance(stages, list) and len(stages) == 4:
                pct = 1.0
                for s in stages:
                    pct *= float(s.get("expected_yield_pct", 100)) / 100.0
                target_yield_pct = round(pct * 100, 2)
    except Exception:
        pass

    try:
        cycle_today = (await db.execute(
            select(ProductionCycle)
            .where(ProductionCycle.company_id == co.id, ProductionCycle.cycle_date == today)
        )).scalar_one_or_none()
        if cycle_today and cycle_today.input_kg and cycle_today.input_kg > 0:
            out_total = float((await db.execute(
                text("SELECT COALESCE(SUM(output_kg), 0) FROM production_cycle_outputs WHERE cycle_id = :cid"),
                {"cid": str(cycle_today.id)},
            )).scalar() or 0)
            today_yield_pct = round(out_total / float(cycle_today.input_kg) * 100, 2)
            variance = round(today_yield_pct - target_yield_pct, 2)
            if variance >= -1.0:
                yvs = "on_track"
            elif variance >= -5.0:
                yvs = "below"
            else:
                yvs = "critical"
            yield_variance = {
                "cycle_id": str(cycle_today.id),
                "today_yield_pct": today_yield_pct,
                "target_yield_pct": target_yield_pct,
                "variance_pct": variance,
                "is_finalised": cycle_today.is_finalised,
                "status": yvs,
            }
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("dashboard.exceptions: yield query failed: %s", exc)

    # ── 5. Today's revenue vs 30-day median ──────────────────────────────────
    today_rev = 0.0
    median_30d = 0.0
    rev_variance_pct = 0.0
    try:
        month_start = today - timedelta(days=30)
        daily_rev_rows = (await db.execute(
            select(Invoice.invoice_date, func.coalesce(func.sum(Invoice.grand_total), 0))
            .where(
                Invoice.company_id == co.id,
                Invoice.invoice_type == "sale",
                Invoice.status == "final",
                Invoice.invoice_date >= month_start,
                Invoice.invoice_date <= today,
            )
            .group_by(Invoice.invoice_date)
        )).all()
        daily_map = {d: float(amt) for d, amt in daily_rev_rows}
        today_rev = daily_map.get(today, 0.0)
        past = [daily_map.get(month_start + timedelta(days=i), 0.0) for i in range(30)]
        past_sorted = sorted(past)
        median_30d = past_sorted[len(past_sorted) // 2] if past_sorted else 0.0
        if median_30d > 0:
            rev_variance_pct = round((today_rev - median_30d) / median_30d * 100, 1)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("dashboard.exceptions: revenue query failed: %s", exc)

    today_revenue = {
        "today": round(today_rev, 2),
        "median_30d": round(median_30d, 2),
        "variance_pct": rev_variance_pct,
    }

    # ── 6. Today's purchases vs 30-day median (supplier / farmer side) ───────
    today_pur = 0.0
    median_pur_30d = 0.0
    pur_variance_pct = 0.0
    try:
        m_start = today - timedelta(days=30)
        pur_rows = (await db.execute(
            select(Invoice.invoice_date, func.coalesce(func.sum(Invoice.grand_total), 0))
            .where(
                Invoice.company_id == co.id,
                Invoice.invoice_type == "purchase",
                Invoice.status == "final",
                Invoice.invoice_date >= m_start,
                Invoice.invoice_date <= today,
            )
            .group_by(Invoice.invoice_date)
        )).all()
        pmap = {d: float(amt) for d, amt in pur_rows}
        today_pur = pmap.get(today, 0.0)
        past_p = [pmap.get(m_start + timedelta(days=i), 0.0) for i in range(30)]
        ps = sorted(past_p)
        median_pur_30d = ps[len(ps) // 2] if ps else 0.0
        if median_pur_30d > 0:
            pur_variance_pct = round((today_pur - median_pur_30d) / median_pur_30d * 100, 1)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("dashboard.exceptions: purchases query failed: %s", exc)

    today_purchases = {
        "today": round(today_pur, 2),
        "median_30d": round(median_pur_30d, 2),
        "variance_pct": pur_variance_pct,
    }

    # ── 7. Payables — money owed to suppliers/farmers (unpaid purchase bills) ─
    payables_total = 0.0
    payables_count = 0
    try:
        prow = (await db.execute(
            select(
                func.coalesce(func.sum(Invoice.grand_total - Invoice.amount_paid), 0),
                func.count(func.distinct(Invoice.party_id)),
            )
            .where(
                Invoice.company_id == co.id,
                Invoice.invoice_type == "purchase",
                Invoice.status == "final",
                Invoice.payment_status != "paid",
            )
        )).first()
        if prow:
            payables_total = float(prow[0] or 0)
            payables_count = int(prow[1] or 0)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("dashboard.exceptions: payables query failed: %s", exc)

    payables = {"total": round(payables_total, 2), "supplier_count": payables_count}

    # ── Traffic-light overall status + headline ──────────────────────────────
    # critical: anything expired, anything fully out of stock, or critical yield miss
    # warning: any overdue, any low stock, any expiring compliance, yield below target
    # healthy: clean across the board
    has_expired = any(i["alert_level"] == "expired" for i in comp_items)
    has_critical_compliance = any(i["alert_level"] in ("expired", "critical") for i in comp_items)
    has_out_of_stock = any(i["is_out"] for i in low_stock_items)
    has_overdue_60plus = any(i["oldest_overdue_days"] > 60 for i in overdue_items)
    yield_critical = yield_variance and yield_variance["status"] == "critical"

    problem_count = (
        (1 if overdue_items else 0)
        + (1 if low_stock_items else 0)
        + (1 if comp_items else 0)
        + (1 if (yield_variance and yield_variance["status"] != "on_track") else 0)
    )

    if has_expired or has_out_of_stock or yield_critical or has_overdue_60plus:
        status = "critical"
    elif problem_count > 0:
        status = "warning"
    else:
        status = "healthy"

    if status == "healthy":
        headline = "All clear · plant healthy today"
    else:
        bits = []
        if has_overdue_60plus or overdue_items:
            bits.append(f"₹{overdue_total/100000:.2f}L overdue")
        if has_out_of_stock:
            bits.append(f"{sum(1 for i in low_stock_items if i['is_out'])} product(s) out of stock")
        elif low_stock_items:
            bits.append(f"{len(low_stock_items)} product(s) low")
        if has_critical_compliance:
            bits.append(f"{sum(1 for i in comp_items if i['alert_level'] in ('expired', 'critical'))} compliance critical")
        elif comp_items:
            bits.append(f"{len(comp_items)} compliance expiring")
        if yield_variance and yield_variance["status"] != "on_track":
            bits.append(f"Yield {yield_variance['variance_pct']:+.1f}% vs target")
        headline = f"{problem_count} thing{'s' if problem_count != 1 else ''} need you — " + " · ".join(bits)

    return {
        "status": status,
        "headline": headline,
        "problem_count": problem_count,
        "overdue_customers": {
            "items": overdue_items,
            "count": len(overdue_items),
            "total_balance": round(overdue_total, 2),
        },
        "low_stock_products": {
            "items": low_stock_items,
            "count": len(low_stock_items),
            "out_of_stock_count": sum(1 for i in low_stock_items if i["is_out"]),
        },
        "compliance_expiring": {
            "items": comp_items,
            "count": len(comp_items),
        },
        "yield_variance": yield_variance,
        "today_revenue": today_revenue,
        "today_purchases": today_purchases,
        "payables": payables,
    }


# ── Sprint 2: One-tap WhatsApp batch for overdue customers ─────────────────────
#
# POST /api/v1/dashboard/whatsapp-overdue
# Body: { "party_ids": ["uuid", ...] }
# Returns: { "sent": N, "skipped": N (no phone), "failed": N }
#
from fastapi import HTTPException
from pydantic import BaseModel as _BaseModel


class _OverdueReminderRequest(_BaseModel):
    party_ids: list[str]


@router.post("/whatsapp-overdue")
async def whatsapp_overdue(
    payload: _OverdueReminderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Batch-send 'payment_overdue_reminder' to a set of customer party_ids.

    Uses the existing notifications pipeline — looks up templates for event
    `payment_overdue_reminder` on enabled channels, renders per party, and
    dispatches. Each party gets one message per channel (whatsapp / sms / email
    / telegram — whichever template is configured AND has a destination on
    the party record).
    """
    from app.integrations.notifications.service import send_notification
    from app.models.invoice import Invoice as _Inv
    import uuid as _uuid

    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not co:
        raise HTTPException(500, "Company not configured")
    if not payload.party_ids:
        return {"sent": 0, "skipped": 0, "failed": 0}

    try:
        pids = [_uuid.UUID(p) for p in payload.party_ids]
    except ValueError:
        raise HTTPException(400, "Invalid party_ids")

    today = date.today()
    sent = 0
    skipped = 0
    failed = 0

    # Pull the parties + per-party overdue summary in one shot
    rows = (await db.execute(
        select(
            Party,
            func.sum(_Inv.grand_total - _Inv.amount_paid).label("balance"),
            func.max(today - _Inv.due_date).label("oldest_days"),
        )
        .join(_Inv, _Inv.party_id == Party.id)
        .where(
            Party.id.in_(pids),
            _Inv.company_id == co.id,
            _Inv.invoice_type == "sale",
            _Inv.status == "final",
            _Inv.payment_status != "paid",
            _Inv.due_date.isnot(None),
            _Inv.due_date < today,
        )
        .group_by(Party.id)
    )).all()

    for party, balance, oldest_days in rows:
        if not party.phone and not party.email:
            skipped += 1
            continue
        try:
            ctx = {
                "company_name": co.name,
                "party_name": party.name,
                "party_phone": party.phone or "",
                "party_email": party.email or "",
                "balance": f"{float(balance or 0):,.2f}",
                "oldest_overdue_days": int(oldest_days or 0),
                "date": today.strftime("%d %b %Y"),
            }
            await send_notification(
                db, co.id, "payment_overdue_reminder", ctx,
                entity_type="party", entity_id=str(party.id),
            )
            sent += 1
        except Exception:
            failed += 1

    # Audit log
    try:
        from app.routers.audit import log_action
        await log_action(
            db, co.id, current_user.id, "send_overdue_reminders", "dashboard",
            entity_id=None,
            details={"sent": sent, "skipped": skipped, "failed": failed,
                     "party_count": len(payload.party_ids)},
        )
    except Exception:
        pass

    return {"sent": sent, "skipped": skipped, "failed": failed}

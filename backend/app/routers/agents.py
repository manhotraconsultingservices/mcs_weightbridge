"""Agents (brokers/dalals) — master CRUD + commission report card + payouts.

Commission is snapshotted on invoices.commission_amount at finalise (see
routers/invoices.py). The report card just aggregates those snapshots minus
recorded payouts, so it is stable against later rate changes.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.agent import Agent, AgentCommissionPayment
from app.models.invoice import Invoice
from app.models.party import Party
from app.schemas.agent import (
    AgentCreate, AgentResponse, AgentPayoutCreate, AgentPayoutResponse,
    AgentReport, AgentReportInvoice, AgentSummaryRow,
)
from app.services.commission import COMMISSION_TYPES

router = APIRouter(prefix="/api/v1/agents", tags=["Agents"])

# Which invoice types earn commission. Widen to ("sale", "purchase") to also
# pay agents on purchases — snapshot logic in invoices.py keys off the same set.
COMMISSION_INVOICE_TYPES = ("sale",)


# ── Master CRUD ───────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
async def list_agents(
    search: str | None = None,
    include_inactive: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Agent).where(Agent.company_id == current_user.company_id)
    if not include_inactive:
        q = q.where(Agent.is_active == True)
    if search:
        q = q.where(Agent.name.ilike(f"%{search}%"))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows = (await db.execute(
        q.order_by(Agent.name).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {"items": [AgentResponse.model_validate(a) for a in rows],
            "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    data: AgentCreate,
    current_user: User = Depends(require_role("admin", "operator", "accountant")),
    db: AsyncSession = Depends(get_db),
):
    if data.commission_type not in COMMISSION_TYPES:
        raise HTTPException(400, f"commission_type must be one of {COMMISSION_TYPES}")
    payload = data.model_dump(exclude_none=True)
    payload.pop("is_active", None)   # new agents are active
    agent = Agent(company_id=current_user.company_id, **payload)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(agent)


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: uuid.UUID,
    data: AgentCreate,
    current_user: User = Depends(require_role("admin", "operator", "accountant")),
    db: AsyncSession = Depends(get_db),
):
    agent = (await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.company_id == current_user.company_id)
    )).scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")
    if data.commission_type and data.commission_type not in COMMISSION_TYPES:
        raise HTTPException(400, f"commission_type must be one of {COMMISSION_TYPES}")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(agent)


# ── Payouts ───────────────────────────────────────────────────────────────────

@router.post("/{agent_id}/payouts", response_model=AgentPayoutResponse, status_code=201)
async def create_payout(
    agent_id: uuid.UUID,
    data: AgentPayoutCreate,
    current_user: User = Depends(require_role("admin", "accountant")),
    db: AsyncSession = Depends(get_db),
):
    agent = (await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.company_id == current_user.company_id)
    )).scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")
    if Decimal(str(data.amount or 0)) <= 0:
        raise HTTPException(400, "Payout amount must be positive")
    pay = AgentCommissionPayment(
        company_id=current_user.company_id, agent_id=agent_id,
        amount=data.amount, paid_on=data.paid_on, payment_mode=data.payment_mode,
        reference_no=data.reference_no, notes=data.notes, created_by=current_user.id,
    )
    db.add(pay)
    await db.flush()
    from app.routers.audit import log_action
    await log_action(db, current_user.company_id, current_user.id, "create", "agent_payout",
                     entity_id=str(pay.id),
                     details={"agent": agent.name, "amount": str(pay.amount),
                              "mode": pay.payment_mode, "reference_no": pay.reference_no})
    await db.commit()
    await db.refresh(pay)
    return AgentPayoutResponse.model_validate(pay)


@router.get("/{agent_id}/payouts", response_model=list[AgentPayoutResponse])
async def list_payouts(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(AgentCommissionPayment)
        .where(AgentCommissionPayment.company_id == current_user.company_id,
               AgentCommissionPayment.agent_id == agent_id)
        .order_by(AgentCommissionPayment.paid_on.desc(), AgentCommissionPayment.created_at.desc())
    )).scalars().all()
    return [AgentPayoutResponse.model_validate(p) for p in rows]


# ── Report card ───────────────────────────────────────────────────────────────

async def _paid_total(db, cid, agent_id, date_from, date_to) -> Decimal:
    q = select(func.coalesce(func.sum(AgentCommissionPayment.amount), 0)).where(
        AgentCommissionPayment.company_id == cid, AgentCommissionPayment.agent_id == agent_id)
    if date_from:
        q = q.where(AgentCommissionPayment.paid_on >= date_from)
    if date_to:
        q = q.where(AgentCommissionPayment.paid_on <= date_to)
    return Decimal(str((await db.execute(q)).scalar() or 0))


@router.get("/report-summary", response_model=list[AgentSummaryRow])
async def report_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """All agents — earned / paid / due at a glance."""
    cid = current_user.company_id
    agents = (await db.execute(
        select(Agent).where(Agent.company_id == cid).order_by(Agent.name)
    )).scalars().all()

    # earned per agent
    eq = select(Invoice.agent_id,
                func.coalesce(func.sum(func.coalesce(Invoice.commission_amount, 0)), 0),
                func.count(Invoice.id)).where(
        Invoice.company_id == cid, Invoice.status == "final",
        Invoice.invoice_type.in_(COMMISSION_INVOICE_TYPES),
        Invoice.agent_id.isnot(None))
    if date_from:
        eq = eq.where(Invoice.invoice_date >= date_from)
    if date_to:
        eq = eq.where(Invoice.invoice_date <= date_to)
    eq = eq.group_by(Invoice.agent_id)
    earned_map = {r[0]: (Decimal(str(r[1] or 0)), int(r[2] or 0)) for r in (await db.execute(eq)).all()}

    out = []
    for a in agents:
        earned, cnt = earned_map.get(a.id, (Decimal("0"), 0))
        paid = await _paid_total(db, cid, a.id, date_from, date_to)
        out.append(AgentSummaryRow(
            agent_id=a.id, name=a.name, commission_type=a.commission_type,
            commission_rate=a.commission_rate or Decimal("0"),
            invoice_count=cnt, earned=earned, paid=paid, due=earned - paid,
        ))
    return out


# ── Trend (daily / weekly / monthly commission) ───────────────────────────────

def _period_key(d: date, gran: str) -> date:
    if gran == "month":
        return date(d.year, d.month, 1)
    if gran == "week":
        return d - timedelta(days=d.weekday())   # Monday of that week
    return d


def _period_label(pk: date, gran: str) -> str:
    return pk.strftime("%b %y") if gran == "month" else pk.strftime("%d %b")


def _iter_periods(start: date, end: date, gran: str) -> list[date]:
    keys, cur, guard = [], _period_key(start, gran), 0
    endk = _period_key(end, gran)
    while cur <= endk and guard < 2000:
        keys.append(cur)
        guard += 1
        if gran == "month":
            cur = date(cur.year + (1 if cur.month == 12 else 0), (cur.month % 12) + 1, 1)
        elif gran == "week":
            cur = cur + timedelta(days=7)
        else:
            cur = cur + timedelta(days=1)
    return keys


@router.get("/trend")
async def agent_trend(
    date_from: date | None = None,
    date_to: date | None = None,
    granularity: str = "day",
    agent_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Commission earned (by invoice date) vs paid (by payout date), bucketed by
    day / week / month, gap-filled across the range. `agent_id` omitted → all
    sales partners combined. Powers the agent dashboard trend chart."""
    gran = granularity if granularity in ("day", "week", "month") else "day"
    cid = current_user.company_id
    end = date_to or date.today()
    start = date_from or (end - timedelta(days=90))
    if start > end:
        start = end

    iq = select(Invoice.invoice_date, Invoice.commission_amount).where(
        Invoice.company_id == cid, Invoice.status == "final",
        Invoice.invoice_type.in_(COMMISSION_INVOICE_TYPES), Invoice.agent_id.isnot(None),
        Invoice.invoice_date >= start, Invoice.invoice_date <= end)
    if agent_id:
        iq = iq.where(Invoice.agent_id == agent_id)
    inv_rows = (await db.execute(iq)).all()

    pq = select(AgentCommissionPayment.paid_on, AgentCommissionPayment.amount).where(
        AgentCommissionPayment.company_id == cid,
        AgentCommissionPayment.paid_on >= start, AgentCommissionPayment.paid_on <= end)
    if agent_id:
        pq = pq.where(AgentCommissionPayment.agent_id == agent_id)
    pay_rows = (await db.execute(pq)).all()

    earned: dict = {}
    count: dict = {}
    paid: dict = {}
    for d, amt in inv_rows:
        k = _period_key(d, gran)
        earned[k] = earned.get(k, Decimal("0")) + Decimal(str(amt or 0))
        count[k] = count.get(k, 0) + 1
    for d, amt in pay_rows:
        k = _period_key(d, gran)
        paid[k] = paid.get(k, Decimal("0")) + Decimal(str(amt or 0))

    series = [{
        "period": pk.isoformat(), "label": _period_label(pk, gran),
        "earned": float(earned.get(pk, 0)), "paid": float(paid.get(pk, 0)),
        "invoice_count": count.get(pk, 0),
    } for pk in _iter_periods(start, end, gran)]

    return {
        "granularity": gran, "date_from": start.isoformat(), "date_to": end.isoformat(),
        "series": series,
        "totals": {
            "earned": float(sum(earned.values(), Decimal("0"))),
            "paid": float(sum(paid.values(), Decimal("0"))),
            "invoice_count": sum(count.values()),
        },
    }


@router.get("/{agent_id}/report", response_model=AgentReport)
async def agent_report(
    agent_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = current_user.company_id
    agent = (await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.company_id == cid)
    )).scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")

    q = (select(Invoice, Party.name)
         .outerjoin(Party, Invoice.party_id == Party.id)
         .where(Invoice.company_id == cid, Invoice.agent_id == agent_id,
                Invoice.status == "final",
                Invoice.invoice_type.in_(COMMISSION_INVOICE_TYPES)))
    if date_from:
        q = q.where(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.where(Invoice.invoice_date <= date_to)
    q = q.order_by(Invoice.invoice_date.desc())
    rows = (await db.execute(q)).all()

    invoices = []
    earned = Decimal("0")
    total_sale = Decimal("0")
    for inv, party_name in rows:
        comm = Decimal(str(inv.commission_amount or 0))
        earned += comm
        total_sale += Decimal(str(inv.grand_total or 0))
        invoices.append(AgentReportInvoice(
            invoice_id=inv.id, invoice_no=inv.invoice_no, invoice_date=inv.invoice_date,
            invoice_type=inv.invoice_type, party_name=party_name,
            net_weight_mt=(Decimal(str(inv.net_weight or 0)) / Decimal("1000")).quantize(Decimal("0.001")),
            taxable_amount=Decimal(str(inv.taxable_amount or 0)),
            grand_total=Decimal(str(inv.grand_total or 0)),
            commission_amount=comm,
        ))

    paid = await _paid_total(db, cid, agent_id, date_from, date_to)
    payouts = (await db.execute(
        select(AgentCommissionPayment)
        .where(AgentCommissionPayment.company_id == cid, AgentCommissionPayment.agent_id == agent_id)
        .order_by(AgentCommissionPayment.paid_on.desc(), AgentCommissionPayment.created_at.desc())
    )).scalars().all()

    return AgentReport(
        agent=AgentResponse.model_validate(agent),
        earned=earned, paid=paid, due=earned - paid,
        invoice_count=len(invoices), total_sale_value=total_sale,
        invoices=invoices,
        payouts=[AgentPayoutResponse.model_validate(p) for p in payouts],
    )

"""Workforce & Payroll — workers (non-login), attendance muster, payments.

Makes the weighbridge the system-of-record for labour cost: add workers, mark
daily attendance, record every payment (advance/wage/salary/bonus/deduction),
and read each worker's attendance-driven Earned vs Paid → Balance Due (advances
netted). All-new tables + endpoints; nothing existing changes.
"""
from __future__ import annotations

import json
import uuid
from calendar import monthrange
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.workforce import Worker, WorkerAttendance, WorkerPayment
from app.schemas.workforce import (
    WorkerCreate, WorkerUpdate, WorkerResponse,
    AttendanceMark, AttendanceBulk,
    PaymentCreate, PaymentUpdate, PaymentResponse,
)
from app.services import payroll

router = APIRouter(prefix="/api/v1/workforce", tags=["Workforce & Payroll"])


# ── Config ────────────────────────────────────────────────────────────────────

async def _get_config(db: AsyncSession) -> dict:
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key = 'workforce_config'")
        )).fetchone()
        if row:
            cfg = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return {**payroll.DEFAULT_CONFIG, **(cfg or {})}
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
    return dict(payroll.DEFAULT_CONFIG)


@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await _get_config(db)


@router.put("/config")
async def put_config(payload: dict, db: AsyncSession = Depends(get_db),
                     user: User = Depends(get_current_user)):
    await db.execute(
        text("""
            INSERT INTO app_settings (key, value, updated_at)
            VALUES ('workforce_config', :v, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """),
        {"v": json.dumps(payload)},
    )
    await db.commit()
    return {"ok": True}


# ── Workers master ────────────────────────────────────────────────────────────

@router.get("/workers", response_model=list[WorkerResponse])
async def list_workers(
    active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    q = select(Worker).where(Worker.company_id == user.company_id)
    if active is not None:
        q = q.where(Worker.is_active == active)
    if search:
        q = q.where(Worker.name.ilike(f"%{search}%"))
    rows = (await db.execute(q.order_by(Worker.name))).scalars().all()
    return [WorkerResponse.model_validate(w) for w in rows]


@router.post("/workers", response_model=WorkerResponse, status_code=201)
async def create_worker(payload: WorkerCreate, db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    if not payload.name.strip():
        raise HTTPException(400, "Name is required")
    w = Worker(company_id=user.company_id, branch_id=getattr(user, "branch_id", None),
               created_by=user.id, **payload.model_dump())
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return WorkerResponse.model_validate(w)


@router.put("/workers/{worker_id}", response_model=WorkerResponse)
async def update_worker(worker_id: uuid.UUID, payload: WorkerUpdate,
                        db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    w = (await db.execute(select(Worker).where(
        Worker.id == worker_id, Worker.company_id == user.company_id))).scalar_one_or_none()
    if not w:
        raise HTTPException(404, "Worker not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(w, k, v)
    await db.commit()
    await db.refresh(w)
    return WorkerResponse.model_validate(w)


@router.delete("/workers/{worker_id}")
async def delete_worker(worker_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    w = (await db.execute(select(Worker).where(
        Worker.id == worker_id, Worker.company_id == user.company_id))).scalar_one_or_none()
    if not w:
        raise HTTPException(404, "Worker not found")
    w.is_active = False   # soft delete — keep history intact
    await db.commit()
    return {"ok": True}


# ── Attendance muster ─────────────────────────────────────────────────────────

async def _upsert_attendance(db: AsyncSession, user: User, item: AttendanceMark,
                             commit: bool = True) -> dict:
    w = (await db.execute(select(Worker).where(
        Worker.id == item.worker_id, Worker.company_id == user.company_id))).scalar_one_or_none()
    if not w:
        raise HTTPException(404, "Worker not found")
    existing = (await db.execute(select(WorkerAttendance).where(
        WorkerAttendance.worker_id == item.worker_id,
        WorkerAttendance.att_date == item.att_date))).scalar_one_or_none()
    if item.status == "clear":                        # tap-cycle back to blank
        if existing:
            await db.delete(existing)
        if commit:
            await db.commit()
        return {"ok": True, "cleared": True}
    if existing:
        existing.status = item.status
        existing.ot_hours = item.ot_hours
        existing.notes = item.notes
    else:
        db.add(WorkerAttendance(
            company_id=user.company_id, worker_id=item.worker_id, att_date=item.att_date,
            status=item.status, ot_hours=item.ot_hours, notes=item.notes, created_by=user.id))
    if commit:
        await db.commit()
    return {"ok": True}


@router.get("/attendance")
async def attendance_grid(
    month: Optional[str] = Query(None, description="YYYY-MM (or pass date_from + date_to)"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Muster grid over a range (a day, a week, or a month) — workers × days + per-worker
    units & earned for that window. Pass month=YYYY-MM OR date_from + date_to."""
    if date_from and date_to:
        dfrom, dto = date_from, date_to
    elif month:
        try:
            y, m = (int(x) for x in month.split("-")[:2])
            dfrom = date(y, m, 1)
            dto = date(y, m, monthrange(y, m)[1])
        except Exception:
            raise HTTPException(400, "month must be YYYY-MM")
    else:
        raise HTTPException(400, "provide month or date_from + date_to")
    if dto < dfrom:
        dfrom, dto = dto, dfrom
    if (dto - dfrom).days > 92:
        raise HTTPException(400, "date range too large (max 3 months)")

    cfg = await _get_config(db)
    workers = (await db.execute(select(Worker).where(
        Worker.company_id == user.company_id, Worker.is_active == True
    ).order_by(Worker.name))).scalars().all()
    att = (await db.execute(select(WorkerAttendance).where(
        WorkerAttendance.company_id == user.company_id,
        WorkerAttendance.att_date >= dfrom, WorkerAttendance.att_date <= dto))).scalars().all()

    by_worker: dict = {}
    for a in att:
        by_worker.setdefault(a.worker_id, {})[a.att_date.isoformat()] = {
            "status": a.status, "ot_hours": float(a.ot_hours or 0)}

    days = []
    d = dfrom
    while d <= dto:
        days.append(d.isoformat())
        d += timedelta(days=1)

    out = []
    for w in workers:
        amap = by_worker.get(w.id, {})
        if w.worker_type == "monthly_salary":
            units = None
            earned = payroll.salary_earned(float(w.rate), dfrom, dto)
        else:
            units = payroll.daily_units(
                [{"status": v["status"], "ot_hours": v["ot_hours"]} for v in amap.values()], cfg)
            earned = round(units * float(w.rate), 2)
        out.append({
            "worker_id": str(w.id), "name": w.name, "worker_type": w.worker_type,
            "rate": float(w.rate), "attendance": amap, "units": units, "earned": earned,
        })
    return {"date_from": dfrom.isoformat(), "date_to": dto.isoformat(), "days": days, "workers": out}


@router.post("/attendance")
async def mark_attendance(payload: AttendanceMark, db: AsyncSession = Depends(get_db),
                          user: User = Depends(get_current_user)):
    return await _upsert_attendance(db, user, payload)


@router.post("/attendance/bulk")
async def mark_attendance_bulk(payload: AttendanceBulk, db: AsyncSession = Depends(get_db),
                               user: User = Depends(get_current_user)):
    n = 0
    for item in payload.items:
        await _upsert_attendance(db, user, item, commit=False)
        n += 1
    await db.commit()
    return {"ok": True, "count": n}


# ── Payments ledger ───────────────────────────────────────────────────────────

@router.get("/payments")
async def list_payments(
    worker_id: Optional[uuid.UUID] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(300, ge=1, le=1000),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    q = select(WorkerPayment).where(WorkerPayment.company_id == user.company_id)
    if worker_id:
        q = q.where(WorkerPayment.worker_id == worker_id)
    if date_from:
        q = q.where(WorkerPayment.pay_date >= date_from)
    if date_to:
        q = q.where(WorkerPayment.pay_date <= date_to)
    rows = (await db.execute(q.order_by(
        WorkerPayment.pay_date.desc(), WorkerPayment.created_at.desc()))).scalars().all()
    total = len(rows)
    page_rows = rows[(page - 1) * page_size: page * page_size]
    names = {w.id: w.name for w in (await db.execute(
        select(Worker).where(Worker.company_id == user.company_id))).scalars().all()}
    items = [{
        "id": str(r.id), "worker_id": str(r.worker_id), "worker_name": names.get(r.worker_id),
        "pay_date": str(r.pay_date), "payment_type": r.payment_type, "amount": float(r.amount),
        "mode": r.mode, "reference": r.reference, "notes": r.notes,
    } for r in page_rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/payments", response_model=PaymentResponse, status_code=201)
async def create_payment(payload: PaymentCreate, db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)):
    w = (await db.execute(select(Worker).where(
        Worker.id == payload.worker_id, Worker.company_id == user.company_id))).scalar_one_or_none()
    if not w:
        raise HTTPException(404, "Worker not found")
    if payload.amount is None or payload.amount <= 0:
        raise HTTPException(400, "Amount must be greater than 0")
    p = WorkerPayment(company_id=user.company_id, branch_id=getattr(user, "branch_id", None),
                      created_by=user.id, **payload.model_dump())
    db.add(p)
    await db.commit()
    await db.refresh(p)
    resp = PaymentResponse.model_validate(p)
    resp.worker_name = w.name
    return resp


@router.put("/payments/{payment_id}", response_model=PaymentResponse)
async def update_payment(payment_id: uuid.UUID, payload: PaymentUpdate,
                         db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    p = (await db.execute(select(WorkerPayment).where(
        WorkerPayment.id == payment_id, WorkerPayment.company_id == user.company_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Payment not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    await db.commit()
    await db.refresh(p)
    return PaymentResponse.model_validate(p)


@router.delete("/payments/{payment_id}")
async def delete_payment(payment_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)):
    p = (await db.execute(select(WorkerPayment).where(
        WorkerPayment.id == payment_id, WorkerPayment.company_id == user.company_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Payment not found")
    await db.delete(p)
    await db.commit()
    return {"ok": True}


# ── Payroll summary ───────────────────────────────────────────────────────────

@router.get("/summary")
async def payroll_summary(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    """Per-worker Earned / Advances / Paid / Balance Due over [date_from, date_to]."""
    cfg = await _get_config(db)
    workers = (await db.execute(select(Worker).where(
        Worker.company_id == user.company_id, Worker.is_active == True
    ).order_by(Worker.name))).scalars().all()
    att = (await db.execute(select(WorkerAttendance).where(
        WorkerAttendance.company_id == user.company_id,
        WorkerAttendance.att_date >= date_from, WorkerAttendance.att_date <= date_to))).scalars().all()
    pay = (await db.execute(select(WorkerPayment).where(
        WorkerPayment.company_id == user.company_id,
        WorkerPayment.pay_date >= date_from, WorkerPayment.pay_date <= date_to))).scalars().all()

    att_by: dict = {}
    pay_by: dict = {}
    for a in att:
        att_by.setdefault(a.worker_id, []).append({"status": a.status, "ot_hours": float(a.ot_hours or 0)})
    for p in pay:
        pay_by.setdefault(p.worker_id, []).append({"payment_type": p.payment_type, "amount": float(p.amount)})

    rows = []
    totals = {"earned": 0.0, "advances": 0.0, "settled": 0.0, "deductions": 0.0,
              "total_paid": 0.0, "balance_due": 0.0}
    for w in workers:
        s = payroll.worker_summary(
            {"rate": float(w.rate), "worker_type": w.worker_type},
            att_by.get(w.id, []), pay_by.get(w.id, []), date_from, date_to, cfg)
        rows.append({"worker_id": str(w.id), "name": w.name, "worker_type": w.worker_type,
                     "rate": float(w.rate), **s})
        for k in totals:
            totals[k] += s.get(k) or 0
    totals = {k: round(v, 2) for k, v in totals.items()}
    return {"date_from": str(date_from), "date_to": str(date_to), "summary": rows, "totals": totals}

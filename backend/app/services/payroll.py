"""Worker payroll — attendance-driven earnings + advance-netted balance.

All figures are computed at READ time from worker_attendance + worker_payments;
nothing derived is stored (so a corrected attendance mark re-derives instantly).

Balance model (net):  balance_due = earned − total_paid
  where total_paid = advances + settled(wage/salary/bonus) − deductions.
A positive balance = owed to the worker; negative = net advance / overpaid.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "half_day_factor": 0.5,   # a half-day earns this fraction of the daily rate
    "work_hours": 8,          # standard hours in a full day (for OT proration)
    "ot_factor": 1.0,         # each OT hour paid at (daily_rate / work_hours) * ot_factor
}

SETTLE_TYPES = ("wage", "salary", "bonus")


def _f(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def day_factor(status: str, ot_hours: Any, cfg: dict) -> float:
    """Fraction of a full day's wage earned for one attendance mark."""
    if status == "present":
        return 1.0
    if status == "half_day":
        return float(cfg.get("half_day_factor", 0.5))
    if status == "overtime":
        wh = float(cfg.get("work_hours", 8)) or 8.0
        return 1.0 + _f(ot_hours) * (float(cfg.get("ot_factor", 1.0)) / wh)
    return 0.0  # absent / unknown


def daily_units(attendance: list[dict], cfg: dict) -> float:
    """Sum of day-factors over a daily-wage worker's attendance rows."""
    return round(sum(day_factor(a.get("status", ""), a.get("ot_hours", 0), cfg) for a in attendance), 3)


def _month_overlap_fraction(dfrom: date, dto: date, y: int, m: int) -> float:
    dim = monthrange(y, m)[1]
    m_start, m_end = date(y, m, 1), date(y, m, dim)
    lo, hi = max(dfrom, m_start), min(dto, m_end)
    if lo > hi:
        return 0.0
    return ((hi - lo).days + 1) / dim


def salary_earned(rate: float, dfrom: date, dto: date) -> float:
    """Monthly salary pro-rated across every month overlapping [dfrom, dto].
    Full month in range → full salary; a partial month → the covered fraction."""
    total = 0.0
    y, m = dfrom.year, dfrom.month
    while (y, m) <= (dto.year, dto.month):
        total += rate * _month_overlap_fraction(dfrom, dto, y, m)
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return round(total, 2)


def worker_summary(worker: dict, attendance: list[dict], payments: list[dict],
                   dfrom: date, dto: date, cfg: dict) -> dict:
    """Per-worker payroll summary over [dfrom, dto]."""
    rate = _f(worker.get("rate"))
    if worker.get("worker_type") == "monthly_salary":
        units = None
        earned = salary_earned(rate, dfrom, dto)
    else:
        units = daily_units(attendance, cfg)
        earned = round(units * rate, 2)

    advances   = round(sum(_f(p["amount"]) for p in payments if p.get("payment_type") == "advance"), 2)
    settled    = round(sum(_f(p["amount"]) for p in payments if p.get("payment_type") in SETTLE_TYPES), 2)
    deductions = round(sum(_f(p["amount"]) for p in payments if p.get("payment_type") == "deduction"), 2)
    total_paid = round(advances + settled - deductions, 2)
    balance_due = round(earned - total_paid, 2)

    return {
        "days_units": units,           # None for salaried workers
        "earned": earned,
        "advances": advances,
        "settled": settled,
        "deductions": deductions,
        "total_paid": total_paid,
        "balance_due": balance_due,
    }

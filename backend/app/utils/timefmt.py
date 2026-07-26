"""Shared IST (Asia/Kolkata) datetime formatting for user-facing text.

Timestamps are stored as UTC (TIMESTAMPTZ / naive-UTC). Notifications and any
other server-rendered text must show the company's local time — India (UTC+5:30)
for every current tenant. Kept in one place so it can become per-tenant later
without touching each call site.
"""
from datetime import datetime, date, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def to_ist(value):
    """UTC/naive datetime -> IST datetime. A pure `date` (no time) passes through
    untouched; None stays None; non-datetime values are returned as-is."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)  # stored values are UTC
        return value.astimezone(IST)
    return value


def fmt_ist(value, fmt: str = "%d-%m-%Y %H:%M", dash: str = "—") -> str:
    """Format a UTC datetime in IST. Returns `dash` for None. A pure date is
    formatted with the given fmt if it has date directives, else str()."""
    v = to_ist(value)
    if v is None:
        return dash
    if isinstance(v, (datetime, date)):
        try:
            return v.strftime(fmt)
        except Exception:
            return str(v)
    return str(v)

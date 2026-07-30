"""Daily EOD CSV pack — Telegram.

Once a day (fired from the owner-digest loop) OR on demand, send the day's
gate passes, tokens, payments, sales invoices and purchase invoices as CSV
attachments to the tenant's Telegram recipients subscribed to `eod_csv_pack`.

Deliberately additive / zero-impact:
  • uses sendDocument (send_telegram_document) — the existing text/sendMessage
    path is untouched;
  • each dataset query is SAVEPOINT-guarded → a tenant missing a feature table
    simply omits that one CSV;
  • the scheduled trigger is gated by app_settings 'eod_csv_pack.enabled'
    (default OFF), so no tenant sends anything until it's switched on.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _csv_bytes(header: list[str], rows: list[tuple]) -> bytes:
    """Render rows to CSV bytes with a UTF-8 BOM so Excel shows ₹ / Hindi text."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return (chr(0xFEFF) + buf.getvalue()).encode("utf-8")


async def build_eod_csv_files(db: AsyncSession, company_id, target_date: date) -> list[tuple[str, bytes, int]]:
    """Return [(filename, csv_bytes, row_count)] for the day. Empty datasets are
    omitted. Each query runs in its own SAVEPOINT so one missing table (e.g. a
    tenant without the gate/store module) skips only that file."""
    cid = str(company_id)
    params = {"cid": cid, "d": target_date}
    out: list[tuple[str, bytes, int]] = []

    async def add(name: str, header: list[str], sql: str, extra: dict | None = None):
        try:
            async with db.begin_nested():
                rows = (await db.execute(text(sql), {**params, **(extra or {})})).fetchall()
        except Exception as e:  # noqa: BLE001 — missing feature-module table, etc.
            logger.warning("EOD CSV '%s' skipped: %s", name, str(e)[:140])
            return
        if not rows:
            return
        out.append((f"{name}_{target_date.isoformat()}.csv",
                    _csv_bytes(header, [tuple(r) for r in rows]), len(rows)))

    # 1. Gate passes (entry/exit times in IST)
    await add(
        "gate_passes",
        ["Gate Pass", "Date", "Vehicle", "Driver", "Material", "Purpose", "Entry", "Exit", "Status"],
        "SELECT gate_pass_no, pass_date, vehicle_no, driver_name, material, purpose, "
        "to_char(entry_time AT TIME ZONE 'Asia/Kolkata', 'HH24:MI'), "
        "to_char(exit_time AT TIME ZONE 'Asia/Kolkata', 'HH24:MI'), status "
        "FROM gate_passes WHERE company_id=:cid AND pass_date=:d ORDER BY entry_time")

    # 2. Tokens (net weight shown in MT)
    await add(
        "tokens",
        ["Token", "Date", "Type", "Vehicle", "Party", "Material", "Net Weight (MT)", "Status", "Gate Pass"],
        "SELECT t.token_no, t.token_date, t.token_type, t.vehicle_no, p.name, pr.name, "
        "ROUND(COALESCE(t.net_weight,0)/1000.0, 3), t.status, t.gate_pass_no "
        "FROM tokens t LEFT JOIN parties p ON p.id=t.party_id "
        "LEFT JOIN products pr ON pr.id=t.product_id "
        "WHERE t.company_id=:cid AND t.token_date=:d ORDER BY t.created_at")

    # 3. Payments — receipts (money in) + vouchers/expenses (money out)
    await add(
        "payments",
        ["Kind", "No", "Date", "Party", "Amount", "Mode", "Reference", "Category"],
        "SELECT 'Receipt' AS kind, r.receipt_no, r.receipt_date, p.name, r.amount, r.payment_mode, "
        "r.reference_no, '' AS cat FROM payment_receipts r LEFT JOIN parties p ON p.id=r.party_id "
        "WHERE r.company_id=:cid AND r.receipt_date=:d "
        "UNION ALL "
        "SELECT CASE WHEN v.expense_category IS NOT NULL THEN 'Expense' ELSE 'Voucher' END, "
        "v.voucher_no, v.voucher_date, p.name, v.amount, v.payment_mode, v.reference_no, "
        "COALESCE(v.expense_category,'') FROM payment_vouchers v LEFT JOIN parties p ON p.id=v.party_id "
        "WHERE v.company_id=:cid AND v.voucher_date=:d "
        "ORDER BY 3, 1")

    # 4 & 5. Sales / purchase invoices (draft OR final; cancelled excluded)
    inv_header = ["Invoice", "Date", "Party", "Taxable", "GST", "Grand Total", "Status", "Payment", "Token"]
    inv_sql = (
        "SELECT COALESCE(i.invoice_no,'(draft)'), i.invoice_date, p.name, "
        "i.taxable_amount, (i.cgst_amount + i.sgst_amount + i.igst_amount) AS gst, i.grand_total, "
        "i.status, i.payment_status, t.token_no "
        "FROM invoices i LEFT JOIN parties p ON p.id=i.party_id "
        "LEFT JOIN tokens t ON t.id=i.token_id "
        "WHERE i.company_id=:cid AND i.invoice_type=:ity AND i.invoice_date=:d "
        "AND i.status NOT IN ('cancelled','superseded') "
        "ORDER BY i.invoice_no NULLS LAST, i.created_at")
    await add("sales_invoices", inv_header, inv_sql, {"ity": "sale"})
    await add("purchase_invoices", inv_header, inv_sql, {"ity": "purchase"})

    return out


async def send_eod_csv_pack(db: AsyncSession, company_id, company_name: str, target_date: date) -> dict:
    """Build the day's CSVs and send them (header message + one document each) to
    every active Telegram recipient subscribed to `eod_csv_pack` (or `*`). Logs one
    NotificationLog row per recipient. Never raises — returns a summary dict."""
    from app.integrations.notifications.service import _load_recipients
    from app.integrations.notifications.telegram_notify import (
        send_telegram_document, send_telegram_notification,
    )
    from app.models.notification import NotificationConfig, NotificationLog

    cfg = (await db.execute(
        select(NotificationConfig).where(
            NotificationConfig.company_id == company_id,
            NotificationConfig.channel == "telegram",
            NotificationConfig.is_enabled == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not cfg or not cfg.tg_bot_token:
        return {"sent": 0, "recipients": 0, "files": 0, "reason": "telegram not configured"}

    chats = await _load_recipients(db, company_id, "telegram", "eod_csv_pack")
    if not chats:
        return {"sent": 0, "recipients": 0, "files": 0, "reason": "no recipients subscribed"}

    files = await build_eod_csv_files(db, company_id, target_date)
    date_label = target_date.strftime("%d %b %Y")
    if files:
        listing = "\n".join(f"• {n.rsplit('_', 1)[0].replace('_', ' ').title()} — {c}" for n, _, c in files)
        header_msg = f"📎 <b>Day Book — CSV pack</b>\n{date_label}\n\n{listing}\n\n— {company_name}"
    else:
        header_msg = f"📎 <b>Day Book — CSV pack</b>\n{date_label}\n\nNo activity recorded.\n\n— {company_name}"

    sent_docs = 0
    for chat in chats:
        status = "sent"
        err = None
        try:
            await send_telegram_notification(cfg.tg_bot_token, chat, header_msg)
            for fname, content, cnt in files:
                await send_telegram_document(
                    cfg.tg_bot_token, chat, fname, content, caption=f"{fname} · {cnt} rows")
                sent_docs += 1
        except Exception as e:  # noqa: BLE001
            status = "failed"
            from app.integrations.notifications.service import _redact_secrets
            err = _redact_secrets(str(e))[:500]
            logger.warning("EOD CSV pack send failed [chat=%s]: %s", chat, err)
        db.add(NotificationLog(
            company_id=company_id, channel="telegram", event_type="eod_csv_pack",
            entity_type="company", entity_id=str(company_id), recipient=chat,
            subject=None, body_preview=header_msg[:500], status=status, error_message=err,
        ))
    await db.commit()
    return {"sent": sent_docs, "recipients": len(chats), "files": len(files),
            "date": target_date.isoformat()}

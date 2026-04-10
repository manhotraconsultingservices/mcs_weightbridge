"""Telegram Bot API sender — used for inventory daily reports."""
import logging
from typing import List

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


async def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "Markdown",
) -> None:
    """Send a message via Telegram Bot API.  Raises httpx.HTTPStatusError on failure."""
    url = _TELEGRAM_API.format(token=bot_token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
    logger.info("Telegram message sent to chat_id=%s", chat_id)


def build_daily_report(
    items: List[dict],
    today_issues: int,
    today_receipts: int,
    company_name: str,
    report_date: str,
) -> str:
    """
    Build the Markdown-formatted daily inventory report string.

    items: list of dicts with keys: name, unit, current_stock, min_stock_level, stock_status
    """
    ok_items  = [i for i in items if i["stock_status"] == "ok"]
    low_items = [i for i in items if i["stock_status"] == "low"]
    out_items = [i for i in items if i["stock_status"] == "out"]

    lines = [
        "📦 *Daily Inventory Report*",
        f"🗓 Date: {report_date}",
        "",
    ]

    if ok_items:
        lines.append(f"🟢 *OK Items ({len(ok_items)})*")
        for i in ok_items:
            stock = float(i["current_stock"])
            # Format: show as integer if whole number, else 3 dp
            stock_str = f"{stock:g}" if stock == int(stock) else f"{stock:.3f}"
            lines.append(f"• {i['name']} — {stock_str} {i['unit']} ✅")
        lines.append("")

    if low_items:
        lines.append(f"🟡 *Low Stock ({len(low_items)})*")
        for i in low_items:
            stock = float(i["current_stock"])
            min_s = float(i["min_stock_level"])
            stock_str = f"{stock:g}" if stock == int(stock) else f"{stock:.3f}"
            min_str   = f"{min_s:g}" if min_s == int(min_s) else f"{min_s:.3f}"
            lines.append(f"• {i['name']} — {stock_str} {i['unit']} ⚠️ (min: {min_str})")
        lines.append("")

    if out_items:
        lines.append(f"🔴 *Out of Stock ({len(out_items)})*")
        for i in out_items:
            lines.append(f"• {i['name']} — 0 {i['unit']} ❌")
        lines.append("")

    if not items:
        lines.append("_No inventory items configured yet._")
        lines.append("")

    lines += [
        "📊 *Today's Activity*",
        f"• Issues: {today_issues} transaction{'s' if today_issues != 1 else ''}",
        f"• Receipts: {today_receipts} PO{'s' if today_receipts != 1 else ''} received",
        "",
        f"— {company_name}",
    ]

    return "\n".join(lines)

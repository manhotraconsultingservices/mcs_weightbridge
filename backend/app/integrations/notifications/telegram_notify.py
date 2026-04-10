"""Telegram notification sender — used by the main notification engine.

Distinct from integrations/notifications/telegram.py which handles the
inventory daily-report Telegram integration.
"""
import logging
import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


async def send_telegram_notification(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
) -> None:
    """Send a message to a Telegram chat via the Bot API.

    Args:
        bot_token: The Telegram Bot API token (from BotFather).
        chat_id:   Recipient chat ID or @channel_username.
        text:      Message text (HTML or plain).
        parse_mode: 'HTML' (default) or 'Markdown'.

    Raises:
        httpx.HTTPStatusError: if Telegram returns a non-2xx status.
        RuntimeError: if Telegram reports ok=false in the response JSON.
    """
    url = TELEGRAM_API.format(token=bot_token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram error: {data.get('description', 'unknown')}")

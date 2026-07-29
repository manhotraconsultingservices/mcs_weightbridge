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
        RuntimeError: on any Telegram error, carrying Telegram's own
            ``description`` (e.g. "Bad Request: chat not found") + the chat_id —
            and NEVER the request URL (which embeds the bot token). We
            deliberately do NOT call ``raise_for_status()``: its message leaks the
            token-laden URL and drops the useful reason.
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
        try:
            data = resp.json()
        except Exception:
            data = {}
        if resp.status_code >= 400 or not data.get("ok"):
            desc = data.get("description") or f"HTTP {resp.status_code}"
            raise RuntimeError(f"Telegram {resp.status_code}: {desc} (chat_id={chat_id})")

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


async def send_telegram_document(
    bot_token: str,
    chat_id: str,
    filename: str,
    content: bytes,
    caption: str | None = None,
    parse_mode: str = "HTML",
) -> None:
    """Send a file (e.g. a CSV) to a Telegram chat via the Bot API's sendDocument.

    Separate from ``send_telegram_notification`` (which uses sendMessage) — this is
    a multipart upload and is only used by the daily EOD CSV pack, so the text path
    is untouched.

    Raises:
        RuntimeError: on any Telegram error, carrying Telegram's own ``description``
            + the chat_id, and NEVER the token-laden request URL (see the sendMessage
            sender for the rationale).
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    files = {"document": (filename, content, "text/csv")}
    data: dict[str, str] = {"chat_id": chat_id, "disable_notification": "false"}
    if caption:
        data["caption"] = caption[:1024]
        data["parse_mode"] = parse_mode
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, data=data, files=files)
        try:
            j = resp.json()
        except Exception:
            j = {}
        if resp.status_code >= 400 or not j.get("ok"):
            desc = j.get("description") or f"HTTP {resp.status_code}"
            raise RuntimeError(f"Telegram sendDocument {resp.status_code}: {desc} (chat_id={chat_id})")

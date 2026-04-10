"""WhatsApp sender via WATI API."""
import httpx
import logging

logger = logging.getLogger(__name__)


async def send_whatsapp(
    api_url: str,
    api_key: str,
    to_phone: str,
    message: str,
) -> None:
    """Send WhatsApp message via WATI. Raises on failure.

    WATI API: POST {api_url}/api/v1/sendSessionMessage/{phone}
    Authorization: Bearer {api_key}
    """
    # Normalize phone
    phone = to_phone.replace(" ", "").replace("-", "").replace("+", "")
    if not phone.startswith("91") and len(phone) == 10:
        phone = "91" + phone

    base = api_url.rstrip("/")
    url = f"{base}/api/v1/sendSessionMessage/{phone}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"messageText": message}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()

    logger.info("WhatsApp sent to %s via WATI", to_phone)

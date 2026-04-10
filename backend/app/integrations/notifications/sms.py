"""MSG91 SMS sender."""
import httpx
import logging

logger = logging.getLogger(__name__)

MSG91_SEND_URL = "https://api.msg91.com/api/v5/flow/"
MSG91_SEND_SMS_URL = "https://api.msg91.com/api/sendhttp.php"


async def send_sms(
    api_key: str,
    sender_id: str,
    to_phone: str,
    message: str,
    route: str = "4",
) -> None:
    """Send SMS via MSG91 API. Raises on failure."""
    # Normalize phone: strip spaces/dashes, ensure country code
    phone = to_phone.replace(" ", "").replace("-", "").replace("+", "")
    if not phone.startswith("91") and len(phone) == 10:
        phone = "91" + phone

    params = {
        "authkey": api_key,
        "mobiles": phone,
        "message": message,
        "sender": sender_id,
        "route": route,
        "country": "91",
        "DLT_TE_ID": "",  # fill if DLT registered
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(MSG91_SEND_SMS_URL, params=params)
        resp.raise_for_status()

    logger.info("SMS sent to %s via MSG91", to_phone)

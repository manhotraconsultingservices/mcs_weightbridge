"""Unified notification service — render template + dispatch via channel + log."""
from __future__ import annotations
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Any

from jinja2 import Environment, BaseLoader, Undefined, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.models.notification import (
    NotificationConfig,
    NotificationTemplate,
    NotificationLog,
    NotificationRecipient,
)

logger = logging.getLogger(__name__)

# ── Jinja2 sandbox ────────────────────────────────────────────────────────────
# Use Undefined (base class) — missing vars render as empty string in str context,
# which is fine for notification templates.

_jinja = Environment(
    loader=BaseLoader(),
    autoescape=select_autoescape(["html"]),
    undefined=Undefined,
)


def render_template(template_str: str, context: dict[str, Any]) -> str:
    try:
        tmpl = _jinja.from_string(template_str)
        return tmpl.render(**context)
    except Exception as e:
        logger.warning("Template render error: %s", e)
        return template_str


# ── Default seed templates ─────────────────────────────────────────────────────

DEFAULT_TEMPLATES = [
    {
        "event_type": "invoice_finalized",
        "channel": "email",
        "name": "Invoice Finalized (Email)",
        "subject": "Invoice {{ invoice_no }} from {{ company_name }}",
        "body": """<p>Dear {{ party_name }},</p>
<p>Your invoice <strong>{{ invoice_no }}</strong> dated {{ invoice_date }} has been generated.</p>
<p><strong>Amount: ₹{{ grand_total }}</strong></p>
<p>Thank you for your business.</p>
<p>Regards,<br>{{ company_name }}</p>""",
    },
    {
        "event_type": "invoice_finalized",
        "channel": "sms",
        "name": "Invoice Finalized (SMS)",
        "subject": None,
        "body": "Dear {{ party_name }}, Invoice {{ invoice_no }} of Rs.{{ grand_total }} generated on {{ invoice_date }}. Thank you. - {{ company_name }}",
    },
    {
        "event_type": "invoice_finalized",
        "channel": "whatsapp",
        "name": "Invoice Finalized (WhatsApp)",
        "subject": None,
        "body": "Dear {{ party_name }},\n\nInvoice *{{ invoice_no }}* dated {{ invoice_date }}\nAmount: *₹{{ grand_total }}*\n\nThank you! - {{ company_name }}",
    },
    {
        "event_type": "invoice_finalized",
        "channel": "telegram",
        "name": "Invoice Finalized (Telegram)",
        "subject": None,
        "body": "📄 <b>Invoice Finalized</b>\n\nParty: {{ party_name }}\nInvoice: <b>{{ invoice_no }}</b>\nDate: {{ invoice_date }}\nAmount: <b>₹{{ grand_total }}</b>\n\n— {{ company_name }}",
    },
    {
        "event_type": "payment_received",
        "channel": "email",
        "name": "Payment Received (Email)",
        "subject": "Payment Receipt {{ receipt_no }} - {{ company_name }}",
        "body": """<p>Dear {{ party_name }},</p>
<p>We have received your payment of <strong>₹{{ amount }}</strong> on {{ receipt_date }}.</p>
<p>Receipt No: {{ receipt_no }}</p>
<p>Thank you.</p>
<p>Regards,<br>{{ company_name }}</p>""",
    },
    {
        "event_type": "payment_received",
        "channel": "sms",
        "name": "Payment Received (SMS)",
        "subject": None,
        "body": "Dear {{ party_name }}, payment of Rs.{{ amount }} received on {{ receipt_date }}. Receipt: {{ receipt_no }}. - {{ company_name }}",
    },
    {
        "event_type": "payment_received",
        "channel": "telegram",
        "name": "Payment Received (Telegram)",
        "subject": None,
        "body": "💰 <b>Payment Received</b>\n\nParty: {{ party_name }}\nReceipt: <b>{{ receipt_no }}</b>\nAmount: <b>₹{{ amount }}</b>\nDate: {{ receipt_date }}\n\n— {{ company_name }}",
    },
    {
        "event_type": "quotation_sent",
        "channel": "email",
        "name": "Quotation Sent (Email)",
        "subject": "Quotation {{ quotation_no }} from {{ company_name }}",
        "body": """<p>Dear {{ party_name }},</p>
<p>Please find attached your quotation <strong>{{ quotation_no }}</strong> valid till {{ valid_to }}.</p>
<p>Total: <strong>₹{{ grand_total }}</strong></p>
<p>Regards,<br>{{ company_name }}</p>""",
    },
    {
        "event_type": "token_completed",
        "channel": "sms",
        "name": "Weighment Complete (SMS)",
        "subject": None,
        "body": "Token #{{ token_no }}: Vehicle {{ vehicle_no }}, Net Wt {{ net_weight }} MT completed at {{ completed_at }}. - {{ company_name }}",
    },
    {
        "event_type": "token_completed",
        "channel": "telegram",
        "name": "Weighment Complete (Telegram)",
        "subject": None,
        "body": "⚖️ <b>Weighment Completed</b>\n\nToken: <b>#{{ token_no }}</b>\nVehicle: {{ vehicle_no }}\nParty: {{ party_name }}\nNet Weight: <b>{{ net_weight }} MT</b>\nCompleted: {{ completed_at }}\n\n— {{ company_name }}",
    },
]


async def seed_default_templates(db: AsyncSession, company_id: uuid.UUID) -> None:
    """Insert any missing default templates (upsert by event_type+channel)."""
    # Load existing (event_type, channel) pairs so we only insert missing ones
    existing_rows = (await db.execute(
        select(NotificationTemplate.event_type, NotificationTemplate.channel).where(
            NotificationTemplate.company_id == company_id
        )
    )).all()
    existing_keys = {(r.event_type, r.channel) for r in existing_rows}

    for t in DEFAULT_TEMPLATES:
        if (t["event_type"], t["channel"]) in existing_keys:
            continue  # already seeded
        db.add(NotificationTemplate(
            company_id=company_id,
            event_type=t["event_type"],
            channel=t["channel"],
            name=t["name"],
            subject=t.get("subject"),
            body=t["body"],
            is_enabled=True,
        ))
    await db.commit()


# ── Recipient helpers ──────────────────────────────────────────────────────────

async def _load_recipients(
    db: AsyncSession,
    company_id: uuid.UUID,
    channel: str,
    event_type: str,
) -> list[str]:
    """Return list of contact addresses for active recipients subscribed to event."""
    rows = (await db.execute(
        select(NotificationRecipient).where(
            NotificationRecipient.company_id == company_id,
            NotificationRecipient.channel == channel,
            NotificationRecipient.is_active == True,
        )
    )).scalars().all()

    contacts: list[str] = []
    for r in rows:
        try:
            event_list: list[str] = json.loads(r.event_types or '["*"]')
        except Exception:
            event_list = ["*"]
        if "*" in event_list or event_type in event_list:
            contacts.append(r.contact)
    return contacts


# ── Channel dispatch ───────────────────────────────────────────────────────────

async def _dispatch(channel: str, cfg: NotificationConfig, recipient: str, subject: str | None, body: str) -> None:
    """Send rendered message to a single recipient via the given channel."""
    if channel == "email":
        from app.integrations.notifications.email import send_email
        await send_email(
            smtp_host=cfg.smtp_host or "",
            smtp_port=cfg.smtp_port or 587,
            smtp_user=cfg.smtp_user or "",
            smtp_password=cfg.smtp_password or "",
            from_email=cfg.from_email or "",
            from_name=cfg.from_name or "",
            to_email=recipient,
            subject=subject or "",
            body_html=body,
            use_tls=cfg.use_tls,
        )
    elif channel == "sms":
        from app.integrations.notifications.sms import send_sms
        await send_sms(
            api_key=cfg.sms_api_key or "",
            sender_id=cfg.sms_sender_id or "",
            to_phone=recipient,
            message=body,
            route=cfg.sms_route or "4",
        )
    elif channel == "whatsapp":
        from app.integrations.notifications.whatsapp import send_whatsapp
        await send_whatsapp(
            api_url=cfg.wa_api_url or "",
            api_key=cfg.wa_api_key or "",
            to_phone=recipient,
            message=body,
        )
    elif channel == "telegram":
        from app.integrations.notifications.telegram_notify import send_telegram_notification
        await send_telegram_notification(
            bot_token=cfg.tg_bot_token or "",
            chat_id=recipient,
            text=body,
        )
    else:
        raise ValueError(f"Unknown channel: {channel}")


# ── Main dispatch ──────────────────────────────────────────────────────────────

async def send_notification(
    db: AsyncSession,
    company_id: uuid.UUID,
    event_type: str,
    context: dict[str, Any],
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> list[dict]:
    """
    Find enabled templates + configs for event_type, render, send to all recipients,
    and log each attempt. Returns list of log dicts with status.

    Recipients:
    1. Party contact from context (party_email / party_phone) — for email/sms/whatsapp
    2. All active notification_recipients subscribed to this event_type + channel
    """
    results = []

    # Load enabled templates for this event
    templates = (await db.execute(
        select(NotificationTemplate).where(
            NotificationTemplate.company_id == company_id,
            NotificationTemplate.event_type == event_type,
            NotificationTemplate.is_enabled == True,
        )
    )).scalars().all()

    if not templates:
        return results

    # Load configs (one per channel)
    configs_rows = (await db.execute(
        select(NotificationConfig).where(
            NotificationConfig.company_id == company_id,
            NotificationConfig.is_enabled == True,
        )
    )).scalars().all()
    configs = {c.channel: c for c in configs_rows}

    for tmpl in templates:
        cfg = configs.get(tmpl.channel)
        if not cfg:
            continue

        subject = render_template(tmpl.subject or "", context) if tmpl.subject else None
        body = render_template(tmpl.body, context)

        # Build list of recipients to notify
        recipients: list[str] = []

        # 1. Party contact from context (not for Telegram — parties don't have chat IDs)
        if tmpl.channel == "email":
            party_contact = context.get("party_email", "")
            if party_contact:
                recipients.append(party_contact)
        elif tmpl.channel in ("sms", "whatsapp"):
            party_contact = context.get("party_phone", "")
            if party_contact:
                recipients.append(party_contact)

        # 2. Named recipients subscribed to this event
        named = await _load_recipients(db, company_id, tmpl.channel, event_type)
        for c in named:
            if c not in recipients:
                recipients.append(c)

        if not recipients:
            continue

        for recipient in recipients:
            status = "pending"
            error_msg = None
            try:
                await _dispatch(tmpl.channel, cfg, recipient, subject, body)
                status = "sent"
            except Exception as e:
                status = "failed"
                error_msg = str(e)[:500]
                logger.warning(
                    "Notification send failed [%s/%s → %s]: %s",
                    tmpl.channel, event_type, recipient, e,
                )

            log_entry = NotificationLog(
                company_id=company_id,
                channel=tmpl.channel,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                recipient=recipient,
                subject=subject,
                body_preview=body[:500],
                status=status,
                error_message=error_msg,
            )
            db.add(log_entry)
            results.append({"channel": tmpl.channel, "recipient": recipient, "status": status, "error": error_msg})

    await db.commit()
    return results

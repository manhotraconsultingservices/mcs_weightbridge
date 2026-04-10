"""Notifications router — config, templates, test-send, delivery log, recipients."""
import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.notification import (
    NotificationConfig,
    NotificationTemplate,
    NotificationLog,
    NotificationRecipient,
)
from app.models.user import User
from app.models.company import Company

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_company_id(db: AsyncSession) -> uuid.UUID:
    company = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not company:
        raise HTTPException(404, "Company not found")
    return company.id


# ── Config ────────────────────────────────────────────────────────────────────

class ConfigPayload(BaseModel):
    channel: str
    is_enabled: bool = False
    # Email
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    use_tls: bool = True
    # SMS
    sms_api_key: Optional[str] = None
    sms_sender_id: Optional[str] = None
    sms_route: Optional[str] = "4"
    # WhatsApp
    wa_api_url: Optional[str] = None
    wa_api_key: Optional[str] = None
    wa_phone_number_id: Optional[str] = None
    # Telegram
    tg_bot_token: Optional[str] = None


VALID_CHANNELS = ("email", "sms", "whatsapp", "telegram")


@router.get("/config")
async def get_notification_configs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    company_id = await _get_company_id(db)
    rows = (await db.execute(
        select(NotificationConfig).where(NotificationConfig.company_id == company_id)
    )).scalars().all()

    # Always return all 4 channels
    existing = {r.channel: r for r in rows}
    result = []
    for channel in VALID_CHANNELS:
        cfg = existing.get(channel)
        if cfg:
            result.append(_cfg_out(cfg))
        else:
            result.append({"channel": channel, "is_enabled": False})
    return result


def _cfg_out(cfg: NotificationConfig) -> dict:
    return {
        "id": str(cfg.id),
        "channel": cfg.channel,
        "is_enabled": cfg.is_enabled,
        "smtp_host": cfg.smtp_host,
        "smtp_port": cfg.smtp_port,
        "smtp_user": cfg.smtp_user,
        "smtp_password": "***" if cfg.smtp_password else None,  # mask
        "from_email": cfg.from_email,
        "from_name": cfg.from_name,
        "use_tls": cfg.use_tls,
        "sms_api_key": "***" if cfg.sms_api_key else None,
        "sms_sender_id": cfg.sms_sender_id,
        "sms_route": cfg.sms_route,
        "wa_api_url": cfg.wa_api_url,
        "wa_api_key": "***" if cfg.wa_api_key else None,
        "wa_phone_number_id": cfg.wa_phone_number_id,
        "tg_bot_token": "***" if cfg.tg_bot_token else None,
    }


@router.put("/config/{channel}")
async def save_notification_config(
    channel: str,
    payload: ConfigPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if channel not in VALID_CHANNELS:
        raise HTTPException(400, f"channel must be one of: {', '.join(VALID_CHANNELS)}")

    company_id = await _get_company_id(db)
    cfg = (await db.execute(
        select(NotificationConfig).where(
            NotificationConfig.company_id == company_id,
            NotificationConfig.channel == channel,
        )
    )).scalar_one_or_none()

    if not cfg:
        cfg = NotificationConfig(company_id=company_id, channel=channel)
        db.add(cfg)

    cfg.is_enabled = payload.is_enabled
    cfg.smtp_host = payload.smtp_host
    cfg.smtp_port = payload.smtp_port
    cfg.smtp_user = payload.smtp_user
    if payload.smtp_password and payload.smtp_password != "***":
        cfg.smtp_password = payload.smtp_password
    cfg.from_email = payload.from_email
    cfg.from_name = payload.from_name
    cfg.use_tls = payload.use_tls
    if payload.sms_api_key and payload.sms_api_key != "***":
        cfg.sms_api_key = payload.sms_api_key
    cfg.sms_sender_id = payload.sms_sender_id
    cfg.sms_route = payload.sms_route
    cfg.wa_api_url = payload.wa_api_url
    if payload.wa_api_key and payload.wa_api_key != "***":
        cfg.wa_api_key = payload.wa_api_key
    cfg.wa_phone_number_id = payload.wa_phone_number_id
    if payload.tg_bot_token and payload.tg_bot_token != "***":
        cfg.tg_bot_token = payload.tg_bot_token

    await db.commit()
    return {"message": f"{channel} config saved"}


class TestSendPayload(BaseModel):
    channel: str
    recipient: str  # email, phone, or Telegram chat_id


@router.post("/config/{channel}/test")
async def test_send(
    channel: str,
    payload: TestSendPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Send a test message to verify configuration."""
    company_id = await _get_company_id(db)
    cfg = (await db.execute(
        select(NotificationConfig).where(
            NotificationConfig.company_id == company_id,
            NotificationConfig.channel == channel,
        )
    )).scalar_one_or_none()

    if not cfg:
        raise HTTPException(404, "Config not found")

    try:
        if channel == "email":
            from app.integrations.notifications.email import send_email
            await send_email(
                smtp_host=cfg.smtp_host or "",
                smtp_port=cfg.smtp_port or 587,
                smtp_user=cfg.smtp_user or "",
                smtp_password=cfg.smtp_password or "",
                from_email=cfg.from_email or "",
                from_name=cfg.from_name or "",
                to_email=payload.recipient,
                subject="Test Notification — Weighbridge",
                body_html="<p>This is a test email from your Weighbridge Invoice Software.</p>",
                use_tls=cfg.use_tls,
            )
        elif channel == "sms":
            from app.integrations.notifications.sms import send_sms
            await send_sms(
                api_key=cfg.sms_api_key or "",
                sender_id=cfg.sms_sender_id or "",
                to_phone=payload.recipient,
                message="Test SMS from Weighbridge Invoice Software.",
                route=cfg.sms_route or "4",
            )
        elif channel == "whatsapp":
            from app.integrations.notifications.whatsapp import send_whatsapp
            await send_whatsapp(
                api_url=cfg.wa_api_url or "",
                api_key=cfg.wa_api_key or "",
                to_phone=payload.recipient,
                message="Test WhatsApp from Weighbridge Invoice Software.",
            )
        elif channel == "telegram":
            from app.integrations.notifications.telegram_notify import send_telegram_notification
            await send_telegram_notification(
                bot_token=cfg.tg_bot_token or "",
                chat_id=payload.recipient,
                text="✅ Test message from <b>Weighbridge Invoice Software</b>.",
            )
        return {"success": True, "message": f"Test {channel} sent to {payload.recipient}"}
    except Exception as e:
        raise HTTPException(400, f"Send failed: {e}")


# ── Templates ─────────────────────────────────────────────────────────────────

class TemplatePayload(BaseModel):
    event_type: str
    channel: str
    name: str
    subject: Optional[str] = None
    body: str
    is_enabled: bool = True


@router.get("/templates")
async def list_templates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company_id = await _get_company_id(db)

    # Seed defaults on first load
    from app.integrations.notifications.service import seed_default_templates
    await seed_default_templates(db, company_id)

    rows = (await db.execute(
        select(NotificationTemplate)
        .where(NotificationTemplate.company_id == company_id)
        .order_by(NotificationTemplate.event_type, NotificationTemplate.channel)
    )).scalars().all()

    return [_tmpl_out(t) for t in rows]


def _tmpl_out(t: NotificationTemplate) -> dict:
    return {
        "id": str(t.id),
        "event_type": t.event_type,
        "channel": t.channel,
        "name": t.name,
        "subject": t.subject,
        "body": t.body,
        "is_enabled": t.is_enabled,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.post("/templates", status_code=201)
async def create_template(
    payload: TemplatePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    company_id = await _get_company_id(db)
    t = NotificationTemplate(company_id=company_id, **payload.model_dump())
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _tmpl_out(t)


@router.put("/templates/{template_id}")
async def update_template(
    template_id: uuid.UUID,
    payload: TemplatePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    t = (await db.execute(select(NotificationTemplate).where(NotificationTemplate.id == template_id))).scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Template not found")
    for k, v in payload.model_dump().items():
        setattr(t, k, v)
    await db.commit()
    return _tmpl_out(t)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    t = (await db.execute(select(NotificationTemplate).where(NotificationTemplate.id == template_id))).scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Template not found")
    await db.delete(t)
    await db.commit()


# ── Recipients ────────────────────────────────────────────────────────────────

class RecipientPayload(BaseModel):
    name: str
    channel: str                          # email | sms | telegram
    contact: str                          # email / phone / Telegram chat_id
    event_types: list[str] = ["*"]        # ["*"] = all events
    is_active: bool = True


def _recip_out(r: NotificationRecipient) -> dict:
    try:
        event_list = json.loads(r.event_types or '["*"]')
    except Exception:
        event_list = ["*"]
    return {
        "id": str(r.id),
        "name": r.name,
        "channel": r.channel,
        "contact": r.contact,
        "event_types": event_list,
        "is_active": r.is_active,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/recipients")
async def list_recipients(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    company_id = await _get_company_id(db)
    rows = (await db.execute(
        select(NotificationRecipient)
        .where(NotificationRecipient.company_id == company_id)
        .order_by(NotificationRecipient.channel, NotificationRecipient.name)
    )).scalars().all()
    return [_recip_out(r) for r in rows]


@router.post("/recipients", status_code=201)
async def create_recipient(
    payload: RecipientPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if payload.channel not in ("email", "sms", "telegram"):
        raise HTTPException(400, "channel must be email, sms, or telegram")
    company_id = await _get_company_id(db)
    r = NotificationRecipient(
        company_id=company_id,
        name=payload.name,
        channel=payload.channel,
        contact=payload.contact,
        event_types=json.dumps(payload.event_types),
        is_active=payload.is_active,
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return _recip_out(r)


@router.put("/recipients/{recipient_id}")
async def update_recipient(
    recipient_id: uuid.UUID,
    payload: RecipientPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if payload.channel not in ("email", "sms", "telegram"):
        raise HTTPException(400, "channel must be email, sms, or telegram")
    r = (await db.execute(
        select(NotificationRecipient).where(NotificationRecipient.id == recipient_id)
    )).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "Recipient not found")
    r.name = payload.name
    r.channel = payload.channel
    r.contact = payload.contact
    r.event_types = json.dumps(payload.event_types)
    r.is_active = payload.is_active
    await db.commit()
    return _recip_out(r)


@router.delete("/recipients/{recipient_id}", status_code=204)
async def delete_recipient(
    recipient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    r = (await db.execute(
        select(NotificationRecipient).where(NotificationRecipient.id == recipient_id)
    )).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "Recipient not found")
    await db.delete(r)
    await db.commit()


# ── Delivery Log ──────────────────────────────────────────────────────────────

@router.get("/log")
async def notification_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    channel: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company_id = await _get_company_id(db)
    q = select(NotificationLog).where(NotificationLog.company_id == company_id)
    if channel:
        q = q.where(NotificationLog.channel == channel)
    if status:
        q = q.where(NotificationLog.status == status)
    if event_type:
        q = q.where(NotificationLog.event_type == event_type)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar()
    rows = (await db.execute(
        q.order_by(NotificationLog.sent_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return {
        "items": [_log_out(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _log_out(r: NotificationLog) -> dict:
    return {
        "id": str(r.id),
        "channel": r.channel,
        "event_type": r.event_type,
        "entity_type": r.entity_type,
        "entity_id": r.entity_id,
        "recipient": r.recipient,
        "subject": r.subject,
        "body_preview": r.body_preview,
        "status": r.status,
        "error_message": r.error_message,
        "sent_at": r.sent_at.isoformat() if r.sent_at else None,
    }

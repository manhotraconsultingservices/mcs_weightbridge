"""Notification models — config, templates, delivery log, recipients."""
import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class NotificationConfig(Base):
    """Per-channel notification credentials/settings. One row per channel per company."""
    __tablename__ = "notification_config"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    channel: Mapped[str] = mapped_column(String(20))  # email | sms | whatsapp | telegram

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── Email (SMTP) ──────────────────────────────────────────────────────────
    smtp_host: Mapped[str | None] = mapped_column(String(200))
    smtp_port: Mapped[int | None] = mapped_column(Integer)          # 587 / 465 / 25
    smtp_user: Mapped[str | None] = mapped_column(String(200))
    smtp_password: Mapped[str | None] = mapped_column(String(500))  # stored plain (local deploy)
    from_email: Mapped[str | None] = mapped_column(String(200))
    from_name: Mapped[str | None] = mapped_column(String(200))
    use_tls: Mapped[bool] = mapped_column(Boolean, default=True)

    # ── SMS (MSG91) ───────────────────────────────────────────────────────────
    sms_api_key: Mapped[str | None] = mapped_column(String(500))
    sms_sender_id: Mapped[str | None] = mapped_column(String(20))   # 6-char sender ID
    sms_route: Mapped[str | None] = mapped_column(String(10), default="4")  # transactional

    # ── WhatsApp (WATI / Interakt) ────────────────────────────────────────────
    wa_api_url: Mapped[str | None] = mapped_column(String(500))     # e.g. https://live-server.wati.io
    wa_api_key: Mapped[str | None] = mapped_column(String(500))
    wa_phone_number_id: Mapped[str | None] = mapped_column(String(50))

    # ── Telegram ──────────────────────────────────────────────────────────────
    tg_bot_token: Mapped[str | None] = mapped_column(String(500))   # BotFather token

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NotificationTemplate(Base):
    """Customizable message templates per event + channel."""
    __tablename__ = "notification_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))

    # event_type: invoice_finalized | payment_received | quotation_sent |
    #             token_completed | invoice_overdue | low_balance
    event_type: Mapped[str] = mapped_column(String(50))
    channel: Mapped[str] = mapped_column(String(20))   # email | sms | whatsapp

    name: Mapped[str] = mapped_column(String(200))     # human label
    subject: Mapped[str | None] = mapped_column(String(500))   # email only
    body: Mapped[str] = mapped_column(Text)            # Jinja2 template text
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NotificationRecipient(Base):
    """Named recipients who get notified for specific event types."""
    __tablename__ = "notification_recipients"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))

    name: Mapped[str] = mapped_column(String(200))        # Display name, e.g. "Owner WhatsApp"
    channel: Mapped[str] = mapped_column(String(20))       # email | sms | telegram
    contact: Mapped[str] = mapped_column(String(300))      # email address / phone / Telegram chat_id

    # JSON array of event_type strings, or ["*"] to receive all events
    event_types: Mapped[str] = mapped_column(Text, default='["*"]')

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationLog(Base):
    """Delivery log — one row per send attempt."""
    __tablename__ = "notification_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))

    channel: Mapped[str] = mapped_column(String(20))      # email | sms | whatsapp
    event_type: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str | None] = mapped_column(String(50))   # invoice | token | payment
    entity_id: Mapped[str | None] = mapped_column(String(50))

    recipient: Mapped[str] = mapped_column(String(300))   # email address or phone number
    subject: Mapped[str | None] = mapped_column(String(500))
    body_preview: Mapped[str | None] = mapped_column(String(500))  # first 500 chars

    status: Mapped[str] = mapped_column(String(20), default="pending")  # sent | failed | pending
    error_message: Mapped[str | None] = mapped_column(Text)

    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

"""SMTP email sender."""
import asyncio
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging

logger = logging.getLogger(__name__)


async def send_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    from_email: str,
    from_name: str,
    to_email: str,
    subject: str,
    body_html: str,
    use_tls: bool = True,
) -> None:
    """Send an email via SMTP. Raises on failure."""

    def _send():
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
        msg["To"] = to_email

        # Plain-text fallback (strip basic tags)
        import re
        plain = re.sub(r"<[^>]+>", "", body_html).strip()
        msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        if use_tls and smtp_port == 465:
            # SMTPS (implicit TLS)
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
                server.login(smtp_user, smtp_password)
                server.sendmail(from_email, to_email, msg.as_string())
        else:
            # STARTTLS or plain
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.ehlo()
                if use_tls:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.sendmail(from_email, to_email, msg.as_string())

    await asyncio.get_event_loop().run_in_executor(None, _send)
    logger.info("Email sent to %s subject=%s", to_email, subject)

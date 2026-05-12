"""Email sending. Logs to stdout in dev (when SMTP_HOST is empty)."""

import logging

import aiosmtplib
from email.message import EmailMessage

from salespilot.config import get_settings

log = logging.getLogger(__name__)


async def send_magic_link_email(to_address: str, link: str) -> None:
    settings = get_settings()
    subject = "Your SalesPilot login link"
    body = (
        f"Hi,\n\n"
        f"Click the link below to sign in to SalesPilot. It expires in "
        f"{settings.magic_link_ttl_minutes} minutes.\n\n"
        f"{link}\n\n"
        f"If you didn't request this, you can ignore this email.\n"
    )

    if not settings.smtp_host:
        # Dev: log and return.
        log.warning(
            "SMTP_HOST not configured; magic-link logged instead of mailed. "
            "to=%s link=%s",
            to_address,
            link,
        )
        return

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password.get_secret_value() or None,
        start_tls=settings.smtp_starttls,
    )

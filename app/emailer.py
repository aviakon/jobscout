"""Optional SMTP delivery for digests. Inert unless SMTP_* env vars are set."""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app import config

log = logging.getLogger(__name__)


def send_email(subject: str, html_body: str, text_body: str = "") -> bool:
    """Send one digest email. Returns False (no-op) if SMTP isn't configured."""
    if not config.email_configured():
        log.info("email not configured — skipping send")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.DIGEST_FROM
    msg["To"] = config.DIGEST_TO
    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
        server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASS)
        server.sendmail(config.DIGEST_FROM, [config.DIGEST_TO], msg.as_string())
    log.info("digest email sent to %s", config.DIGEST_TO)
    return True

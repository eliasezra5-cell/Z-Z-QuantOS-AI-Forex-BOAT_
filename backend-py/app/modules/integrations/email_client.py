"""Email SMTP alert client (Feature 4, additive).

Sends rendered reports (and other text/HTML messages) over SMTP using only the
Python standard library (``smtplib`` + ``email.mime``). Mirrors the Telegram /
WhatsApp client contracts: outbound sends are recorded to the
``integration_outbox`` collection and a structured result is returned — real
network calls only happen when SMTP credentials are configured, and errors are
never raised to callers.
"""
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db

DEFAULT_TIMEOUT_SECONDS = 15


def _env(key, default=""):
    return os.environ.get(key, default)


class EmailClientError(Exception):
    """Raised when a real SMTP send fails (caught and recorded by callers)."""


class EmailClient:
    """Thin standard-library SMTP client for report delivery."""

    id = "email"
    name = "Email (SMTP)"

    def __init__(self, host=None, port=None, user=None, password=None, from_addr=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, starttls=None):
        self.host = (host if host is not None else _env("SMTP_HOST")).strip()
        try:
            self.port = int(port if port is not None else _env("SMTP_PORT") or 587)
        except (TypeError, ValueError):
            self.port = 587
        self.user = (user if user is not None else _env("SMTP_USER")).strip()
        self.password = (password if password is not None else _env("SMTP_PASSWORD")).strip()
        self.from_addr = (from_addr if from_addr is not None else _env("EMAIL_FROM")).strip()
        if starttls is None:
            starttls = str(_env("SMTP_STARTTLS", "true")).lower() in ("1", "true", "yes", "on")
        self.starttls = starttls
        self.timeout_seconds = timeout_seconds
        self.last_error = None

    def is_configured(self):
        return bool(self.host and self.from_addr)

    def _record(self, status, detail, meta=None):
        return db.collection("integration_outbox").insert({
            "integrationId": "email",
            "kind": "message",
            "status": status,
            "direction": "outbound",
            "to": str(_env("EMAIL_TO") or ""),
            "detail": detail,
            "createdAt": int(time.time() * 1000),
            **(meta or {}),
        })

    def send_email(self, subject, html_body=None, text_body=None, to=None):
        """Send an email (real SMTP call when configured; outbox-pending otherwise).

        Returns the outbox record exactly like the Telegram/WhatsApp clients.
        """
        to = to or getattr(self, "to_addr", "") or _env("EMAIL_TO")
        if not self.is_configured():
            return self._record("pending", "SMTP not configured (SMTP_HOST / EMAIL_FROM)")
        if not to:
            return self._record("pending", "no recipient (EMAIL_TO)")
        try:
            sent = self._send(subject, html_body, text_body, to)
        except Exception as err:  # noqa: BLE001 - SMTP errors surface as structured failures
            self.last_error = str(err)
            logger.error("email send failed", {"error": str(err), "to": to})
            return self._record("failed", f"smtp-error: {err}")
        return self._record("sent", sent)

    def _send(self, subject, html_body, text_body, to):
        recipients = [r.strip() for r in str(to).split(",") if r.strip()]
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(recipients)
        if text_body:
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as smtp:
            if self.starttls:
                smtp.starttls()
            if self.user or self.password:
                smtp.login(self.user, self.password)
            smtp.sendmail(self.from_addr, recipients, msg.as_string())
        return f"sent to {', '.join(recipients)}"

    def self_test(self):
        """Return configuration status (no real send, mirrors other clients)."""
        if not self.is_configured():
            return {"success": False, "detail": "SMTP_HOST / EMAIL_FROM missing"}
        return {"success": True, "detail": f"smtp configured ({self.host}:{self.port})"}


email_client = EmailClient()


def init_email_client():
    logger.info(f"Email integration initialized (smtp={'configured' if email_client.is_configured() else 'missing'})")
    return email_client

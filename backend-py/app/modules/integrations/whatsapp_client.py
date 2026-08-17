"""WhatsApp Cloud API alert client (additive).

Sends AI suggestion alerts over the official Meta WhatsApp Business Platform
Cloud API (``graph.facebook.com``) and verifies incoming webhook signatures
(``X-Hub-Signature-256``). The client degrades gracefully: when credentials are
missing, outbound sends are recorded to the ``integration_outbox`` collection as
"pending" (same contract as the Telegram client) so the rest of the system keeps
working. Real network calls only happen when a token is configured.
"""
import hashlib
import hmac
import os
import time

import httpx

from ...foundation.event_bus import event_bus
from ...foundation.json_store import db
from ...foundation.logger import logger

API_BASE = "https://graph.facebook.com/v21.0/{phone_number_id}/messages"
DEFAULT_TIMEOUT_SECONDS = 10


def _env(key):
    return os.environ.get(key, "")


class WhatsAppError(Exception):
    """Raised when a real WhatsApp Cloud API call fails."""


class WhatsAppAlertClient:
    """Thin real client over the WhatsApp Cloud API (sendMessage)."""

    id = "whatsapp"
    name = "WhatsApp (official Cloud API)"

    def __init__(self, token=None, phone_number_id=None, admin_number=None, webhook_secret=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
        self.token = (token or _env("WHATSAPP_TOKEN")).strip()
        self.phone_number_id = (phone_number_id or _env("WHATSAPP_PHONE_NUMBER_ID")).strip()
        self.admin_number = (admin_number or _env("WHATSAPP_ADMIN_NUMBER")).strip()
        self.webhook_secret = (webhook_secret or _env("WHATSAPP_WEBHOOK_SECRET")).strip()
        self.timeout_seconds = timeout_seconds
        self.last_error = None

    def is_configured(self):
        return bool(self.token and self.phone_number_id and self.admin_number)

    def _url(self):
        return API_BASE.format(phone_number_id=self.phone_number_id)

    def verify_signature(self, raw_body, signature):
        """Constant-time HMAC-SHA256 check of the raw webhook body.

        ``signature`` is the ``X-Hub-Signature-256`` header value ("sha256=...") sent
        by Meta. ``raw_body`` MUST be the exact raw request body.
        """
        if not signature or not self.webhook_secret:
            return False
        body = raw_body if isinstance(raw_body, bytes) else str(raw_body).encode("utf-8")
        expected = "sha256=" + hmac.new(self.webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, str(signature))

    # ------------------------------------------------------------------ #
    # Sending
    # ------------------------------------------------------------------ #
    def send_text(self, to, text, silent=None):
        """Send a text message to a WhatsApp number (real API call when configured).

        Mirrors the Telegram client contract: network/API failures are recorded
        to the ``integration_outbox`` collection as "failed" and returned — never
        raised — so callers (webhooks, event listeners) keep working.
        """
        to = to or self.admin_number
        if not self.is_configured():
            return self._record("pending", "whatsapp not configured (WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID / WHATSAPP_ADMIN_NUMBER)")
        if not to:
            return self._record("pending", "no recipient phone number configured")
        try:
            res = httpx.post(
                self._url(),
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": str(to),
                    "type": "text",
                    "text": {"body": text, "preview_url": False},
                },
                timeout=self.timeout_seconds,
            )
            data = res.json()
        except Exception as err:  # noqa: BLE001 - network errors surface as structured failures
            self.last_error = str(err)
            return self._record("failed", f"whatsapp-api-error: {err}")
        if res.status_code >= 400:
            self.last_error = str(data.get("error", data))
            return self._record("failed", f"whatsapp-api-rejected: {data}")
        return self._record("sent", data)

    def send_suggestion_alert(self, suggested):
        """Format and send an AI suggestion alert to the admin number.

        The message follows the interactive template: AI Suggests BUY XAUUSD,
        confidence %, and a '1' (execute) / '2' (reject) reply prompt.
        """
        if not self.is_configured():
            return self._record("pending", "whatsapp not configured")
        symbol = str(suggested.get("symbol") or "?")
        side = str(suggested.get("side") or "?").upper()
        confidence = suggested.get("confidence") or 0
        try:
            pct = int(round(float(confidence) * 100))
        except (TypeError, ValueError):
            pct = 0
        text = f"AI Suggests: {side} {symbol}. Conf: {pct}%. Reply '1' to Execute, '2' to Reject."
        return self.send_text(self.admin_number, text)

    def self_test(self):
        """Verify the token by sending a test message to the admin number."""
        if not self.is_configured():
            return {"success": False, "detail": "WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID / WHATSAPP_ADMIN_NUMBER missing"}
        result = self.send_text(self.admin_number, "QuantOS AI WhatsApp test: connection OK.")
        return {"success": result.get("status") == "sent", "detail": result.get("detail")}

    # ------------------------------------------------------------------ #
    # Outbox + dynamic config
    # ------------------------------------------------------------------ #
    def _record(self, status, detail):
        return db.collection("integration_outbox").insert({
            "integrationId": "whatsapp",
            "kind": "message",
            "status": status,
            "direction": "outbound",
            "to": str(self.admin_number or ""),
            "detail": detail,
            "createdAt": int(time.time() * 1000),
        })

    def apply_config(self, config):
        """Push a decrypted connections config into the client (additive)."""
        config = config or {}
        if config.get("api_token"):
            self.token = str(config["api_token"]).strip()
        if config.get("phone_number_id"):
            self.phone_number_id = str(config["phone_number_id"]).strip()
        if config.get("admin_number"):
            self.admin_number = str(config["admin_number"]).strip()
        if config.get("webhook_secret"):
            self.webhook_secret = str(config["webhook_secret"]).strip()


whatsapp_alert_client = WhatsAppAlertClient()

# Default confidence band; tunable at runtime via the conversational assistant
# (persisted through ``ai/confidence_gates.py``). The live band is read from
# the gates in ``_on_suggested_trade_created``; these constants keep the same
# defaults and remain the public defaults for callers/tests.
SUGGESTED_TRADE_MIN_CONFIDENCE = 0.70
SUGGESTED_TRADE_MAX_CONFIDENCE = 0.90

_listener_installed = False


def _send_suggestion_alert_threaded(suggested):
    """Send the alert off-thread so the event emitter never blocks on HTTP."""
    import threading

    def _worker():
        try:
            whatsapp_alert_client.send_suggestion_alert(suggested)
        except Exception as err:  # noqa: BLE001 - alert failures never propagate
            logger.error("whatsapp suggestion alert failed", {"error": str(err)})

    threading.Thread(target=_worker, daemon=True).start()


def _on_suggested_trade_created(event):
    """Fire a WhatsApp alert for AI-suggested trades in the 70-89% band.

    Trades at/above 90% are auto-executed; below 70% are discarded. Only the
    70-89% "suggested" band needs human approval, so that is the only band that
    triggers an alert.
    """
    suggested = (event.get("payload") or {}).get("suggested") or {}
    confidence = suggested.get("confidence")
    try:
        score = float(confidence)
    except (TypeError, ValueError):
        return
    from ..ai.confidence_gates import get_gates  # lazy import

    gates = get_gates()
    if not (gates["suggest"] <= score < gates["auto_execute"]):
        return
    from .connections_manager import connections_manager

    config = connections_manager.get_config("whatsapp")
    if not config.get("is_active") and not config.get("api_token"):
        return
    _send_suggestion_alert_threaded(suggested)


def init_whatsapp_alerts():
    global _listener_installed
    if not _listener_installed:
        event_bus.on("suggested:trade-created", _on_suggested_trade_created)
        _listener_installed = True
        logger.info("WhatsApp suggestion alert listener installed")
    logger.info(f"WhatsApp integration initialized (token={'configured' if whatsapp_alert_client.token else 'missing'})")
    return whatsapp_alert_client

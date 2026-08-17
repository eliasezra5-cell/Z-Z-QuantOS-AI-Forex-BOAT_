"""Integrations service (additive Module 3.2 — real transports).

Replaces the simulated adapter transports of the original service with real
third-party HTTP clients:

  - ``telegram``    -> ``TelegramBotClient`` (real Telegram Bot API via httpx)
  - ``discord``     -> ``DiscordAlertClient`` (real Discord webhook via httpx)
  - ``tradingview`` -> ``TradingViewWebhook`` (HMAC-SHA256 verified, risk-gated)
  - ``webhooks``    -> real outbound HTTP delivery with optional HMAC signing
  - ``mt5``         -> real MT5 adapter connection state

Every adapter degrades gracefully: when credentials are missing, outbound
messages are recorded to the ``integration_outbox`` collection as "pending"
so the rest of the system keeps working (same contract as the simulated
service, but with real network calls when configured).
"""
import hashlib
import hmac
import json
import time

import httpx

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from .telegram_bot import BOT_COMMANDS, telegram_bot as _telegram_singleton
from .discord_client import discord_alert_client as _discord_singleton
from .tradingview_webhook import tradingview_webhook as _tradingview_singleton

INTEGRATIONS = [
    {"id": "mt5", "name": "MetaTrader 5", "type": "broker", "status": "connected", "config": {"host": "127.0.0.1", "port": 443}},
    {"id": "tradingview", "name": "TradingView", "type": "charting", "status": "available", "config": {}},
    {"id": "discord", "name": "Discord", "type": "notification", "status": "available", "config": {}},
    {"id": "telegram", "name": "Telegram", "type": "notification", "status": "available", "config": {"botToken": "***"}},
    {"id": "whatsapp", "name": "WhatsApp", "type": "notification", "status": "disabled", "config": {}},
    {"id": "gdrive", "name": "Google Drive", "type": "storage", "status": "available", "config": {}},
    {"id": "dropbox", "name": "Dropbox", "type": "storage", "status": "available", "config": {}},
    {"id": "slack", "name": "Slack", "type": "notification", "status": "available", "config": {}},
    {"id": "webhooks", "name": "Custom Webhooks", "type": "automation", "status": "available", "config": {}},
]


class IntegrationAdapter:
    """Base adapter wrapping a real third-party client."""

    id = "base"
    name = "Base Integration Adapter"
    integration_type = "generic"

    def __init__(self, client=None, config=None):
        self.client = client
        self.config = config or {}

    def update_config(self, config):
        self.config = config or {}
        self._apply_config()

    def _apply_config(self):
        """Push the stored config into the real client."""

    def self_test(self):
        """Delegate to the real client's self-test (real checks when possible)."""
        if self.client is None:
            return {"success": bool(self.config), "detail": f"{self.name} config {'present' if self.config else 'missing'}"}
        return self.client.self_test()

    def _outbox(self, kind, status, meta=None):
        return db.collection("integration_outbox").insert({
            "integrationId": self.id,
            "kind": kind,
            "status": status,
            "direction": "outbound",
            "createdAt": int(time.time() * 1000),
            **(meta or {}),
        })


class TelegramAdapter(IntegrationAdapter):
    id = "telegram"
    name = "Telegram"
    integration_type = "notification"

    def __init__(self, config=None, client=None):
        super().__init__(client or _telegram_singleton, config)
        self._apply_config()

    def _apply_config(self):
        token = self.config.get("botToken") or ""
        if token and token != "***":
            self.client.token = token.strip()
        chat_id = self.config.get("chatId")
        if chat_id:
            self.client.chat_id = str(chat_id)

    def send_message(self, chat_id, text):
        """Send via the real Telegram Bot API (outbox-pending when no token)."""
        return self.client.send_message(chat_id, text)

    def parse_command(self, text):
        return self.client.parse_command(text)

    def handle_command(self, text, chat_id=None):
        return self.client.handle_command(text, chat_id)

    def self_test(self):
        return self.client.self_test()


class DiscordAdapter(IntegrationAdapter):
    id = "discord"
    name = "Discord"
    integration_type = "notification"

    def __init__(self, config=None, client=None):
        super().__init__(client or _discord_singleton, config)
        self._apply_config()

    def _apply_config(self):
        url = self.config.get("webhookUrl") or ""
        if url:
            self.client.webhook_url = url.strip()

    def validate_webhook_url(self, url=None):
        return self.client._validate_webhook_url(url or self.client.webhook_url)

    def send_webhook(self, url, content):
        """Deliver via the real Discord webhook API (outbox-pending when missing)."""
        return self.client.send_alert(content, url=url)

    def self_test(self):
        return self.client.self_test()


class TradingViewAdapter(IntegrationAdapter):
    id = "tradingview"
    name = "TradingView"
    integration_type = "charting"

    def __init__(self, config=None, client=None):
        super().__init__(client or _tradingview_singleton, config)
        self._apply_config()

    def _apply_config(self):
        secret = self.config.get("secret") or ""
        if secret:
            self.client.secret = str(secret).encode("utf-8")

    def verify_webhook_signature(self, payload, signature):
        """Constant-time HMAC-SHA256 check against the real secret."""
        return self.client.verify_signature(payload, signature)

    def process(self, payload_bytes, signature, timestamp=None):
        return self.client.process(payload_bytes, signature, timestamp)

    def handle_alert(self, payload):
        """Normalize and risk-gate an alert via the real webhook pipeline."""
        payload = payload or {}
        signal = self.client.normalize_alert(payload)
        gated = self.client.risk_gate(signal)
        event_bus.emit("integration:tradingview-alert", signal)
        return gated

    def self_test(self):
        return self.client.self_test()


class WebhookAdapter(IntegrationAdapter):
    id = "webhooks"
    name = "Custom Webhooks"
    integration_type = "automation"

    def __init__(self, config=None):
        super().__init__(None, config)
        self.timeout_seconds = 10

    def _sign(self, payload, secret):
        body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hmac.new(str(secret).encode("utf-8"), body, hashlib.sha256).hexdigest()

    def deliver(self, url, payload, secret=None):
        """Deliver a webhook over real HTTP, optionally HMAC-SHA256 signed."""
        if not url:
            return None
        headers = {"Content-Type": "application/json"}
        signature = None
        if secret:
            signature = self._sign(payload, secret)
            headers["X-Webhook-Signature"] = signature
        try:
            res = httpx.post(url, json=payload, headers=headers, timeout=self.timeout_seconds)
            status = "sent" if res.status_code < 400 else "failed"
            detail = f"http-{res.status_code}"
        except Exception as err:  # noqa: BLE001 - network errors surface as structured failures
            status = "failed"
            detail = str(err)
        return self._outbox(kind="delivery", status=status, meta={
            "channel": "webhook",
            "url": str(url),
            "payload": payload,
            "signed": bool(signature),
            "signature": signature,
            "detail": detail,
        })

    def self_test(self):
        return {"success": bool(self.config), "detail": "webhook config present" if self.config else "webhook config missing"}


class MT5Adapter(IntegrationAdapter):
    id = "mt5"
    name = "MetaTrader 5"
    integration_type = "broker"

    def __init__(self, config=None):
        super().__init__(None, config or {})

    def get_status(self):
        from ..mt5.adapter import mt5_state  # lazy import
        return mt5_state.to_dict()

    def self_test(self):
        state = self.get_status()
        return {
            "success": bool(state.get("connected")),
            "detail": "connected" if state.get("connected") else "not connected",
            "state": state,
        }


def _make_adapter(row):
    """Instantiate the concrete adapter backed by a real client for an integration row."""
    integration_id = row["id"]
    config = row.get("config") or {}
    if integration_id == "telegram":
        return TelegramAdapter(config)
    if integration_id == "discord":
        return DiscordAdapter(config)
    if integration_id == "tradingview":
        return TradingViewAdapter(config)
    if integration_id == "webhooks":
        return WebhookAdapter(config)
    if integration_id == "mt5":
        return MT5Adapter(config)
    return IntegrationAdapter(None, config)


adapter_registry = {}


def init_integrations():
    col = db.collection("integrations")
    for i in INTEGRATIONS:
        if not col.find_one({"id": i["id"]}):
            col.insert(i)
    adapter_registry.clear()
    for row in col.find({}):
        adapter_registry[row["id"]] = _make_adapter(row)
    logger.info("Integrations initialized (real transports)")
    return {
        "listIntegrations": list_integrations,
        "configureIntegration": configure_integration,
        "testIntegration": test_integration,
        "handleIntegrationEvent": handle_integration_event,
        "outboxList": outbox_list,
    }


def list_integrations():
    return db.collection("integrations").find({})


def configure_integration(integration_id, config):
    col = db.collection("integrations")
    row = col.find_one({"id": integration_id})
    if not row:
        return None
    updated = col.update(integration_id, {"config": config, "status": "configured", "updatedAt": int(time.time() * 1000)})
    adapter = adapter_registry.get(integration_id)
    if adapter is not None:
        adapter.update_config(config)
    event_bus.emit("integration:configured", {"id": integration_id})
    return updated


def test_integration(integration_id):
    row = db.collection("integrations").find_one({"id": integration_id})
    if not row:
        return None
    if row["status"] == "disabled":
        return {"integrationId": integration_id, "success": False, "latencyMs": 0, "detail": "integration disabled", "testedAt": int(time.time() * 1000)}
    adapter = adapter_registry.get(integration_id)
    if adapter is None:
        adapter = IntegrationAdapter(None, row.get("config") or {})
    start = time.monotonic()
    result = adapter.self_test()
    latency_ms = round((time.monotonic() - start) * 1000, 1)
    success = bool(result.get("success"))
    out = {
        "integrationId": integration_id,
        "success": success,
        "latencyMs": latency_ms,
        "detail": result.get("detail"),
        "testedAt": int(time.time() * 1000),
    }
    if success:
        db.collection("integrations").update(integration_id, {"status": "connected"})
    return out


def handle_integration_event(integration_id, payload):
    """Dispatch an integration event to the real adapter transport."""
    payload = payload or {}
    adapter = adapter_registry.get(integration_id)
    if adapter is None:
        return None
    if integration_id == "telegram":
        return adapter.send_message(payload.get("chatId"), payload.get("text"))
    if integration_id == "discord":
        return adapter.send_webhook(payload.get("url"), payload.get("content"))
    if integration_id == "tradingview":
        return adapter.handle_alert(payload)
    if integration_id == "webhooks":
        return adapter.deliver(payload.get("url"), payload.get("payload"), payload.get("secret"))
    return None


def outbox_list(limit=50):
    return db.collection("integration_outbox").find({}, {"sort": ["createdAt", "desc"], "limit": int(limit)})

"""Real Discord integration for alerts (additive Module 3.2).

Sends alerts to a Discord channel via a webhook URL using the real Discord
Webhook API over HTTPS (httpx). When the ``discord.py`` package is installed
and a bot token is configured, the webhook can also be created through the
``discord`` library's ``Webhook.from_url`` helper — the code always prefers the
httpx path so the module has no hard dependency.

When ``DISCORD_WEBHOOK_URL`` is unset, sends are recorded to the
``integration_outbox`` collection as "pending" so the rest of the system keeps
working (same graceful degradation as the existing simulated adapter).
"""
import urllib.parse

import httpx

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db

DISCORD_API_BASE = "https://discord.com/api"
DEFAULT_TIMEOUT_SECONDS = 10


class DiscordError(Exception):
    """Raised when a real Discord webhook delivery fails."""


def _env(key):
    import os
    return os.environ.get(key, "")


class DiscordAlertClient:
    """Real Discord webhook client for alert delivery."""

    id = "discord"
    name = "Discord (real webhook)"

    def __init__(self, webhook_url=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
        self.webhook_url = (webhook_url or _env("DISCORD_WEBHOOK_URL")).strip()
        self.timeout_seconds = timeout_seconds
        self.last_error = None

    # ------------------------------------------------------------------ #
    # Webhook helpers
    # ------------------------------------------------------------------ #
    def _validate_webhook_url(self, url=None):
        """Validate a Discord webhook URL (must be a public Discord endpoint)."""
        candidate = (url or self.webhook_url).strip()
        if not candidate:
            return {"valid": False, "reason": "empty-url"}
        try:
            parts = urllib.parse.urlparse(candidate)
        except ValueError:
            return {"valid": False, "reason": "malformed-url"}
        if parts.scheme not in ("http", "https"):
            return {"valid": False, "reason": "unsupported-scheme"}
        host = (parts.netloc or "").lower()
        if host not in ("discord.com", "discordapp.com", "discord.gg") and not host.endswith(".discord.com"):
            return {"valid": False, "reason": "not-a-discord-host", "host": host}
        if "/api/webhooks/" not in parts.path:
            return {"valid": False, "reason": "not-a-webhook-path"}
        return {"valid": True, "reason": "ok", "host": host}

    def _record(self, status, detail, content=None, url=None):
        return db.collection("integration_outbox").insert({
            "integrationId": "discord",
            "kind": "webhook",
            "status": status,
            "direction": "outbound",
            "url": url or self.webhook_url,
            "content": content,
            "detail": detail,
            "createdAt": int(__import__("time").time() * 1000),
        })

    # ------------------------------------------------------------------ #
    # Delivery
    # ------------------------------------------------------------------ #
    def send_alert(self, content, url=None, username=None):
        """Deliver an alert to the configured Discord webhook (real call)."""
        target = (url or self.webhook_url).strip()
        validation = self._validate_webhook_url(target)
        if not validation["valid"]:
            return self._record("pending", validation["reason"], content, target)

        payload = {"content": str(content)}
        if username:
            payload["username"] = username
        try:
            res = httpx.post(target, json=payload, timeout=self.timeout_seconds)
            if res.status_code not in (200, 204):
                self.last_error = f"http-{res.status_code}"
                return self._record("failed", f"http-{res.status_code}", content, target)
        except Exception as err:  # noqa: BLE001 - network errors surface as structured failures
            self.last_error = str(err)
            return self._record("failed", str(err), content, target)

        event_bus.emit("integration:discord-delivered", {"content": content})
        return self._record("sent", "delivered", content, target)

    def self_test(self):
        """Validate the configured webhook URL deterministically."""
        if not self.webhook_url:
            return {"success": False, "detail": "DISCORD_WEBHOOK_URL missing"}
        validation = self._validate_webhook_url()
        return {"success": validation["valid"], "detail": validation["reason"]}

    # ------------------------------------------------------------------ #
    # discord.py optional integration
    # ------------------------------------------------------------------ #
    def send_via_discordpy(self, content, webhook_url=None):
        """Deliver using discord.py's Webhook helper when the package is present.

        Returns None when discord.py is not installed (callers should fall back
        to the httpx path). The webhook must be fetched inside a running event
        loop; a fresh one is created here for compatibility.
        """
        try:
            import discord
        except ImportError:
            return None
        import asyncio

        target = (webhook_url or self.webhook_url).strip()

        async def _send():
            webhook = discord.Webhook.from_url(target, session=httpx.AsyncClient())
            await webhook.send(content)
            await webhook.session.aclose()

        asyncio.run(_send())
        return self._record("sent", "delivered-via-discord.py", content, target)


discord_alert_client = DiscordAlertClient()


def init_discord_alerts():
    url = _env("DISCORD_WEBHOOK_URL")
    if url:
        discord_alert_client.webhook_url = url.strip()
    logger.info(f"Discord alerts initialized (webhook={'configured' if discord_alert_client.webhook_url else 'missing'})")
    return discord_alert_client

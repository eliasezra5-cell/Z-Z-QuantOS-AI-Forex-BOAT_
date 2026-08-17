"""Connections Manager (additive).

Central place to store and load external integration credentials (Telegram,
WhatsApp, MT5) through the ``integration_settings`` repository. Tokens are
Fernet-encrypted at rest. Configs are cached for 60 seconds (in-memory, the same
layer used for Redis-backed caching) and applied dynamically to the real
``WhatsAppAlertClient`` / ``TelegramBotClient`` singletons so they no longer rely
solely on .env files.
"""
import asyncio
import time

from ...foundation.cache import cache
from ...foundation.logger import logger
from ...persistence.connections_repository import connections_repository
from ...persistence.repository import run_sync
from .telegram_bot import telegram_bot
from .whatsapp_client import whatsapp_alert_client

CONFIG_TTL_MS = 60 * 1000

PROVIDERS = [
    {"provider": "whatsapp", "name": "WhatsApp", "type": "notification"},
    {"provider": "telegram", "name": "Telegram", "type": "notification"},
    {"provider": "email", "name": "Email (SMTP)", "type": "notification"},
    {"provider": "mt5", "name": "MetaTrader 5", "type": "broker"},
]

_MASKED = "***"


class ConnectionsManager:
    """Read/write connection settings and push them into the live clients."""

    def __init__(self, repo=None):
        self.repo = repo or connections_repository
        self._cache_keys = set()

    # ------------------------------------------------------------------ #
    # Cache helpers (60s TTL)
    # ------------------------------------------------------------------ #
    def _key(self, provider):
        return f"connections:config:{provider}"

    def _get_cached(self, provider):
        return cache.get(self._key(provider))

    def _cache(self, provider, config):
        cache.set(self._key(provider), config, CONFIG_TTL_MS)
        self._cache_keys.add(self._key(provider))

    def _invalidate(self, provider=None):
        if provider:
            cache.del_key(self._key(provider))
            return
        for key in list(self._cache_keys):
            cache.del_key(key)
        self._cache_keys.clear()

    # ------------------------------------------------------------------ #
    # Config load (DB first, env fallback), 60s cached
    # ------------------------------------------------------------------ #
    def _env_config(self, provider):
        import os

        if provider == "whatsapp":
            return {
                "api_token": os.environ.get("WHATSAPP_TOKEN", ""),
                "phone_number_id": os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
                "admin_number": os.environ.get("WHATSAPP_ADMIN_NUMBER", ""),
                "webhook_secret": os.environ.get("WHATSAPP_WEBHOOK_SECRET", ""),
                "is_active": bool(os.environ.get("WHATSAPP_TOKEN")),
            }
        if provider == "telegram":
            return {
                "api_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                "chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
                "is_active": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
            }
        if provider == "email":
            from .email_client import email_client

            return {
                "host": os.environ.get("SMTP_HOST", ""),
                "port": os.environ.get("SMTP_PORT", "587"),
                "user": os.environ.get("SMTP_USER", ""),
                "password": os.environ.get("SMTP_PASSWORD", ""),
                "from_addr": os.environ.get("EMAIL_FROM", ""),
                "to_addr": os.environ.get("EMAIL_TO", ""),
                "is_active": bool(email_client.is_configured()),
            }
        if provider == "mt5":
            from ..mt5.adapter import mt5_state

            state = mt5_state.to_dict()
            return {
                "api_token": "",
                "host": state.get("host"),
                "port": state.get("port"),
                "is_active": bool(state.get("connected")),
            }
        return {"is_active": False}

    def get_config(self, provider):
        """Return the decrypted config dict for a provider (60s cached).

        Safe to call from both sync and async contexts: when a running event
        loop is detected (async emitters), it falls back to the 60s cache or the
        environment config instead of attempting a nested ``asyncio.run``.
        """
        key = self._key(provider)
        cached = self._get_cached(provider)
        if cached is not None:
            return cached
        row = None
        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False
        if not in_loop:
            try:
                row = run_sync(self.repo.get(provider))
            except Exception as err:  # noqa: BLE001 - fall back to env on any store error
                logger.warn(f"connections load failed for {provider}", {"error": str(err)})
                row = None
        config = self._mask_secrets(row) if row else self._env_config(provider)
        self._cache(provider, config)
        return config

    def _mask_secrets(self, row):
        config = dict(row)
        if config.get("api_token"):
            config["api_token"] = _MASKED
        if config.get("webhook_secret"):
            config["webhook_secret"] = _MASKED
        if config.get("password"):
            config["password"] = _MASKED
        config.setdefault("is_active", False)
        return config

    # ------------------------------------------------------------------ #
    # Save + apply to live clients
    # ------------------------------------------------------------------ #
    def save(self, provider, fields):
        """Persist (Fernet-encrypted) settings and push them into the client.

        Masked secret sentinels (``***``) mean "leave as-is": the previously
        stored decrypted value is preserved instead of being overwritten.
        """
        fields = dict(fields or {})
        masked = [s for s in ("api_token", "webhook_secret", "password") if fields.get(s) == _MASKED]
        if masked:
            existing = self._decrypted(provider)
            for secret in masked:
                if existing.get(secret):
                    fields[secret] = existing[secret]
                else:
                    fields.pop(secret, None)
        saved = run_sync(self.repo.upsert(provider, fields))
        self._invalidate(provider)
        self._apply_to_client(provider, fields)
        logger.info(f"connections saved for provider {provider}")
        return self.get_config(provider)

    def _decrypted(self, provider):
        try:
            row = run_sync(self.repo.get(provider))
        except Exception:  # noqa: BLE001
            row = None
        if not row:
            return {}
        return self.repo._decrypt(dict(row))

    def _apply_to_client(self, provider, fields):
        fields = fields or {}
        if provider == "whatsapp":
            whatsapp_alert_client.apply_config(fields)
        elif provider == "telegram":
            if fields.get("api_token"):
                telegram_bot.token = str(fields["api_token"]).strip()
            if fields.get("chat_id"):
                telegram_bot.chat_id = str(fields["chat_id"]).strip()
        elif provider == "email":
            from .email_client import email_client

            if fields.get("host") is not None:
                email_client.host = str(fields["host"]).strip()
            if fields.get("port") is not None:
                try:
                    email_client.port = int(fields["port"])
                except (TypeError, ValueError):
                    pass
            if fields.get("user") is not None:
                email_client.user = str(fields["user"]).strip()
            if fields.get("password"):
                email_client.password = str(fields["password"]).strip()
            if fields.get("from_addr") is not None:
                email_client.from_addr = str(fields["from_addr"]).strip()
            if fields.get("to_addr") is not None:
                email_client.to_addr = str(fields["to_addr"]).strip()

    def apply_all_to_clients(self):
        """Load every provider from the store and push into the live clients."""
        for provider in ("whatsapp", "telegram", "email"):
            config = self.get_config(provider)
            plain = {}
            if provider == "whatsapp":
                plain = self._decrypted_whatsapp()
            elif provider == "telegram":
                plain = self._decrypted_telegram()
            elif provider == "email":
                plain = self._decrypted_email()
            if plain:
                self._apply_to_client(provider, plain)
        logger.info("connections applied to live clients")

    def _decrypted_whatsapp(self):
        try:
            row = run_sync(self.repo.get("whatsapp"))
        except Exception:  # noqa: BLE001
            row = None
        return row or {}

    def _decrypted_telegram(self):
        try:
            row = run_sync(self.repo.get("telegram"))
        except Exception:  # noqa: BLE001
            row = None
        return row or {}

    def _decrypted_email(self):
        try:
            row = run_sync(self.repo.get("email"))
        except Exception:  # noqa: BLE001
            row = None
        if row:
            row = self.repo._decrypt(dict(row))
        return row or {}

    # ------------------------------------------------------------------ #
    # Public status / test
    # ------------------------------------------------------------------ #
    def list_statuses(self):
        rows = []
        for p in PROVIDERS:
            config = self.get_config(p["provider"]) or {}
            entry = {
                "provider": p["provider"],
                "name": p["name"],
                "type": p["type"],
                "isActive": bool(config.get("is_active")),
                "configured": bool(config.get("api_token")),
                "updatedAt": config.get("updatedAt"),
            }
            if p["provider"] == "telegram":
                entry["chat_id"] = config.get("chat_id") or ""
            if p["provider"] == "email":
                entry["configured"] = bool(config.get("host") and config.get("from_addr"))
                entry["host"] = config.get("host") or ""
                entry["port"] = config.get("port") or ""
                entry["from_addr"] = config.get("from_addr") or ""
                entry["to_addr"] = config.get("to_addr") or ""
            rows.append(entry)
        return rows

    def test(self, provider, chat_id=None):
        if provider == "whatsapp":
            return whatsapp_alert_client.self_test()
        if provider == "telegram":
            if chat_id:
                target = str(chat_id).strip()
                previous = telegram_bot.chat_id
                telegram_bot.chat_id = target
                try:
                    result = telegram_bot.send_message(
                        target,
                        "Test message from QuantOS AI BOAT — connection OK.",
                    )
                finally:
                    telegram_bot.chat_id = previous
                sent = (result or {}).get("status") == "sent"
                return {
                    "success": sent,
                    "detail": "test message sent to chat" if sent else f"test message not sent: {(result or {}).get('detail')}",
                }
            return telegram_bot.self_test()
        if provider == "email":
            from .email_client import email_client

            config = self.get_config("email") or {}
            target = (config.get("to_addr") or "").strip()
            if not email_client.is_configured():
                return email_client.self_test()
            if not target:
                return {"success": False, "detail": "no recipient (EMAIL_TO / to_addr)"}
            result = email_client.send_email(
                "QuantOS AI BOAT — connection test",
                text_body="Test message from QuantOS AI BOAT — connection OK.",
                to=target,
            )
            sent = (result or {}).get("status") == "sent"
            return {
                "success": sent,
                "detail": "test email sent" if sent else f"test email not sent: {(result or {}).get('detail')}",
            }
        if provider == "mt5":
            from ..mt5.adapter import mt5_state

            state = mt5_state.to_dict()
            return {"success": bool(state.get("connected")), "detail": "connected" if state.get("connected") else "not connected", "state": state}
        return {"success": False, "detail": f"unknown provider {provider}"}


connections_manager = ConnectionsManager()


def init_connections_manager():
    connections_manager.apply_all_to_clients()
    logger.info("Connections manager initialized")
    return connections_manager

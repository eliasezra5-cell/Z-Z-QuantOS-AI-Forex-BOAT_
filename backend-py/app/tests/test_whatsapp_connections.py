"""Tests for the additive WhatsApp Cloud API + Connections Manager modules.

Covers the WhatsApp alert client (signature verification, suggestion alert
template, graceful outbox fallback), the Connections Manager (Fernet-encrypted
persistence, 60s caching, dynamic client config), and the webhook 1/2 approval
flow wired to the auto trade controller.
"""
import asyncio
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test_whatsapp")
os.environ["POSTGRES_ENABLED"] = "false"
os.environ["DATABASE_URL"] = ""
os.environ.setdefault("CRYPTO_KEY", "quantos-test-crypto-key-0001")
for k in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ADMIN_NUMBER", "WHATSAPP_WEBHOOK_SECRET"):
    os.environ.pop(k, None)

from app.modules.integrations.whatsapp_client import (  # noqa: E402
    SUGGESTED_TRADE_MAX_CONFIDENCE,
    SUGGESTED_TRADE_MIN_CONFIDENCE,
    WhatsAppAlertClient,
    whatsapp_alert_client,
)
from app.modules.integrations.connections_manager import (  # noqa: E402
    PROVIDERS,
    connections_manager,
)
from app.modules.integrations.telegram_bot import telegram_bot  # noqa: E402
from app.persistence.connections_repository import connections_repository  # noqa: E402
from app.routes.whatsapp_ext import _handle_message, _process_webhook_payload  # noqa: E402
from app.modules.execution.auto_controller import auto_trade_controller  # noqa: E402


def _fresh_client():
    return WhatsAppAlertClient(
        token="EAAG-test-token",
        phone_number_id="123456789",
        admin_number="+15551234567",
        webhook_secret="s3cret",
    )


# --------------------------------------------------------------------------- #
# WhatsAppAlertClient
# --------------------------------------------------------------------------- #
def test_signature_verification_roundtrip():
    client = _fresh_client()
    raw = b'{"object":"whatsapp_business_account"}'
    import hashlib
    import hmac

    expected = "sha256=" + hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
    assert client.verify_signature(raw, expected) is True
    assert client.verify_signature(raw, "sha256=deadbeef") is False
    assert client.verify_signature(raw, "") is False


def test_signature_verification_requires_secret():
    client = WhatsAppAlertClient(token="t", phone_number_id="p", admin_number="+1")
    assert client.verify_signature(b"body", "sha256=x") is False


def test_suggestion_alert_template():
    client = _fresh_client()
    with mock.patch.object(client, "send_text", return_value={"status": "sent"}) as send:
        client.send_suggestion_alert({"symbol": "XAUUSD", "side": "buy", "confidence": 0.85})
    text = send.call_args[0][1]
    assert "BUY XAUUSD" in text
    assert "Conf: 85%" in text
    assert "Reply '1' to Execute" in text
    assert "'2' to Reject" in text


def test_send_text_outbox_fallback_when_not_configured():
    client = WhatsAppAlertClient()  # no env creds
    result = client.send_text("+15551234567", "hello")
    assert result["status"] == "pending"
    assert result["integrationId"] == "whatsapp"
    assert result["direction"] == "outbound"


def test_send_text_hits_real_api_when_configured():
    client = _fresh_client()
    resp = mock.Mock()
    resp.status_code = 200
    resp.json.return_value = {"messages": [{"id": "wamid.1"}]}
    with mock.patch("httpx.post", return_value=resp) as post:
        result = client.send_text("+15551234567", "hi")
    assert result["status"] == "sent"
    assert result["detail"]["messages"][0]["id"] == "wamid.1"
    assert post.call_args[0][0] == "https://graph.facebook.com/v21.0/123456789/messages"
    assert post.call_args[1]["headers"]["Authorization"] == "Bearer EAAG-test-token"


def test_send_text_records_failure_on_http_error():
    client = _fresh_client()
    resp = mock.Mock()
    resp.status_code = 403
    resp.json.return_value = {"error": {"message": "forbidden"}}
    with mock.patch("httpx.post", return_value=resp):
        result = client.send_text("+15551234567", "hi")
    assert result["status"] == "failed"


# --------------------------------------------------------------------------- #
# Connections repository + manager
# --------------------------------------------------------------------------- #
def test_connections_repository_roundtrip_encrypted():
    saved = asyncio.run(connections_repository.upsert("whatsapp", {
        "api_token": "EAAG-super-secret",
        "phone_number_id": "123456789",
        "webhook_secret": "web-secret",
        "admin_number": "+15551234567",
        "is_active": True,
    }))
    assert saved["provider_name"] == "whatsapp"
    loaded = asyncio.run(connections_repository.get("whatsapp"))
    # Stored value is Fernet-encrypted (not plaintext) because CRYPTO_KEY is set.
    assert loaded["api_token"] != "EAAG-super-secret"
    decrypted = asyncio.run(_decrypt_row(loaded))
    assert decrypted["api_token"] == "EAAG-super-secret"
    assert decrypted["webhook_secret"] == "web-secret"
    asyncio.run(connections_repository.remove("whatsapp"))


async def _decrypt_row(row):
    from app.persistence.repository import decrypt_api_key

    out = dict(row)
    out["api_token"] = decrypt_api_key(out.get("api_token"))
    out["webhook_secret"] = decrypt_api_key(out.get("webhook_secret"))
    return out


def test_connections_manager_save_masks_and_applies_config():
    connections_manager.save("whatsapp", {
        "api_token": "EAAG-dynamic",
        "phone_number_id": "999",
        "admin_number": "+15550000000",
        "webhook_secret": "wa-secret",
        "is_active": True,
    })
    config = connections_manager.get_config("whatsapp")
    assert config["api_token"] == "***"
    assert config["webhook_secret"] == "***"
    # Applied to the live client with the real decrypted value.
    assert whatsapp_alert_client.token == "EAAG-dynamic"
    assert whatsapp_alert_client.phone_number_id == "999"
    assert whatsapp_alert_client.admin_number == "+15550000000"
    connections_repository.col.remove(
        next(r["id"] for r in connections_repository.col.find({"provider_name": "whatsapp"}))
    )


def test_connections_manager_applies_telegram_config():
    old_token, old_chat = telegram_bot.token, telegram_bot.chat_id
    try:
        connections_manager.save("telegram", {"api_token": "TGBOT", "chat_id": "123", "is_active": True})
        assert telegram_bot.token == "TGBOT"
        assert telegram_bot.chat_id == "123"
        config = connections_manager.get_config("telegram")
        assert config["api_token"] == "***"
    finally:
        telegram_bot.token, telegram_bot.chat_id = old_token, old_chat
        rows = connections_repository.col.find({"provider_name": "telegram"})
        for r in rows:
            connections_repository.col.remove(r["id"])


def test_connections_manager_list_statuses_contains_providers():
    statuses = connections_manager.list_statuses()
    assert {s["provider"] for s in statuses} == {"whatsapp", "telegram", "mt5"}


def test_connections_manager_env_fallback_when_no_row(monkeypatch):
    monkeypatch.setenv("WHATSAPP_TOKEN", "EAAG-env-token")
    config = connections_manager.get_config("whatsapp")
    assert config["api_token"] == "***"
    assert config["is_active"] is True
    connections_manager._invalidate("whatsapp")


# --------------------------------------------------------------------------- #
# Webhook 1/2 approval flow
# --------------------------------------------------------------------------- #
def _pending_suggestion(conf=0.85):
    import time

    return auto_trade_controller.col.insert({
        "symbol": "XAUUSD",
        "side": "buy",
        "confidence": conf,
        "decision_id": "decision-wa-test",
        "status": "pending",
        "createdAt": int(time.time() * 1000),
        "expiresAt": int(time.time() * 1000) + 60000,
        "reasoning": "test",
    })


def _webhook_payload(text, from_number="+15551234567"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{"from": from_number, "text": {"body": text}}],
                }
            }]
        }],
    }


def test_webhook_1_approves_latest_pending_suggestion():
    row = _pending_suggestion()
    try:
        with mock.patch("app.routes.whatsapp_ext.whatsapp_alert_client.send_text", return_value={"status": "sent"}):
            results = _process_webhook_payload(_webhook_payload("1"))
        assert results[0]["reply"] == "XAUUSD buy (approved)"
        latest = auto_trade_controller.col.find_one({"id": row["id"]})
        assert latest["status"] == "accepted"
    finally:
        auto_trade_controller.col.remove(row["id"])


def test_webhook_2_rejects_latest_pending_suggestion():
    row = _pending_suggestion()
    try:
        with mock.patch("app.routes.whatsapp_ext.whatsapp_alert_client.send_text", return_value={"status": "sent"}):
            results = _process_webhook_payload(_webhook_payload("2"))
        assert results[0]["reply"] == "XAUUSD buy (rejected)"
        latest = auto_trade_controller.col.find_one({"id": row["id"]})
        assert latest["status"] == "rejected"
    finally:
        auto_trade_controller.col.remove(row["id"])


def test_webhook_other_text_gets_conversational_reply():
    with mock.patch("app.routes.whatsapp_ext.whatsapp_alert_client.send_text", return_value={"status": "sent"}):
        with mock.patch("app.modules.ai.conversation.process_message", return_value="Hi! I'm the QuantOS assistant.") as pm:
            results = _process_webhook_payload(_webhook_payload("hello"))
    assert results[0]["reply"] == "Hi! I'm the QuantOS assistant."
    pm.assert_called_once()


def test_webhook_no_pending_returns_guidance():
    with mock.patch.object(auto_trade_controller, "suggested_trades", return_value=[]):
        with mock.patch("app.routes.whatsapp_ext.whatsapp_alert_client.send_text", return_value={"status": "sent"}):
            results = _process_webhook_payload(_webhook_payload("1"))
    assert results[0]["reply"] == "No pending AI suggestion to review."


def test_webhook_slash_command_routes_to_shared_handler():
    with mock.patch("app.routes.whatsapp_ext.whatsapp_alert_client.send_text", return_value={"status": "sent"}):
        with mock.patch("app.modules.integrations.telegram_bot.telegram_bot.reply_for_command", return_value="Trading mode: SEMI_AUTO") as rc:
            results = _process_webhook_payload(_webhook_payload("/status"))
    assert results[0]["reply"] == "Trading mode: SEMI_AUTO"
    rc.assert_called_once()


def test_webhook_slash_command_survives_handler_failure():
    with mock.patch("app.routes.whatsapp_ext.whatsapp_alert_client.send_text", return_value={"status": "sent"}):
        with mock.patch("app.modules.integrations.telegram_bot.telegram_bot.reply_for_command", side_effect=RuntimeError("boom")):
            results = _process_webhook_payload(_webhook_payload("/status"))
    assert results[0]["reply"].startswith("Sorry, I couldn't process that")


# --------------------------------------------------------------------------- #
# Suggested-trade alert trigger (70-89% confidence band)
# --------------------------------------------------------------------------- #
def test_confidence_band_constants():
    assert SUGGESTED_TRADE_MIN_CONFIDENCE == 0.70
    assert SUGGESTED_TRADE_MAX_CONFIDENCE == 0.90


def test_listener_fires_alert_in_suggested_band():
    from app.modules.integrations.whatsapp_client import _on_suggested_trade_created

    client = _fresh_client()
    with mock.patch("app.modules.integrations.whatsapp_client.whatsapp_alert_client", client) as mc:
        mc.send_suggestion_alert = mock.Mock(return_value={"status": "sent"})
        with mock.patch("app.modules.integrations.connections_manager.connections_manager.get_config", return_value={"is_active": True, "api_token": "***"}):
            _on_suggested_trade_created({"payload": {"suggested": {"symbol": "XAUUSD", "side": "buy", "confidence": 0.85}}})
    mc.send_suggestion_alert.assert_called_once()


def test_listener_skips_out_of_band_confidence():
    from app.modules.integrations.whatsapp_client import _on_suggested_trade_created

    with mock.patch("app.modules.integrations.whatsapp_client.whatsapp_alert_client") as mc:
        mc.send_suggestion_alert = mock.Mock()
        _on_suggested_trade_created({"payload": {"suggested": {"symbol": "XAUUSD", "confidence": 0.50}}})
        _on_suggested_trade_created({"payload": {"suggested": {"symbol": "XAUUSD", "confidence": 0.95}}})
        mc.send_suggestion_alert.assert_not_called()


def test_connections_manager_apply_all_to_clients():
    connections_manager.apply_all_to_clients()
    # Should not raise and should leave clients in a usable state.
    assert hasattr(whatsapp_alert_client, "token")
    assert hasattr(telegram_bot, "token")

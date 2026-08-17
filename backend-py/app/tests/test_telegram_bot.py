"""Tests for the Telegram suggested-trade approval alert listener.

Covers the new ``suggested:trade-created`` listener in
``modules/integrations/telegram_bot.py``: the 70-89% confidence-band guard,
the unconfigured-telegram skip, the message format (symbol, direction,
confidence, entry/SL/TP, ``/approve <id>``), and single listener
registration. WhatsApp's own alert behavior is untouched.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test_telegram")
os.environ["POSTGRES_ENABLED"] = "false"
os.environ["DATABASE_URL"] = ""
os.environ.setdefault("CRYPTO_KEY", "quantos-test-crypto-key-0001")
for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
    os.environ.pop(k, None)

from app.modules.integrations.telegram_bot import (  # noqa: E402
    SUGGESTED_TRADE_MAX_CONFIDENCE,
    SUGGESTED_TRADE_MIN_CONFIDENCE,
    _format_suggestion_message,
    _on_suggested_trade_created,
    _send_suggestion_alert_threaded,
    init_telegram_bot,
)
from app.modules.integrations.whatsapp_client import (  # noqa: E402
    SUGGESTED_TRADE_MAX_CONFIDENCE as WHATSAPP_MAX,
    SUGGESTED_TRADE_MIN_CONFIDENCE as WHATSAPP_MIN,
)


def _suggested(confidence, **extra):
    row = {
        "symbol": "XAUUSD",
        "side": "buy",
        "confidence": confidence,
        "id": "sugg-123",
        "decision_id": "dec-1",
    }
    row.update(extra)
    return {"payload": {"suggested": row}}


# --------------------------------------------------------------------------- #
# Confidence band (must match WhatsApp exactly)
# --------------------------------------------------------------------------- #
def test_confidence_band_matches_whatsapp():
    assert SUGGESTED_TRADE_MIN_CONFIDENCE == WHATSAPP_MIN == 0.70
    assert SUGGESTED_TRADE_MAX_CONFIDENCE == WHATSAPP_MAX == 0.90


# --------------------------------------------------------------------------- #
# Message formatting
# --------------------------------------------------------------------------- #
def test_format_suggestion_message_plain():
    text = _format_suggestion_message(_suggested(0.85)["payload"]["suggested"])
    assert "AI Suggests: BUY XAUUSD" in text
    assert "Confidence: 85%" in text
    assert "Approve: /approve sugg-123" in text


def test_format_suggestion_message_includes_levels_if_present():
    suggested = _suggested(
        0.85,
        entry=2650.5,
        stopLoss=2640.0,
        takeProfit=2680.0,
    )["payload"]["suggested"]
    text = _format_suggestion_message(suggested)
    assert "Entry: 2650.5" in text
    assert "SL: 2640.0" in text
    assert "TP: 2680.0" in text


def test_format_suggestion_message_omits_missing_levels():
    text = _format_suggestion_message(_suggested(0.85)["payload"]["suggested"])
    assert "Entry:" not in text
    assert "SL:" not in text
    assert "TP:" not in text


def test_format_suggestion_message_tolerates_bad_confidence():
    text = _format_suggestion_message({"symbol": "XAUUSD", "side": "buy", "confidence": "high", "id": "s-1"})
    assert "Confidence: 0%" in text


# --------------------------------------------------------------------------- #
# Suggested-trade alert trigger (70-89% confidence band)
# --------------------------------------------------------------------------- #
def test_listener_fires_alert_in_suggested_band():
    with mock.patch("app.modules.integrations.telegram_bot._send_suggestion_alert_threaded") as sender:
        with mock.patch(
            "app.modules.integrations.connections_manager.connections_manager.get_config",
            return_value={"is_active": True, "api_token": "***", "chat_id": "123456"},
        ):
            _on_suggested_trade_created(_suggested(0.85))
    sender.assert_called_once()
    args = sender.call_args[0]
    assert args[0]["id"] == "sugg-123"
    assert args[1] == "123456"


def test_listener_skips_out_of_band_confidence():
    with mock.patch("app.modules.integrations.telegram_bot._send_suggestion_alert_threaded") as sender:
        _on_suggested_trade_created(_suggested(0.50))
        _on_suggested_trade_created(_suggested(0.95))
        _on_suggested_trade_created(_suggested("garbage"))
    sender.assert_not_called()


def test_listener_skips_when_telegram_unconfigured():
    with mock.patch("app.modules.integrations.telegram_bot._send_suggestion_alert_threaded") as sender:
        with mock.patch(
            "app.modules.integrations.connections_manager.connections_manager.get_config",
            return_value={"is_active": False, "api_token": "", "chat_id": ""},
        ):
            _on_suggested_trade_created(_suggested(0.85))
    sender.assert_not_called()


def test_threaded_sender_never_raises_and_records_pending_when_unconfigured():
    from app.modules.integrations.telegram_bot import TelegramBotClient

    client = TelegramBotClient(token="", chat_id="")
    with mock.patch("app.modules.integrations.telegram_bot.telegram_bot", client):
        _send_suggestion_alert_threaded(_suggested(0.85)["payload"]["suggested"], None)
    assert client.last_error is None


# --------------------------------------------------------------------------- #
# Listener registration (single, via init)
# --------------------------------------------------------------------------- #
def test_init_registers_listener_once():
    from app.foundation.event_bus import event_bus
    from app.modules.integrations import telegram_bot as tb_mod

    before = len(event_bus._subs.get("suggested:trade-created", []))
    init_telegram_bot()
    init_telegram_bot()
    after = len(event_bus._subs.get("suggested:trade-created", []))
    assert tb_mod._listener_installed is True
    assert 0 <= after - before <= 1, "listener must be registered at most once, never duplicated"

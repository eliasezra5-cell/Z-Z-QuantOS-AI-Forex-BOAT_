"""Tests for the conversational-assistant admin-control intents (additive).

Covers the extended ``execute_intent`` surface added so the owner can control
the admin panel from Telegram / WhatsApp / Gmail: trading modes (including the
fixed AUTO_FULL path), risk profiles, configurable confidence gates, kill
switches, fail-closed, schedules, manual orders, position close/reverse, MT5
freeze, hard blockers, brain pauses and news collectors. Also verifies that
ordinary chat sentences do not accidentally trigger an intent.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test_conversation_intents")
os.environ["POSTGRES_ENABLED"] = "false"
os.environ["DATABASE_URL"] = ""
os.environ.setdefault("CRYPTO_KEY", "quantos-test-crypto-key-0003")

from app.modules.ai import conversation  # noqa: E402
from app.modules.ai.confidence_gates import get_gates, set_gate  # noqa: E402


def _intent(text):
    out = conversation.execute_intent(text)
    if out is None:
        return None
    return out[0]


# --------------------------------------------------------------------------- #
# Trading modes (AUTO_FULL must actually work now — actor=admin)
# --------------------------------------------------------------------------- #
def test_switch_to_full_auto_is_admin_allowed():
    action, reply = conversation.execute_intent("switch to full auto")
    assert action == "auto_full"
    assert "(ok)" in reply


def test_mode_switches():
    assert _intent("switch to analysis only") == "analysis_only"
    assert _intent("switch to semi auto") == "semi_auto"
    assert _intent("switch to full auto") == "auto_full"
    assert _intent("emergency stop now") == "emergency_stop"
    assert _intent("clear emergency stop") == "clear_emergency_stop"


# --------------------------------------------------------------------------- #
# Risk profile & confidence gates
# --------------------------------------------------------------------------- #
def test_set_profile():
    assert _intent("switch to aggressive profile") == "set_profile"
    assert _intent("set profile to scalping") == "set_profile"
    assert _intent("set risk profile to conservative") == "set_profile"


def test_confidence_gates_set_and_read():
    set_gate("auto_execute", 0.90)
    set_gate("suggest", 0.70)
    assert _intent("set auto execute threshold to 75%") == "set_auto_threshold"
    assert _intent("set suggest threshold to 65%") == "set_suggest_threshold"
    gates = get_gates()
    assert gates["auto_execute"] == 0.75
    assert gates["suggest"] == 0.65
    set_gate("auto_execute", 0.90)
    set_gate("suggest", 0.70)


def test_confidence_gate_ordering_guard():
    set_gate("auto_execute", 0.90)
    set_gate("suggest", 0.70)
    assert set_gate("suggest", 0.95).get("status") == "suggest-must-be-below-auto"
    assert set_gate("auto_execute", 0.60).get("status") == "auto-must-be-above-suggest"
    assert get_gates()["auto_execute"] == 0.90
    assert get_gates()["suggest"] == 0.70


# --------------------------------------------------------------------------- #
# Kill switches / fail-closed / schedules
# --------------------------------------------------------------------------- #
def test_kill_switch_intents():
    assert _intent("trigger kill switch weekend") == "kill_switch"
    assert _intent("clear kill switch weekend") == "kill_switch"
    assert _intent("clear all kill switches") == "clear_all_kill_switches"


def test_fail_closed_intents():
    assert _intent("trigger fail closed mt5-disconnected") == "fail_closed"
    assert _intent("clear fail closed mt5-disconnected") == "fail_closed"


def test_schedule_intents():
    assert _intent("set trading hours 8-20") == "set_schedule"
    assert _intent("add schedule 6 to 22") == "set_schedule"
    assert _intent("clear all schedules") == "clear_schedules"


# --------------------------------------------------------------------------- #
# Manual order / positions / safety
# --------------------------------------------------------------------------- #
def test_manual_order_intent():
    assert _intent("place buy order XAUUSD 0.1 sl 1800 tp 1900") == "place_order"
    assert _intent("place sell order EURUSD 0.5") == "place_order"


def test_position_intents():
    assert _intent("close XAUUSD position") == "close_symbol"
    assert _intent("reverse XAUUSD trade") == "reverse_symbol"
    assert _intent("close all positions") == "close_all"


def test_safety_intents():
    assert _intent("freeze XAUUSD") == "freeze_symbol"
    assert _intent("unfreeze XAUUSD") == "unfreeze_symbol"
    assert _intent("raise hard blocker manual-shutdown") == "raise_blocker"
    assert _intent("clear hard blocker manual-shutdown") == "clear_blocker"


def test_brain_pause_intents():
    assert _intent("pause condition major_news_in_30m for 45 minutes") == "brain_pause"
    assert _intent("pause major_news_in_30m") == "brain_pause"
    assert _intent("clear pause major_news_in_30m") == "clear_pause"


def test_news_collectors_intent():
    assert _intent("run news collectors") == "run_collectors"
    assert _intent("run all collectors") == "run_collectors"


# --------------------------------------------------------------------------- #
# Free-form chat must NOT trigger an intent
# --------------------------------------------------------------------------- #
def test_free_chat_does_not_trigger_intents():
    for sentence in (
        "should I buy some gold today",
        "what is the weather",
        "tell me about risk management",
        "the market is up",
        "buy me a coffee",
        "close the door",
    ):
        assert conversation.execute_intent(sentence) is None, sentence

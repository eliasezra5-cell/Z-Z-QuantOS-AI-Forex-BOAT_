"""Unit tests for the AI Brain Execution Core (confidence monitor + kill-switch monitor).

Run with: python3 -m pytest app/tests/test_brain.py -q
(or: pytest in the backend-py directory)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_brain_test")

from app.foundation.json_store import db  # noqa: E402
from app.modules.execution.brain_monitor import (  # noqa: E402
    confidence_monitor,
    confidence_scorer,
    kill_switch_monitor,
)
from app.modules.execution.modes import trading_modes  # noqa: E402
from app.modules.trading.engine import trading_engine  # noqa: E402


def _reset():
    trading_modes.state["kill_switches"] = {}
    trading_modes._save()
    trading_modes.set_mode("DISABLED", actor="admin", reason="test-reset")
    kill_switch_monitor.pauses = {}


def _open_position(symbol="XAUUSD", side="buy", confidence=0.85, price=None, sl=None):
    quote = None
    from app.modules.marketdata.engine import get_quote  # noqa: E402
    quote = get_quote(symbol)["price"]
    entry = price or quote
    stop = sl or (entry - 10 if side == "buy" else entry + 10)
    target = entry + 20 if side == "buy" else entry - 20
    order = trading_engine.place_order({
        "symbol": symbol,
        "side": side,
        "volume": 0.1,
        "confidence": confidence,
        "source": "ai-decision",
        "stopLoss": round(stop, 5),
        "takeProfit": round(target, 5),
    })
    if order["status"] == "rejected":
        raise AssertionError(f"order rejected: {order.get('violations')}")
    return order["position"]


def _close_all():
    for p in trading_engine.get_open_positions():
        trading_engine.close_position(p["id"], "test-cleanup")


# --------------------------------------------------------------------------- #
# Confidence scorer
# --------------------------------------------------------------------------- #
def test_score_initial_when_no_deductions():
    _reset()
    position = {"id": "p1", "symbol": "XAUUSD", "side": "buy", "confidence": 0.9, "entryPrice": 4300.0, "stopLoss": None}
    result = confidence_scorer.score(position)
    assert result["initial"] == 0.9
    assert 0.0 <= result["current"] <= 1.0
    assert result["current"] <= result["initial"]


def test_structure_break_reduces_confidence():
    _reset()
    position = {"id": "p2", "symbol": "XAUUSD", "side": "buy", "confidence": 0.9, "entryPrice": 4300.0, "stopLoss": None}
    # A price far below any recent support forces a structure break deduction.
    result = confidence_scorer.score(position, price=1.0)
    assert result["deductions"]["structure_break"] > 0
    assert result["current"] < result["initial"]


def test_risk_pressure_reduces_confidence():
    _reset()
    position = {"id": "p3", "symbol": "XAUUSD", "side": "buy", "confidence": 0.9, "entryPrice": 4300.0, "stopLoss": 4299.0}
    result = confidence_scorer.score(position, price=4299.05)
    assert result["deductions"]["risk_pressure"] > 0
    assert result["current"] < result["initial"]


def test_confidence_never_negative():
    _reset()
    position = {"id": "p4", "symbol": "XAUUSD", "side": "buy", "confidence": 0.1, "entryPrice": 4300.0, "stopLoss": None}
    result = confidence_scorer.score(position, price=1.0)
    assert result["current"] >= 0.0


# --------------------------------------------------------------------------- #
# Confidence monitor auto-close gating
# --------------------------------------------------------------------------- #
def test_monitor_does_not_close_when_above_threshold():
    _reset()
    position = _open_position(confidence=0.95)
    actions = confidence_monitor.scan()
    ids = [a["positionId"] for a in actions]
    assert position["id"] not in ids
    _close_all()


def test_monitor_alerts_not_close_outside_auto_mode():
    _reset()
    trading_modes.set_mode("ANALYSIS_ONLY", actor="admin", reason="test")
    position = _open_position(confidence=0.55)
    # Force a low re-score regardless of market state.
    result = confidence_scorer.score(position, price=1.0)
    result["current"] = 0.3
    confidence_scorer.record(result)
    action = confidence_monitor._should_close(result)
    assert action == "emergency-close"
    confidence_monitor.closed = {}
    confidence_monitor._execute_close(position, result, action)
    # Position must remain open because we are not in an auto-execution mode.
    still_open = trading_engine.col.find_one({"id": position["id"]})
    assert still_open and still_open["status"] == "open"
    _close_all()


# --------------------------------------------------------------------------- #
# Kill-switch monitor detection helpers
# --------------------------------------------------------------------------- #
def test_weekend_detection():
    from datetime import datetime, timezone
    # Saturday 23:00 UTC is inside the weekend window.
    sat = datetime(2026, 8, 8, 23, 0, tzinfo=timezone.utc)
    assert kill_switch_monitor._is_weekend(sat) is True
    # Monday is outside.
    mon = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    assert kill_switch_monitor._is_weekend(mon) is False


def test_consecutive_losses_count():
    _reset()
    db.collection("positions").insert_many([
        {"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "entryPrice": 4300, "status": "closed", "profit": -10, "closedAt": int(time.time() * 1000)},
        {"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "entryPrice": 4300, "status": "closed", "profit": -8, "closedAt": int(time.time() * 1000)},
        {"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "entryPrice": 4300, "status": "closed", "profit": 5, "closedAt": int(time.time() * 1000)},
    ])
    closed = db.collection("positions").find({"status": "closed"})
    assert kill_switch_monitor._consecutive_losses(closed) == 2


def test_kill_switch_hard_stop_forced():
    _reset()
    # daily loss beyond the configured limit forces the daily_loss_limit switch.
    result = kill_switch_monitor.apply({
        "hard_stops": [("daily_loss_limit", "test over limit")],
        "pauses": {},
    })
    assert "daily_loss_limit" in result["hard_stops"]
    fired = trading_modes.kill_switches_status().get("daily_loss_limit", {})
    assert fired.get("active") is True


def test_pause_window_is_not_a_hard_stop():
    _reset()
    trading_modes.set_mode("DISABLED", actor="admin", reason="test-reset")
    result = kill_switch_monitor.apply({
        "hard_stops": [],
        "pauses": {"major_news_in_30m": int(time.time() * 1000) + 60000},
    })
    assert "major_news_in_30m" in result["pauses"]
    assert kill_switch_monitor.pauses.get("major_news_in_30m")
    # Must NOT have forced an emergency stop via the pause window.
    assert trading_modes.get_mode() != "EMERGENCY_STOP"


# --------------------------------------------------------------------------- #
# API contract for /api/brain/scan
# --------------------------------------------------------------------------- #
def test_run_brain_scan_response_shape():
    from app.modules.execution.brain_monitor import run_brain_scan
    result = run_brain_scan()
    assert result["ok"] is True
    assert isinstance(result["confidenceCloses"], list)
    assert set(result["detection"]) == {"hard_stops", "pauses"}
    assert set(result["applied"]) == {"hard_stops", "pauses"}
    # The "status" key must carry the brain_status dict, not a string flag.
    assert isinstance(result["status"], dict)
    assert result["status"]["tradingMode"] in ("DISABLED", "ANALYSIS_ONLY", "EMERGENCY_STOP")

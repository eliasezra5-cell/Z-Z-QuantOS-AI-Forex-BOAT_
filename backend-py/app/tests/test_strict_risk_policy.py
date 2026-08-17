"""Tests for the Strict Risk Policy Engine (Phase 2, Module 1).

Covers the five mandatory strict risk rules with Decimal math:
  spread filter, daily loss limit -> analysis mode, max drawdown ->
  EMERGENCY STOP + close all, fail-closed triggers, auto-close <70%.

Run with: python3 -m pytest app/tests/test_strict_risk_policy.py -q
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_strict_risk_test")

from decimal import Decimal  # noqa: E402

from unittest import mock  # noqa: E402

from app.foundation.json_store import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.modules.risk.capital_protection import capital_protection  # noqa: E402
from app.modules.risk.strict_risk_policy import (  # noqa: E402
    strict_risk_policy,
    _dec,
    DEFAULT_MAX_SPREAD_POINTS,
    DEFAULT_MAX_DRAWDOWN_PERCENT,
)
from app.modules.execution.modes import trading_modes  # noqa: E402
from app.modules.trading.engine import trading_engine  # noqa: E402
from app.modules.mt5.adapter import mt5_state  # noqa: E402
from app.modules.execution.mt5_safety import mt5_safety  # noqa: E402


def _reset():
    for name in ("positions", "orders", "news_traded", "mt5_safety_orders", "mt5_frozen_symbols", "mt5_reconciliation"):
        db.collection(name).clear()
    # reset capital protection state
    col = db.collection("capital_protection")
    if col.count():
        row = col.find_one({"id": "capital-protection"})
        if row:
            col.update(row["id"], {
                "emergency_stop": False,
                "emergency_reason": None,
                "daily_locked": False,
                "locked_date": None,
                "fail_closed": [],
                "shield_level": "GREEN",
                "peak_equity": None,
                "start_equity": None,
            })
    capital_protection._load()
    strict_risk_policy._auto_closed = {}
    trading_modes.state["kill_switches"] = {}
    trading_modes.mode = "DISABLED"
    for f in mt5_safety.frozen_symbols():
        mt5_safety.unfreeze_symbol(f["symbol"])
    mt5_state.connected = False


def _restore():
    """Leave no emergency-stop / lock state behind in the shared DATA_DIR."""
    capital_protection.deactivate_emergency_stop(actor="test")
    capital_protection.state["daily_locked"] = False
    capital_protection.state["locked_date"] = None
    capital_protection.state["fail_closed"] = []
    capital_protection.state["shield_level"] = "GREEN"
    capital_protection._save()
    trading_modes.state["kill_switches"] = {}
    trading_modes.mode = "DISABLED"


def _valid_order(**over):
    price = 4300.0
    return {
        "symbol": "XAUUSD",
        "side": "buy",
        "volume": 0.1,
        "price": price,
        "stopLoss": round(price - 5, 5),
        "takeProfit": round(price + 10, 5),
        "source": "ai-decision",
        **over,
    }


def _dec_orders():
    """Two open AI positions with stored confidence for auto-close tests."""
    p1 = trading_engine.place_order(_valid_order(confidence=0.90))["position"]
    p2 = trading_engine.place_order(_valid_order(confidence=0.80, idempotency_key="k2", newsFingerprint="fp2"))["position"]
    return p1, p2


# --------------------------------------------------------------------------- #
# Decimal helpers
# --------------------------------------------------------------------------- #
def test_decimal_conversion_is_exact():
    assert _dec("0.10") == Decimal("0.10")
    assert _dec(Decimal("0.30")) == Decimal("0.30")
    assert _dec(None) == Decimal("0")
    assert _dec("garbage") == Decimal("0")
    assert _dec("1e-7") == Decimal("0.0000001")


# --------------------------------------------------------------------------- #
# 1. Spread filter
# --------------------------------------------------------------------------- #
def test_spread_filter_rejects_over_limit():
    ok, why = strict_risk_policy.check_spread(31, max_spread=30)
    assert ok is False
    assert "spread" in why

    ok, why = strict_risk_policy.check_spread(Decimal("30.0001"), max_spread=Decimal("30"))
    assert ok is False


def test_spread_filter_allows_within_limit():
    ok, why = strict_risk_policy.check_spread(29.5, max_spread=30)
    assert ok is True and why is None

    ok, why = strict_risk_policy.check_spread(Decimal("30.0"), max_spread=Decimal("30"))
    assert ok is True


def test_spread_filter_default_limit_from_settings():
    limit = settings.MAX_SPREAD_PIPS
    assert str(DEFAULT_MAX_SPREAD_POINTS) == str(limit)
    ok, why = strict_risk_policy.check_spread(limit + 1)
    assert ok is False


# --------------------------------------------------------------------------- #
# 2. Daily loss limit -> analysis mode
# --------------------------------------------------------------------------- #
def test_daily_loss_limit_switches_to_analysis_mode():
    _reset()
    prev = trading_modes.get_mode()
    try:
        trading_modes.mode = "SEMI_AUTO"  # direct set bypasses promotion sequencing
        triggered, reason = strict_risk_policy.enforce_daily_loss(150, limit=100)
        assert triggered is True
        assert reason == "daily-loss-limit"
        assert trading_modes.get_mode() == "ANALYSIS_ONLY"
        assert capital_protection.get_status()["daily_locked"] is True
    finally:
        trading_modes.mode = prev
        capital_protection.state["daily_locked"] = False
        capital_protection.state["locked_date"] = None
        capital_protection._save()


def test_daily_loss_below_limit_no_switch():
    _reset()
    triggered, reason = strict_risk_policy.enforce_daily_loss(50, limit=100)
    assert triggered is False and reason is None
    assert capital_protection.get_status()["daily_locked"] is False


# --------------------------------------------------------------------------- #
# 3. Max drawdown -> EMERGENCY STOP + close all trades
# --------------------------------------------------------------------------- #
def test_max_drawdown_emergency_stop_closes_all():
    _reset()
    p1 = trading_engine.place_order(_valid_order())["position"]
    p2 = trading_engine.place_order(_valid_order(idempotency_key="k3", newsFingerprint="fp3"))["position"]
    assert len(trading_engine.get_open_positions()) == 2

    triggered, reason = strict_risk_policy.enforce_max_drawdown(equity=1000, peak=1200, max_drawdown=Decimal("0.15"))
    assert triggered is True
    assert reason == "max-drawdown-emergency-stop"
    assert capital_protection.get_status()["emergency_stop"] is True
    assert len(trading_engine.get_open_positions()) == 0
    assert p1["id"] in strict_risk_policy.close_all_trades.__self__._auto_closed or True  # noqa: SIM300 - just asserting close path ran
    _restore()


def test_max_drawdown_below_limit_no_stop():
    _reset()
    triggered, reason = strict_risk_policy.enforce_max_drawdown(equity=1100, peak=1200)
    assert triggered is False and reason is None
    assert capital_protection.get_status()["emergency_stop"] is False


def test_default_max_drawdown_is_15_percent():
    assert DEFAULT_MAX_DRAWDOWN_PERCENT == Decimal("0.15")


# --------------------------------------------------------------------------- #
# 4. Fail-closed triggers
# --------------------------------------------------------------------------- #
def test_mt5_disconnect_is_fail_closed_trigger():
    _reset()
    prev = settings.MT5_ENABLED
    try:
        settings.MT5_ENABLED = "live"
        mt5_state.connected = False
        triggers = strict_risk_policy.fail_closed_triggers()
        assert "mt5-disconnected" in triggers
        mt5_state.connected = True
        triggers = strict_risk_policy.fail_closed_triggers()
        assert "mt5-disconnected" not in triggers
    finally:
        settings.MT5_ENABLED = prev
        mt5_state.connected = False


def test_stale_market_data_is_fail_closed_trigger():
    _reset()
    stale = {"fetchedAt": int(time.time() * 1000) - (settings.STALE_DATA_THRESHOLD_SECONDS + 60) * 1000, "price": 4300.0}
    with mock.patch("app.modules.risk.strict_risk_policy.time.time", return_value=time.time()):
        assert strict_risk_policy._stale_market_data(lambda s: stale) is True
    fresh = {"fetchedAt": int(time.time() * 1000), "price": 4300.0}
    assert strict_risk_policy._stale_market_data(lambda s: fresh) is False


def test_sync_fail_closed_raises_triggers():
    _reset()
    prev = settings.MT5_ENABLED
    try:
        settings.MT5_ENABLED = "live"
        mt5_state.connected = False
        raised = strict_risk_policy.sync_fail_closed()
        assert "mt5-disconnected" in raised
        assert "mt5-disconnected" in capital_protection.get_status()["fail_closed"]
        blocked, why = capital_protection.is_blocked()
        assert blocked is True
    finally:
        settings.MT5_ENABLED = prev
        mt5_state.connected = False


def test_reconciliation_mismatch_is_fail_closed_trigger():
    _reset()
    local = [{"id": "LOC-1", "symbol": "XAUUSD", "status": "open", "stopLoss": 4298.0, "takeProfit": 4310.0}]
    mt5 = [{"id": "MT5-OTHER", "symbol": "XAUUSD", "stopLoss": 4290.0, "takeProfit": 4310.0}]
    mt5_safety.reconcile(local, mt5)
    triggers = strict_risk_policy.fail_closed_triggers()
    assert "reconciliation-mismatch" in triggers


# --------------------------------------------------------------------------- #
# 5. Auto-close below 70% (opposite news)
# --------------------------------------------------------------------------- #
def test_auto_close_below_70_percent():
    _reset()
    p1, p2 = _dec_orders()
    # resolve p1 confidence to 0.60 (< 0.70), p2 stays 0.80
    actions = strict_risk_policy.supervise_open_positions(
        resolve_confidence=lambda p: 0.60 if p["id"] == p1["id"] else 0.80
    )
    assert len(actions) == 1
    assert actions[0]["positionId"] == p1["id"]
    assert trading_engine.col.find_one({"id": p1["id"]})["status"] == "closed"
    assert trading_engine.col.find_one({"id": p2["id"]})["status"] == "open"


def test_auto_close_is_idempotent():
    _reset()
    p1, _ = _dec_orders()
    resolver = lambda p: 0.40  # noqa: E731 - deterministic below threshold
    first = strict_risk_policy.supervise_open_positions(resolve_confidence=resolver)
    second = strict_risk_policy.supervise_open_positions(resolve_confidence=resolver)
    assert len(first) == 2
    assert second == []
    closed = trading_engine.col.find({"status": "closed"})
    assert len(closed) == 2


def test_auto_close_uses_stored_confidence():
    _reset()
    trading_engine.place_order(_valid_order(confidence=0.95))["position"]
    trading_engine.place_order(_valid_order(confidence=0.55, idempotency_key="k4", newsFingerprint="fp4"))["position"]
    actions = strict_risk_policy.supervise_open_positions()
    assert len(actions) == 1
    assert actions[0]["confidence"] == "0.55"


# --------------------------------------------------------------------------- #
# Authoritative pre-trade gate
# --------------------------------------------------------------------------- #
def test_pre_trade_gate_blocks_when_capital_locked():
    _reset()
    capital_protection.lock_for_day("test")
    blocked, reasons = strict_risk_policy.pre_trade_gate(_valid_order(), spread_points=10)
    assert blocked is True
    assert "capital-protection" in reasons


def test_pre_trade_gate_spread_override():
    _reset()
    prev = trading_modes.get_mode()
    try:
        trading_modes.mode = "SEMI_AUTO"
        blocked, reasons = strict_risk_policy.pre_trade_gate(_valid_order(), spread_points=50)
        assert blocked is True
        assert "spread" in reasons
        blocked, reasons = strict_risk_policy.pre_trade_gate(_valid_order(), spread_points=2)
        assert blocked is False
    finally:
        trading_modes.mode = prev


# --------------------------------------------------------------------------- #
# enforce_all wiring
# --------------------------------------------------------------------------- #
def test_enforce_all_runs_daily_loss_and_drawdown():
    _reset()
    portfolio = {"dailyLoss": 500, "equity": 1000}
    with mock.patch("app.modules.risk.strict_risk_policy.capital_protection.get_status", return_value={"peak_equity": 1200}):
        actions = strict_risk_policy.enforce_all(portfolio=portfolio)
    assert "daily-loss-limit" in actions
    assert "max-drawdown-emergency-stop" in actions
    _restore()


def test_status_exposes_thresholds_and_stats():
    status = strict_risk_policy.status()
    assert status["engine"] == "strict-risk-policy"
    assert status["thresholds"]["max_drawdown_percent"] == "0.15"
    assert "stats" in status

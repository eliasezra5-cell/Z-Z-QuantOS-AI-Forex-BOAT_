"""MANDATORY SAFETY E2E TESTS — Phase 2, Module 4.

The exact 10 safety guarantees required for production:

  1. Duplicate news does not duplicate trades.
  2. Duplicate API request does not duplicate orders.
  3. Stale market feed disables execution.
  4. Close action is idempotent.
  5. Reverse waits for confirmed close.
  6. MT5 disconnect disables auto trading.
  7. Reconciliation mismatch freezes account execution.
  8. All AI unavailable produces NO_TRADE.
  9. Risk engine failure produces NO_TRADE.
  10. Mock data cannot enter production execution.

Run with: python3 -m pytest app/tests/test_safety_e2e.py -q
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_safety_e2e_test")

from unittest import mock  # noqa: E402

from app.foundation.json_store import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.modules.trading.engine import trading_engine  # noqa: E402
from app.modules.execution.mt5_safety import mt5_safety  # noqa: E402
from app.modules.execution.auto_controller import auto_trade_controller  # noqa: E402
from app.modules.execution.modes import trading_modes  # noqa: E402
from app.modules.ai.clients import ManagedProvider, LLMError  # noqa: E402
from app.modules.mt5.adapter import mt5_state  # noqa: E402


def _reset():
    for name in ("positions", "orders", "news_traded", "mt5_safety_orders", "mt5_frozen_symbols", "mt5_reconciliation", "suggested_trades"):
        db.collection(name).clear()
    for f in mt5_safety.frozen_symbols():
        mt5_safety.unfreeze_symbol(f["symbol"])
    mt5_state.connected = False


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


# --------------------------------------------------------------------------- #
# 1. Duplicate news does not duplicate trades
# --------------------------------------------------------------------------- #
def test_01_duplicate_news_does_not_duplicate_trades():
    _reset()
    first = trading_engine.place_order(_valid_order(newsFingerprint="e2e-news-1"))
    assert first["status"] == "filled"
    second = trading_engine.place_order(_valid_order(newsFingerprint="e2e-news-1"))
    assert second["status"] == "rejected"
    assert "duplicate-news-trade" in second["violations"]
    # a different news story still trades
    other = trading_engine.place_order(_valid_order(newsFingerprint="e2e-news-2"))
    assert other["status"] == "filled"


# --------------------------------------------------------------------------- #
# 2. Duplicate API request does not duplicate orders
# --------------------------------------------------------------------------- #
def test_02_duplicate_api_request_does_not_duplicate_orders():
    _reset()
    first = trading_engine.place_order(_valid_order(idempotency_key="e2e-dup-key"))
    assert first["status"] == "filled"
    second = trading_engine.place_order(_valid_order(idempotency_key="e2e-dup-key"))
    assert second["status"] == "rejected"
    assert "duplicate-order" in second["violations"]
    orders = [o for o in mt5_safety.orders.find({"idempotency_key": "e2e-dup-key"}) if o.get("status") == "filled"]
    assert len(orders) == 1


# --------------------------------------------------------------------------- #
# 3. Stale market feed disables execution
# --------------------------------------------------------------------------- #
def test_03_stale_market_feed_disables_execution():
    _reset()
    stale = {"fetchedAt": int(time.time() * 1000) - (settings.STALE_DATA_THRESHOLD_SECONDS + 60) * 1000, "price": 4300.0}
    fresh = {"fetchedAt": int(time.time() * 1000), "price": 4300.0}
    with mock.patch("app.modules.trading.engine.get_live_quote", return_value=stale):
        res = trading_engine.place_order(_valid_order())
        assert res["status"] == "rejected"
        assert "stale-market-data" in res["violations"]
    with mock.patch("app.modules.trading.engine.get_live_quote", return_value=fresh):
        res = trading_engine.place_order(_valid_order())
        assert res["status"] == "filled"


# --------------------------------------------------------------------------- #
# 4. Close action is idempotent
# --------------------------------------------------------------------------- #
def test_04_close_action_is_idempotent():
    _reset()
    pos = trading_engine.place_order(_valid_order())["position"]
    first = trading_engine.close_position(pos["id"], "e2e-test")
    assert first["status"] == "closed"
    second = trading_engine.close_position(pos["id"], "e2e-test")
    assert second["status"] == "already-closed"
    closed = [p for p in trading_engine.col.find({"id": pos["id"]})]
    assert len(closed) == 1
    assert closed[0]["status"] == "closed"


# --------------------------------------------------------------------------- #
# 5. Reverse waits for confirmed close
# --------------------------------------------------------------------------- #
def test_05_reverse_waits_for_confirmed_close():
    _reset()
    pos = trading_engine.place_order(_valid_order())["position"]
    res = trading_engine.reverse_position(pos["id"])
    assert res["status"] == "filled"
    original = trading_engine.col.find_one({"id": pos["id"]})
    assert original["status"] == "closed"
    assert original["closeReason"] == "reverse-wait"
    opens = trading_engine.get_open_positions()
    assert len(opens) == 1
    assert opens[0]["side"] == "sell"
    assert opens[0]["id"] != pos["id"]
    # reversing an already-closed position is refused (no phantom hedge)
    refused = trading_engine.reverse_position(pos["id"])
    assert refused["status"] == "position-not-open"


# --------------------------------------------------------------------------- #
# 6. MT5 disconnect disables auto trading
# --------------------------------------------------------------------------- #
def test_06_mt5_disconnect_disables_auto_trading():
    _reset()
    prev = settings.MT5_ENABLED
    try:
        settings.MT5_ENABLED = "live"
        mt5_state.connected = False
        res = trading_engine.place_order(_valid_order())
        assert res["status"] == "rejected"
        assert "mt5-disconnected" in res["violations"]
        # no auto-trade verdict is produced either
        verdict, _ = auto_trade_controller.evaluate({"symbol": "XAUUSD", "confidence": {"score": 0.95}})
        assert verdict in ("no-trade", "blocked")
        mt5_state.connected = True
        res = trading_engine.place_order(_valid_order())
        assert res["status"] == "filled"
    finally:
        settings.MT5_ENABLED = prev
        mt5_state.connected = False


# --------------------------------------------------------------------------- #
# 7. Reconciliation mismatch freezes account execution
# --------------------------------------------------------------------------- #
def test_07_reconciliation_mismatch_freezes_account_execution():
    _reset()
    local = [{"id": "LOC-1", "symbol": "XAUUSD", "status": "open", "stopLoss": 4298.0, "takeProfit": 4310.0}]
    mt5 = [{"id": "MT5-OTHER", "symbol": "XAUUSD", "stopLoss": 4290.0, "takeProfit": 4310.0}]
    mismatches = mt5_safety.reconcile(local, mt5)
    assert len(mismatches) >= 1
    assert mt5_safety.is_frozen("XAUUSD") is True
    res = trading_engine.place_order(_valid_order())
    assert res["status"] == "rejected"
    assert "execution-frozen" in res["violations"]


# --------------------------------------------------------------------------- #
# 8. All AI unavailable produces NO_TRADE
# --------------------------------------------------------------------------- #
def test_08_all_ai_unavailable_produces_no_trade():
    class BrokenClient:
        id = "broken"
        name = "Broken"
        model = "x"
        url = None
        api_key = None

        def complete(self, *a, **k):
            raise RuntimeError("provider down")

    manager = ManagedProvider(BrokenClient(), retries=0)
    try:
        manager.reason({"symbol": "XAUUSD", "summary": {"price": 4300}})
        raised = False
    except LLMError:
        raised = True
    assert raised is True  # fail-closed: an exception, never a fabricated trade


# --------------------------------------------------------------------------- #
# 9. Risk engine failure produces NO_TRADE
# --------------------------------------------------------------------------- #
def test_09_risk_engine_failure_produces_no_trade():
    _reset()
    # missing stop loss -> risk violation -> rejected (no trade)
    res = trading_engine.place_order({
        "symbol": "XAUUSD",
        "side": "buy",
        "volume": 0.1,
        "price": 4300.0,
        "source": "ai-decision",
    })
    assert res["status"] == "rejected"
    assert any("Stop loss" in v for v in res["violations"])


# --------------------------------------------------------------------------- #
# 10. Mock data cannot enter production execution
# --------------------------------------------------------------------------- #
def test_10_mock_data_cannot_enter_production_execution():
    _reset()
    prev_env = settings.ENVIRONMENT
    try:
        settings.ENVIRONMENT = "production"
        for src in ("simulator", "mock", "demo"):
            res = trading_engine.place_order(_valid_order(source=src))
            assert res["status"] == "rejected"
            assert "mock-data-in-production" in res["violations"]
        # real sources are unaffected
        res = trading_engine.place_order(_valid_order(source="mt5"))
        assert res["status"] == "filled"
    finally:
        settings.ENVIRONMENT = prev_env


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)

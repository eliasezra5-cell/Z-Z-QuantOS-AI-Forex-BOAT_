"""MANDATORY SAFETY TESTS — Batch 41.

Covers the missing safety guarantees so every fail-closed path is proven:

  1. Duplicate news  -> no duplicate trade
  2. Duplicate API   -> no duplicate order
  4. Stale market feed disables execution
  6. Close action is idempotent
  7. Reverse waits for confirmed close
  8. MT5 disconnect disables auto trading / order placement
  9. Reconciliation mismatch freezes execution
 10. Unavailable AI falls back safely
 11. All AI unavailable -> fail-closed (no fabricated trade)
 12. Invalid AI JSON   -> fail-closed (never trades on garbage)
 13. Risk failure      -> order rejected
 15. Mock data cannot enter production

(3/5/14 already covered: stale-news decay, opposite-news re-analysis,
capital-protection override.)

Run with: python3 -m pytest app/tests/test_safety_gates.py -q
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_safety_test")

from unittest import mock  # noqa: E402

import pytest  # noqa: E402

from app.foundation.json_store import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.modules.trading.engine import trading_engine  # noqa: E402
from app.modules.execution.mt5_safety import mt5_safety  # noqa: E402
from app.modules.ai.clients import (  # noqa: E402
    ManagedProvider,
    ProviderManager,
    LocalFallbackClient,
    LLMError,
    _parse_model_json,
)
from app.modules.mt5.adapter import mt5_state  # noqa: E402


def _reset():
    for name in ("positions", "orders", "news_traded", "mt5_safety_orders", "mt5_frozen_symbols", "mt5_reconciliation"):
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
# 1. Duplicate news -> no duplicate trade
# --------------------------------------------------------------------------- #
def test_duplicate_news_blocks_second_trade():
    _reset()
    first = trading_engine.place_order(_valid_order(newsFingerprint="fp-news-1"))
    assert first["status"] == "filled"
    second = trading_engine.place_order(_valid_order(newsFingerprint="fp-news-1"))
    assert second["status"] == "rejected"
    assert "duplicate-news-trade" in second["violations"]
    # a different news story is unaffected
    other = trading_engine.place_order(_valid_order(newsFingerprint="fp-news-2"))
    assert other["status"] == "filled"


# --------------------------------------------------------------------------- #
# 2. Duplicate API (same idempotency key) -> no duplicate order
# --------------------------------------------------------------------------- #
def test_duplicate_api_order_is_rejected():
    _reset()
    first = trading_engine.place_order(_valid_order(idempotency_key="dup-key-1"))
    assert first["status"] == "filled"
    second = trading_engine.place_order(_valid_order(idempotency_key="dup-key-1"))
    assert second["status"] == "rejected"
    assert "duplicate-order" in second["violations"]
    # different key still works
    other = trading_engine.place_order(_valid_order(idempotency_key="dup-key-2"))
    assert other["status"] == "filled"


# --------------------------------------------------------------------------- #
# 4. Stale market feed disables execution
# --------------------------------------------------------------------------- #
def test_stale_market_feed_blocks_execution():
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
# 6. Close action is idempotent
# --------------------------------------------------------------------------- #
def test_close_position_is_idempotent():
    _reset()
    pos = trading_engine.place_order(_valid_order())["position"]
    first = trading_engine.close_position(pos["id"], "test")
    assert first["status"] == "closed"
    second = trading_engine.close_position(pos["id"], "test")
    assert second["status"] == "already-closed"
    # still exactly one closed record, no double-close corruption
    closed = [p for p in trading_engine.col.find({"id": pos["id"]})]
    assert len(closed) == 1
    assert closed[0]["status"] == "closed"


# --------------------------------------------------------------------------- #
# 7. Reverse waits for confirmed close
# --------------------------------------------------------------------------- #
def test_reverse_waits_for_confirmed_close():
    _reset()
    pos = trading_engine.place_order(_valid_order())["position"]
    res = trading_engine.reverse_position(pos["id"])
    assert res["status"] == "filled"
    # original must be closed and opposite position opened
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
# 8. MT5 disconnect disables order placement
# --------------------------------------------------------------------------- #
def test_mt5_disconnect_blocks_execution():
    _reset()
    prev = settings.MT5_ENABLED
    try:
        settings.MT5_ENABLED = "live"
        mt5_state.connected = False
        res = trading_engine.place_order(_valid_order())
        assert res["status"] == "rejected"
        assert "mt5-disconnected" in res["violations"]
        mt5_state.connected = True
        res = trading_engine.place_order(_valid_order())
        assert res["status"] == "filled"
    finally:
        settings.MT5_ENABLED = prev
        mt5_state.connected = False


# --------------------------------------------------------------------------- #
# 9. Reconciliation mismatch freezes execution
# --------------------------------------------------------------------------- #
def test_reconciliation_mismatch_freezes_symbol():
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
# 10. Unavailable AI falls back safely
# --------------------------------------------------------------------------- #
def test_ai_falls_back_when_primary_fails():
    class BrokenClient:
        id = "broken-primary"
        name = "Broken"
        model = "x"
        url = None
        api_key = None

        def complete(self, *a, **k):
            raise RuntimeError("provider down")

    broken = ManagedProvider(BrokenClient(), retries=0)
    fallback = ManagedProvider(LocalFallbackClient(), retries=0)
    manager = ProviderManager([broken, fallback])
    result = manager.reason({"symbol": "XAUUSD", "summary": {"price": 4300}})
    assert result["direction"] in ("buy", "sell", "neutral")
    assert result["model"] == "local-fallback"


# --------------------------------------------------------------------------- #
# 11. All AI unavailable -> fail-closed (never fabricates a trade)
# --------------------------------------------------------------------------- #
def test_all_ai_unavailable_is_fail_closed():
    class BrokenClient:
        id = "broken"
        name = "Broken"
        model = "x"
        url = None
        api_key = None

        def complete(self, *a, **k):
            raise RuntimeError("provider down")

    manager = ProviderManager([ManagedProvider(BrokenClient(), retries=0) for _ in range(3)])
    try:
        manager.reason({"symbol": "XAUUSD"})
        raised = False
    except LLMError:
        raised = True
    assert raised is True  # fail-closed: an exception, never a fake trade


# --------------------------------------------------------------------------- #
# 12. Invalid AI JSON -> fail-closed (never trades on garbage)
# --------------------------------------------------------------------------- #
def test_invalid_ai_json_is_fail_closed():
    _reset()
    with pytest.raises(LLMError):
        _parse_model_json("not json at all", "broken-primary")
    with pytest.raises(LLMError):
        _parse_model_json("", "broken-primary")

    class GarbageClient:
        id = "garbage"
        name = "Garbage"
        model = "x"
        url = None
        api_key = None

        def complete(self, *a, **k):
            return {"text": "{broken json", "model": "garbage", "usage": {}, "provider": "garbage"}

    garbage = ManagedProvider(GarbageClient(), retries=0)
    fallback = ManagedProvider(LocalFallbackClient(), retries=0)
    manager = ProviderManager([garbage, fallback])
    result = manager.reason({"symbol": "XAUUSD"})
    assert result["model"] == "local-fallback"  # garbage never trades, falls back safely


# --------------------------------------------------------------------------- #
# 13. Risk failure -> NO_TRADE (order rejected before execution)
# --------------------------------------------------------------------------- #
def test_risk_failure_rejects_order():
    _reset()
    # No stop loss -> "Stop loss required" risk violation -> rejected
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
# 15. Mock data cannot enter production
# --------------------------------------------------------------------------- #
def test_mock_data_blocked_in_production():
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

"""Tests for market-data quality gates + cross-market alignment.

Run with: python3 -m pytest app/tests/test_quality_gates.py -q
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_quality_gates")

from app.modules.marketdata.quality_gates import validate_quote, cross_market_check  # noqa: E402

T0 = 1_700_000_000_000

GATE_KEYS = {"monotonicTimestamp", "duplicateTick", "gap", "outlier", "ohlc", "session", "sequenceGap"}


def _quote(**overrides):
    q = {
        "symbol": "EURUSD",
        "bid": 1.1000,
        "ask": 1.1002,
        "price": 1.1001,
        "spread": 0.0002,
        "timestamp": T0,
        "seq": 100,
        "open": 1.0995,
        "high": 1.1010,
        "low": 1.0989,
        "close": 1.1001,
    }
    q.update(overrides)
    return q


def test_gate_keys_shape():
    prev = _quote(timestamp=T0 - 1000, price=1.1000, seq=99)
    res = validate_quote(_quote(), prev)
    assert res["valid"] is True
    assert set(res["gates"].keys()) == GATE_KEYS
    assert "failedGates" in res
    assert "hardFailed" in res


def test_valid_quote_passes_all_gates():
    prev = _quote(
        timestamp=T0 - 1000, price=1.0999, seq=99, bid=1.0998, ask=1.1000,
        open=1.0995, high=1.1005, low=1.0988, close=1.0999,
    )
    res = validate_quote(_quote(), prev)
    assert res["valid"] is True
    assert all(v is False for v in res["gates"].values())
    assert res["failedGates"] == []


def test_monotonic_timestamp_violation():
    prev = _quote(timestamp=T0, price=1.1000, seq=99)
    quote = _quote(timestamp=T0 - 5000, price=1.1001, seq=100)
    res = validate_quote(quote, prev)
    assert res["gates"]["monotonicTimestamp"] is True
    assert sum(res["gates"].values()) == 1


def test_duplicate_tick_detection():
    prev = _quote(timestamp=T0, price=1.1001, seq=100)
    quote = _quote(timestamp=T0, price=1.1001, seq=101)
    res = validate_quote(quote, prev)
    assert res["gates"]["duplicateTick"] is True
    assert sum(res["gates"].values()) == 1


def test_gap_detection():
    prev = _quote(timestamp=T0 - 1000, price=100.0, seq=99)
    quote = _quote(timestamp=T0, price=108.0, seq=100)
    res = validate_quote(quote, prev)
    assert res["gates"]["gap"] is True
    assert sum(res["gates"].values()) == 1


def test_outlier_detection():
    quote = _quote(timestamp=T0, price=-5.0, seq=100)
    res = validate_quote(quote, None)
    assert res["gates"]["outlier"] is True
    assert sum(res["gates"].values()) == 1


def test_ohlc_invalid():
    quote = _quote(timestamp=T0, price=1.1001, seq=100, open=1.0995, close=1.1001, high=1.0980, low=1.0989)
    res = validate_quote(quote, None)
    assert res["gates"]["ohlc"] is True
    assert sum(res["gates"].values()) == 1


def test_session_bounds():
    session = {"name": "Tokyo", "open": 0, "close": 9}
    inside_ts = int(datetime(2026, 8, 7, 3, 30, tzinfo=timezone.utc).timestamp() * 1000)
    outside_ts = int(datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)
    ok = validate_quote(_quote(timestamp=inside_ts), None, session=session)
    assert ok["gates"]["session"] is False
    bad = validate_quote(_quote(timestamp=outside_ts), None, session=session)
    assert bad["gates"]["session"] is True
    assert sum(bad["gates"].values()) == 1


def test_sequence_gap():
    prev = _quote(timestamp=T0 - 1000, price=1.1000, seq=99)
    quote = _quote(timestamp=T0, price=1.1001, seq=102)
    res = validate_quote(quote, prev)
    assert res["gates"]["sequenceGap"] is True
    assert sum(res["gates"].values()) == 1


def test_cross_market_aligned():
    quotes = {
        "DXY": {"price": 103.5, "change24h": -0.4},
        "XAUUSD": {"price": 4321.0, "change24h": 1.2},
        "EURUSD": {"price": 1.1200, "change24h": 0.3},
    }
    res = cross_market_check(quotes)
    assert res["crossMarketAligned"] is True
    assert res["divergences"] == []


def test_cross_market_contradictory():
    quotes = {
        "DXY": {"price": 103.5, "change24h": -0.4},
        "XAUUSD": {"price": 4290.0, "change24h": -1.2},
    }
    res = cross_market_check(quotes)
    assert res["crossMarketAligned"] is False
    assert len(res["divergences"]) >= 1

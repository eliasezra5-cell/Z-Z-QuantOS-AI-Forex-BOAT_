"""Unit tests for additive historical intelligence (Batch 06).

Covers the named-event catalog, Market Memory Service (with PIT guards) and
pattern matching helpers. No network calls.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test")

import time  # noqa: E402

from app.modules.historical.memory import (  # noqa: E402
    NAMED_EVENTS,
    MarketMemoryService,
    init_historical_memory,
    match_named_events,
    named_events,
)


def test_named_events_catalog_has_20_plus():
    assert len(NAMED_EVENTS) >= 20


def test_named_events_filters_by_symbol():
    gold = named_events(symbol="XAUUSD")
    assert all(e["symbol"] == "XAUUSD" for e in gold)


def test_named_events_filters_by_category():
    cb = named_events(category="central-banks")
    assert all(e["category"] == "central-banks" for e in cb)
    assert len(cb) > 0


def test_market_memory_records_and_counts():
    service = MarketMemoryService()
    before = service.count()
    service.record({"symbol": "XAUUSD", "driver": "NFP", "category": "macro", "direction": "buy", "movePips": 100, "summary": "test"})
    assert service.count() == before + 1


def test_market_memory_pit_guard_drops_future_entries():
    from app.foundation.json_store import db
    db.collection("market_memory").clear()
    service = MarketMemoryService()
    now = int(time.time() * 1000)
    future = service.record({"symbol": "XAUUSD", "pitAsOf": now + 10 * 3600000, "summary": "future"})
    past = service.record({"symbol": "XAUUSD", "pitAsOf": now - 10 * 3600000, "summary": "past"})
    results = service.query(symbol="XAUUSD", k=10, pit_as_of=now)
    ids = {r["id"] for r in results}
    assert past["id"] in ids
    assert future["id"] not in ids


def test_match_named_events_returns_top5():
    matches = match_named_events("XAUUSD")
    assert len(matches) <= 5
    assert all("relevance" in m for m in matches)


def test_match_named_events_driver_filter():
    matches = match_named_events("XAUUSD", driver="FOMC")
    assert all(m["driver"] == "FOMC" for m in matches)


def test_init_seeds_memory():
    init_historical_memory()
    assert len(NAMED_EVENTS) >= 20

"""Unit tests for the weighted news trust/confidence formulas (Task 1).

Covers: weight normalization, monotonic component sensitivity, fake/clickbait
down-ranking and structured event extraction. No real network calls.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_news_scoring_test")

from app.modules.news.engine import (  # noqa: E402
    CONFIDENCE_WEIGHTS,
    TRUST_WEIGHTS,
    analyze_news_item,
    extract_event,
)

NOW = int(time.time() * 1000)

CLEAN_ITEM = {
    "title": "Fed officials signal patience on rate cuts",
    "source": "Reuters",
    "url": "https://example.com/fed-patience",
    "crossReference": ["source-a", "source-b", "source-c"],
    "time": NOW,
}

FAKE_ITEM = {
    "title": "SHOCKING!!! GUARANTEED 100% INSIDER SECRET to the moon",
    "source": "Reddit",
    "reliability": 0.4,
    "time": NOW,
}


def test_trust_weights_sum_to_one():
    assert abs(sum(TRUST_WEIGHTS.values()) - 1.0) < 1e-9


def test_confidence_weights_sum_to_one():
    assert abs(sum(CONFIDENCE_WEIGHTS.values()) - 1.0) < 1e-9


def test_trust_moves_monotonically_with_source_reliability():
    low = analyze_news_item({**CLEAN_ITEM, "reliability": 0.7})
    high = analyze_news_item({**CLEAN_ITEM, "reliability": 0.99})
    assert high["trustScore"] > low["trustScore"]
    assert 0 <= low["trustScore"] <= 1
    assert 0 <= high["trustScore"] <= 1


def test_trust_moves_monotonically_with_cross_reference_count():
    single = analyze_news_item({**CLEAN_ITEM, "crossReference": ["source-a"]})
    multi = analyze_news_item({**CLEAN_ITEM, "crossReference": ["a", "b", "c", "d", "e"]})
    assert multi["trustScore"] >= single["trustScore"]


def test_fake_clickbait_scores_lower_than_clean_verified():
    clean = analyze_news_item(CLEAN_ITEM)
    fake = analyze_news_item(FAKE_ITEM)
    assert fake["trustScore"] < clean["trustScore"]
    assert fake["confidence"] < clean["confidence"]
    assert fake["trustScore"] < 0.7
    assert clean["trustScore"] > 0.7


def test_extract_event_detects_cpi_release():
    event = extract_event({"title": "US CPI data comes in hot, inflation rises", "entities": ["USD", "CPI"]})
    assert event["hasEvent"] is True
    assert event["eventType"] == "cpi"
    assert event["currency"] == "USD"


def test_extract_event_detects_geopolitics():
    event = extract_event({"title": "Oil markets react to escalating geopolitical tensions", "entities": ["WTI", "oil"]})
    assert event["hasEvent"] is True
    assert event["eventType"] == "geopolitics"


def test_extract_event_returns_none_for_unrelated_item():
    event = extract_event({"title": "Bitcoin surges past resistance on ETF inflows", "entities": ["BTC"]})
    assert event["eventType"] == "none"
    assert event["hasEvent"] is False


def test_processed_item_has_event_attached():
    item = analyze_news_item({"title": "US CPI data comes in hot", "source": "Reuters", "url": "https://example.com/cpi", "time": NOW})
    assert item["event"]["hasEvent"] is True
    assert item["event"]["eventType"] == "cpi"

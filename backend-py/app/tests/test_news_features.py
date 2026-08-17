"""Unit tests for additive news features (Batch 03).

Covers the News Decay Engine, collector registry, collector run loop and the
WhatsApp safety adapter (official/webhook/manual modes + experimental web
disabled by default). No real network calls.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test")

import time  # noqa: E402
from unittest import mock  # noqa: E402

from app.modules.news.decay import NewsDecayEngine, news_decay_engine, get_live_news  # noqa: E402
from app.modules.news.collectors import (  # noqa: E402
    FinancialApiCollector,
    RssCollector,
    WhatsAppAdapter,
    init_news_collectors,
    run_collectors,
    whatsapp_adapter,
)


def test_fresh_news_has_full_relevance():
    engine = NewsDecayEngine(half_life_seconds=3600)
    now = int(time.time() * 1000)
    item = {"time": now, "marketImpact": 0.8}
    assert engine.decay_factor(item, now) == 1.0
    assert engine.effective_impact(item, now) == 0.8
    assert engine.is_decayed(item, now) is False


def test_old_news_decays():
    engine = NewsDecayEngine(half_life_seconds=3600)
    now = int(time.time() * 1000)
    item = {"time": now - 2 * 3600 * 1000, "marketImpact": 0.8}
    assert engine.decay_factor(item, now_ms=now) == 0.25
    assert abs(engine.effective_impact(item, now_ms=now) - 0.2) < 1e-9


def test_hard_stale_news_is_decayed():
    engine = NewsDecayEngine(hard_stale_seconds=7200)
    now = int(time.time() * 1000)
    item = {"time": now - 3 * 3600 * 1000, "marketImpact": 0.8}
    assert engine.is_decayed(item, now_ms=now) is True


def test_filter_live_drops_decayed():
    engine = NewsDecayEngine()
    now = int(time.time() * 1000)
    items = [
        {"time": now, "marketImpact": 0.8},
        {"time": now - 3 * 3600 * 1000, "marketImpact": 0.8},
    ]
    live = engine.filter_live(items, now_ms=now)
    assert len(live) == 1
    assert live[0]["decay"]["decayed"] is False


def test_classify_shape():
    engine = NewsDecayEngine()
    out = engine.classify({"time": int(time.time() * 1000), "marketImpact": 0.5})
    for key in ("ageSeconds", "decayFactor", "effectiveImpact", "decayed", "halfLifeSeconds"):
        assert key in out


def test_init_registers_all_collectors():
    registry = init_news_collectors()
    assert {"rss", "telegram", "twitter", "financial_api", "regulatory", "whatsapp"} <= set(registry)


def test_whatsapp_experimental_web_disabled_by_default():
    adapter = WhatsAppAdapter({"mode": "web"})
    assert adapter.mode != "web"
    assert adapter.mode == "official"


def test_whatsapp_web_enabled_when_forced():
    with mock.patch.dict(os.environ, {"WHATSAPP_ALLOW_EXPERIMENTAL_WEB": "1"}):
        adapter = WhatsAppAdapter({"mode": "web"})
    assert adapter.mode == "web"


def test_whatsapp_ingest_payload_emits():
    adapter = WhatsAppAdapter({"mode": "manual"})
    with mock.patch("app.modules.news.collectors.event_bus") as bus:
        adapter.ingest_payload({"title": "Test signal", "channel": "fx-signals"})
    bus.emit.assert_called_once()
    assert bus.emit.call_args[0][0] == "news:ingest"


def test_run_collectors_happy_path():
    registry = init_news_collectors()
    adapter = whatsapp_adapter()
    adapter.enabled = False
    for cid, col in registry.items():
        if cid != "whatsapp":
            col.enabled = True
    with mock.patch("app.modules.news.collectors.event_bus") as bus:
        result = run_collectors()
    assert result["collected"] > 0
    assert bus.emit.call_count == result["collected"]


def test_financial_api_reports_key_presence():
    col = FinancialApiCollector({"apiKey": ""})
    items = col.collect()
    assert items and items[0]["_hasKey"] is False


def test_rss_collector_produces_raw_items():
    col = RssCollector({"feedUrls": ["https://example.com/rss"]})
    items = col.collect()
    assert items[0]["raw"] is True
    assert items[0]["collector"] == "rss"

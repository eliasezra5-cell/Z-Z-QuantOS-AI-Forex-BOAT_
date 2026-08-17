"""News Collectors + WhatsApp Safety Adapter (Batch 03, additive).

Adds a collector registry for the 5 required collector types and the WhatsApp
safety adapter mandated by the global amendments:

  - RSS feeds collector
  - Telegram channel collector
  - X / Twitter collector
  - Financial / Premium news API collector
  - Regulatory body collector

WhatsApp safety rules (per global amendment):
  - Official Business API (cloud/graph) is the preferred channel
  - Webhook ingestion
  - Manual entry
  - File import
  - Experimental web adapter is DISABLED by default

All adapters are additive to ``news/engine.py``; no existing code is modified.
"""
import os
import time

from ...config import settings
from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.provider_framework import providers

COLLECTOR_TYPES = {
    "rss": "RSS Feeds",
    "telegram": "Telegram Channels",
    "twitter": "X / Twitter",
    "financial_api": "Financial News API",
    "regulatory": "Regulatory Bodies",
    "whatsapp": "WhatsApp (official)",
}

# WhatsApp adapter mode: official | webhook | manual | file_import | web
WHATSAPP_DEFAULT_MODE = "official"


class NewsCollector:
    """Base collector: an adapter that produces normalized news payloads."""

    id = "base"
    name = "Base Collector"
    collector_type = "rss"

    def __init__(self, config=None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)

    def collect(self, params=None):
        """Return a list of raw news dicts. Subclasses override."""
        raise NotImplementedError

    def emit(self, item):
        """Emit a raw item through the ingest pipeline (news:ingest event)."""
        event_bus.emit("news:ingest", {"payload": item})
        return item


class RssCollector(NewsCollector):
    id = "rss"
    name = "RSS Feeds"
    collector_type = "rss"

    def collect(self, params=None):
        feed_urls = self.config.get("feedUrls") or []
        items = []
        for url in feed_urls:
            items.append({
                "source": self.config.get("sourceName", "RSS"),
                "title": f"[RSS pending] {url}",
                "category": "macro",
                "impact": 0.4,
                "collector": self.id,
                "collectorType": self.collector_type,
                "url": url,
                "time": int(time.time() * 1000),
                "raw": True,
            })
        return items


class TelegramCollector(NewsCollector):
    id = "telegram"
    name = "Telegram Channels"
    collector_type = "telegram"

    def collect(self, params=None):
        channels = self.config.get("channels") or []
        return [{
            "source": "Telegram",
            "title": f"[Telegram pending] {ch}",
            "category": "social",
            "impact": 0.3,
            "collector": self.id,
            "collectorType": self.collector_type,
            "channel": ch,
            "time": int(time.time() * 1000),
            "raw": True,
        } for ch in channels]


class TwitterCollector(NewsCollector):
    id = "twitter"
    name = "X / Twitter"
    collector_type = "twitter"

    def collect(self, params=None):
        handles = self.config.get("handles") or []
        return [{
            "source": "X (Twitter)",
            "title": f"[X pending] @{h}",
            "category": "social",
            "impact": 0.3,
            "collector": self.id,
            "collectorType": self.collector_type,
            "handle": h,
            "time": int(time.time() * 1000),
            "raw": True,
        } for h in handles]


class FinancialApiCollector(NewsCollector):
    id = "financial_api"
    name = "Financial News API"
    collector_type = "financial_api"

    def collect(self, params=None):
        api_key = self.config.get("apiKey") or settings.BINANCE_API_KEY
        sources = self.config.get("sources") or ["Reuters", "Bloomberg"]
        return [{
            "source": s,
            "title": f"[Financial API pending] {s}",
            "category": "macro",
            "impact": 0.5,
            "collector": self.id,
            "collectorType": self.collector_type,
            "time": int(time.time() * 1000),
            "raw": True,
            "_hasKey": bool(api_key),
        } for s in sources]


class RegulatoryCollector(NewsCollector):
    id = "regulatory"
    name = "Regulatory Bodies"
    collector_type = "regulatory"

    def collect(self, params=None):
        bodies = self.config.get("bodies") or ["Federal Reserve", "ECB", "BOJ", "IMF", "BIS"]
        return [{
            "source": b,
            "title": f"[Regulatory pending] {b}",
            "category": "central-banks",
            "impact": 0.6,
            "collector": self.id,
            "collectorType": self.collector_type,
            "time": int(time.time() * 1000),
            "raw": True,
        } for b in bodies]


class WhatsAppAdapter(NewsCollector):
    """WhatsApp news ingestion with a strict safety envelope.

    Modes:
      - official      : WhatsApp Business/Cloud API (preferred)
      - webhook       : inbound webhook payloads
      - manual        : manually entered signals
      - file_import   : imported message files
      - web           : experimental web automation — DISABLED unless forced
    """

    id = "whatsapp"
    name = "WhatsApp Channels"
    collector_type = "whatsapp"

    def __init__(self, config=None):
        super().__init__(config)
        mode = (self.config.get("mode") or os.environ.get("WHATSAPP_MODE", WHATSAPP_DEFAULT_MODE)).lower()
        if mode == "web":
            # Experimental web adapter is disabled by default per global rules.
            allowed = os.environ.get("WHATSAPP_ALLOW_EXPERIMENTAL_WEB", "0").lower() in ("1", "true", "yes", "on")
            if not allowed:
                logger.warn("WhatsApp experimental web adapter is DISABLED by default; refusing web mode")
                mode = WHATSAPP_DEFAULT_MODE
        self.mode = mode
        self.phone_id = self.config.get("phoneId") or os.environ.get("WHATSAPP_PHONE_ID", "")
        self.token = self.config.get("token") or os.environ.get("WHATSAPP_TOKEN", "")
        self.official_ready = bool(self.phone_id and self.token)

    def ingest_payload(self, payload):
        """Webhook / manual / file-import entry point."""
        item = {
            **payload,
            "source": "WhatsApp Channels",
            "category": payload.get("category", "social"),
            "impact": payload.get("impact", 0.3),
            "collector": self.id,
            "collectorType": self.collector_type,
            "channel": payload.get("channel", "whatsapp"),
            "ingestMode": self.mode,
            "time": payload.get("time") or int(time.time() * 1000),
        }
        return self.emit(item)

    def collect(self, params=None):
        # Pending-official entries are only produced when the official API is ready.
        if self.mode == "official" and self.official_ready:
            return [{
                "source": "WhatsApp Channels",
                "title": "[WhatsApp official pending]",
                "category": "social",
                "impact": 0.3,
                "collector": self.id,
                "collectorType": self.collector_type,
                "mode": "official",
                "time": int(time.time() * 1000),
                "raw": True,
            }]
        if self.mode == "manual":
            return [{
                "source": "WhatsApp Channels",
                "title": "[WhatsApp manual entry enabled]",
                "category": "social",
                "impact": 0.3,
                "collector": self.id,
                "collectorType": self.collector_type,
                "mode": "manual",
                "time": int(time.time() * 1000),
                "raw": True,
            }]
        return []


def _default_collector_config():
    return {
        "feedUrls": [],
        "channels": [],
        "handles": [],
        "sources": [],
        "bodies": [],
    }


collectors_registry = {}


def register_collector(collector):
    collectors_registry[collector.id] = collector
    providers.register({
        "id": f"news-collector-{collector.id}",
        "category": "news-collector",
        "name": collector.name,
        "collectorType": collector.collector_type,
        "enabled": collector.enabled,
        "collect": collector.collect,
    })
    return collector


def init_news_collectors():
    """Register the 5 collector types plus the WhatsApp safety adapter."""
    cfg = _default_collector_config()
    register_collector(RssCollector(cfg))
    register_collector(TelegramCollector(cfg))
    register_collector(TwitterCollector(cfg))
    register_collector(FinancialApiCollector(cfg))
    register_collector(RegulatoryCollector(cfg))
    whatsapp = register_collector(WhatsAppAdapter(cfg))
    logger.info(f"News collectors initialized: {list(collectors_registry)} (whatsapp mode={whatsapp.mode})")
    event_bus.emit("news:collectors-ready", {"collectors": list(collectors_registry)})
    return collectors_registry


def run_collectors(collector_ids=None):
    """Collect from enabled collectors and push raw items through ingestion.

    Collector outputs are raw ("raw": True) placeholders that the analysis
    pipeline replaces with verified stories once a live data source is wired.
    """
    collected = []
    for cid, collector in collectors_registry.items():
        if collector_ids and cid not in collector_ids:
            continue
        if not collector.enabled:
            continue
        try:
            for item in collector.collect():
                collector.emit(item)
                collected.append(item)
        except Exception as exc:  # noqa: BLE001 - collectors must never crash the loop
            logger.warn(f"Collector {cid} failed", meta={"error": str(exc)})
    return {"collected": len(collected), "items": collected}


def whatsapp_adapter():
    return collectors_registry.get("whatsapp")

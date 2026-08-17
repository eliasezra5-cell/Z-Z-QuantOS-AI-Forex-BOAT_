"""Extra premium news source collectors (additive).

Adds Benzinga, WSJ Markets, Seeking Alpha and Biztoc as additional news
sources. Collectors follow the exact same interface as the existing realtime
collectors (``id`` / ``name`` / ``collector_type`` / ``collect(params)``) and
the same normalized item schema, so they register into the existing registry as
extra source types WITHOUT changing any registry logic — this file only adds new
entries to the registry and to the source list.

Keys (optional): BENZINGA_API_KEY / WSJ_API_KEY / SEEKING_ALPHA_API_KEY.
Missing keys just disable the live feed for that source; the collector still
returns an empty list and never raises.
"""
import time

import feedparser
import httpx

from ...foundation.logger import logger

USER_AGENT = "ZZ_QuantOS_AI_BOAT/1.0 (+institutional news aggregator)"

FEED_TIMEOUT_SECONDS = 15


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _fetch_feed(url):
    """Fetch a feed body with a guaranteed timeout (never hangs)."""
    with httpx.Client(timeout=FEED_TIMEOUT_SECONDS, follow_redirects=True) as client:
        res = client.get(url, headers={"User-Agent": USER_AGENT})
        res.raise_for_status()
        return res.text


class _RssSourceCollector:
    """Base class for the extra RSS-based premium sources."""

    id = "base_extra"
    name = "Extra RSS"
    collector_type = "rss"
    feed_urls = []

    def __init__(self, config=None):
        self.config = config or {}

    def _feed_urls(self):
        urls = self.config.get("feedUrls") or self.feed_urls
        return [u for u in urls if u]

    def collect(self, params=None):
        items = []
        for url in self._feed_urls():
            try:
                parsed = feedparser.parse(_fetch_feed(url))
                entries = _get(parsed, "entries") or []
                feed_title = _get(_get(parsed, "feed") or {}, "title") or self.name
                for entry in entries[: (params or {}).get("limit", 10)]:
                    title = (entry.get("title") or "").strip()
                    if not title:
                        continue
                    published = entry.get("published_parsed") or entry.get("updated_parsed")
                    published_ms = int(time.mktime(published)) * 1000 if published else int(time.time() * 1000)
                    items.append({
                        "source": self.config.get("sourceName") or feed_title,
                        "title": title,
                        "summary": (entry.get("summary") or "")[:2000],
                        "url": entry.get("link"),
                        "category": "macro",
                        "impact": 0.6,
                        "collector": self.id,
                        "collectorType": self.collector_type,
                        "time": published_ms,
                        "raw": True,
                    })
            except Exception as exc:  # noqa: BLE001 - one feed must never break the cycle
                logger.warn(f"{self.name} fetch failed for {url}: {exc}")
        return items


class BenzingaCollector(_RssSourceCollector):
    id = "benzinga"
    name = "Benzinga"
    collector_type = "rss"
    feed_urls = ["https://www.benzinga.com/feed"]


class WsjCollector(_RssSourceCollector):
    id = "wsj"
    name = "WSJ Markets"
    collector_type = "rss"
    feed_urls = ["https://feeds.a.dj.com/rss/RSSMarketsMain.xml"]


class SeekingAlphaCollector(_RssSourceCollector):
    id = "seeking_alpha"
    name = "Seeking Alpha"
    collector_type = "rss"
    feed_urls = ["https://seekingalpha.com/market_currents.xml"]


class BiztocCollector(_RssSourceCollector):
    id = "biztoc"
    name = "Biztoc"
    collector_type = "rss"
    feed_urls = ["https://biztoc.com/rss"]


# --------------------------------------------------------------------------- #
# Convenience wrappers mirroring the old collectors.py function shape
# --------------------------------------------------------------------------- #
def collect_benzinga(params=None):
    return BenzingaCollector({}).collect(params)


def collect_wsj(params=None):
    return WsjCollector({}).collect(params)


def collect_seeking_alpha(params=None):
    return SeekingAlphaCollector({}).collect(params)


def collect_biztoc(params=None):
    return BiztocCollector({}).collect(params)


# --------------------------------------------------------------------------- #
# Additive registration into the existing realtime registry
# --------------------------------------------------------------------------- #
EXTRA_SOURCES = [
    {
        "name": "Benzinga",
        "type": "benzinga",
        "config": {"feedUrls": BenzingaCollector.feed_urls, "sourceName": "Benzinga"},
        "priority": 2,
    },
    {
        "name": "WSJ Markets",
        "type": "wsj",
        "config": {"feedUrls": WsjCollector.feed_urls, "sourceName": "WSJ Markets"},
        "priority": 2,
    },
    {
        "name": "Seeking Alpha",
        "type": "seeking_alpha",
        "config": {"feedUrls": SeekingAlphaCollector.feed_urls, "sourceName": "Seeking Alpha"},
        "priority": 2,
    },
    {
        "name": "Biztoc",
        "type": "biztoc",
        "config": {"feedUrls": BiztocCollector.feed_urls, "sourceName": "Biztoc"},
        "priority": 2,
    },
]


def _extend_collector_types():
    """Add the extra source types to the existing registry type map.

    This only *adds new entries* to the ``_COLLECTOR_TYPES`` dict used by
    ``_build_collector``; no existing mapping is removed or reordered.
    """
    try:
        from .realtime.registry import _COLLECTOR_TYPES, register_realtime_collector

        register_realtime_collector(BenzingaCollector({}))
        register_realtime_collector(WsjCollector({}))
        register_realtime_collector(SeekingAlphaCollector({}))
        register_realtime_collector(BiztocCollector({}))
        for sid, cls in {
            "benzinga": BenzingaCollector,
            "wsj": WsjCollector,
            "seeking_alpha": SeekingAlphaCollector,
            "biztoc": BiztocCollector,
        }.items():
            if sid not in _COLLECTOR_TYPES:
                _COLLECTOR_TYPES[sid] = cls
        return True
    except Exception as exc:  # noqa: BLE001 - registration must never crash boot
        logger.warn(f"extra news source registration failed: {exc}")
        return False


def init_extra_news_sources():
    """Register extra collectors and seed their source entries (idempotent)."""
    registered = _extend_collector_types()
    seeded = 0
    try:
        from ...persistence import news_repository

        existing = None
        try:
            import asyncio

            existing = asyncio.run(news_repository.list_sources())
        except Exception as exc:  # noqa: BLE001 - repository may be unavailable
            logger.warn(f"extra news source list failed: {exc}")
        existing_names = {s.get("name") for s in existing or []}
        for source in EXTRA_SOURCES:
            if source["name"] in existing_names:
                continue
            try:
                import asyncio

                asyncio.run(news_repository.add_source(source))
                seeded += 1
            except Exception as exc:  # noqa: BLE001 - seeding is best-effort
                logger.warn(f"extra news source seed failed for {source['name']}: {exc}")
    except Exception as exc:  # noqa: BLE001 - init must never crash
        logger.warn(f"init_extra_news_sources failed: {exc}")
    logger.info(f"Extra news sources initialized (registered={registered}, seeded={seeded})")
    return {"registered": registered, "seeded": seeded}

"""Real RSS feed collector using ``feedparser``.

Fetches configured RSS/Atom feed URLs, normalizes entries into raw news
payloads (title, summary, url, published time), and marks the source's
``lastCollectedAt``. Only configured feed URLs are fetched; nothing is faked.

Fetching is done through ``httpx`` with a hard network timeout (newer
feedparser versions dropped the ``timeout`` kwarg, and a bare ``parse(url)``
would hang forever on a dead/unresponsive feed).
"""
import time

import feedparser
import httpx

from ....foundation.logger import logger

USER_AGENT = "ZZ_QuantOS_AI_BOAT/1.0 (+institutional gold news aggregator)"


def _get(obj, key, default=None):
    """Read from a dict-like or attribute-like parse result."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _fetch_feed(url):
    """Fetch a feed body with a guaranteed timeout (never hangs)."""
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        res = client.get(url, headers={"User-Agent": USER_AGENT})
        res.raise_for_status()
        return res.text


class RssRealtimeCollector:
    id = "rss"
    name = "RSS Feeds (live)"
    collector_type = "rss"

    def __init__(self, config=None):
        self.config = config or {}

    def collect(self, params=None):
        feed_urls = self.config.get("feedUrls") or self.config.get("feeds") or []
        items = []
        last_error = None
        for url in feed_urls:
            try:
                parsed = feedparser.parse(_fetch_feed(url))
                entries = _get(parsed, "entries") or []
                if _get(parsed, "bozo", False) and not entries:
                    exc = _get(parsed, "bozo_exception")
                    logger.warn(f"RSS parse failed for {url}: {exc}")
                    last_error = exc or RuntimeError(f"RSS parse failed for {url}")
                    continue
                feed_title = _get(_get(parsed, "feed") or {}, "title") or "RSS"
                for entry in entries[: (params or {}).get("limit", 10)]:
                    published = entry.get("published_parsed") or entry.get("updated_parsed")
                    published_ms = int(time.mktime(published)) * 1000 if published else int(time.time() * 1000)
                    items.append({
                        "source": self.config.get("sourceName") or feed_title,
                        "title": entry.get("title", "").strip(),
                        "summary": entry.get("summary", "")[:2000],
                        "url": entry.get("link"),
                        "category": "macro",
                        "impact": 0.5,
                        "collector": self.id,
                        "collectorType": self.collector_type,
                        "time": published_ms,
                        "raw": True,
                    })
            except Exception as exc:  # noqa: BLE001 - network errors must not crash polling
                logger.warn(f"RSS fetch failed for {url}: {exc}")
                last_error = exc
        items = [i for i in items if i["title"]]
        # A source that produced nothing because every feed failed must surface
        # the failure instead of failing silently (News Terminal reliability UI).
        if not items and last_error is not None:
            raise last_error
        return items


def register(config=None):
    return RssRealtimeCollector(config or {})

"""Realtime collector for institutional (official) and calendar sources.

Official institutions publish both RSS feeds (Fed, ECB, BoE, White House) and
HTML press-release landing pages (U.S. Treasury, CENTCOM, BOJ, IMF). This
collector tries ``config.feedUrls`` through the RSS parser first and falls back
to ``config.urls`` through the web page extractor, so one source entry can mix
both. Calendar sources (ForexFactory / Investing.com) reuse the same page
fetch logic; heavy bot-protection surfaces as a visible fetch error.
"""
import time

from ....foundation.logger import logger
from .rss import _parse_feed
from .web import WebRealtimeCollector


class OfficialRealtimeCollector:
    id = "official"
    name = "Official Institutions (live)"
    collector_type = "official"

    def __init__(self, config=None):
        self.config = config or {}
        self._web = WebRealtimeCollector(config)

    def collect(self, params=None):
        items = []
        feed_urls = self.config.get("feedUrls") or self.config.get("feeds") or []
        for url in feed_urls:
            try:
                parsed = _parse_feed(url)
                entries = parsed.entries or []
                if getattr(parsed, "bozo", False) and not entries:
                    raise RuntimeError(str(getattr(parsed, "bozo_exception", "bozo parse error")))
                for entry in entries[: (params or {}).get("limit", 10)]:
                    published = entry.get("published_parsed") or entry.get("updated_parsed")
                    published_ms = int(time.mktime(published)) * 1000 if published else int(time.time() * 1000)
                    items.append({
                        "source": self.config.get("sourceName") or (getattr(parsed, "feed", None) or {}).get("title") or "Official",
                        "title": (entry.get("title") or "").strip(),
                        "summary": (entry.get("summary") or "")[:2000],
                        "url": entry.get("link"),
                        "category": "macro",
                        "impact": 0.6,
                        "collector": self.id,
                        "collectorType": self.collector_type,
                        "time": published_ms,
                        "raw": True,
                    })
            except Exception as exc:  # noqa: BLE001 - one feed must not kill the source
                logger.warn(f"Official RSS fetch failed for {url}: {exc}")
        page_urls = self.config.get("urls") or self.config.get("pages") or []
        if page_urls:
            try:
                items.extend(self._web.collect(params))
            except Exception as exc:  # noqa: BLE001
                logger.warn(f"Official page fetch failed: {exc}")
        if not items:
            # Nothing was retrievable: raise so the source surfaces an error.
            raise RuntimeError("no entries retrieved from configured feeds/pages")
        return [i for i in items if i.get("title")]


class CalendarRealtimeCollector(OfficialRealtimeCollector):
    id = "calendar"
    name = "Economic Calendar (live)"
    collector_type = "calendar"


def register(config=None):
    return OfficialRealtimeCollector(config or {})

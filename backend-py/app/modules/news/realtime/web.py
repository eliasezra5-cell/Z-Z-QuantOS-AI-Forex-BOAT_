"""Real web collector for financial news sites.

Fetches configured article URLs and extracts the headline + lede from the
``<title>`` and meta description tags. This handles official statement pages
(Fed, ECB, BIS...) and press-release landing pages that are not RSS feeds.

This collector is meant for a single URL whose page content changes over time
(e.g. a live statement page). For article feeds with multiple items, prefer an
RSS source. Each poll dedupes against the most-recent persisted item for the
source (title+URL or content hash) and against the per-source
``lastContentHash`` field, so an unchanged page is never re-inserted.

``feedUrls`` entries are also accepted: when a configured URL points to an
RSS/Atom feed (e.g. a blog or news-site feed), it is parsed as a feed and every
entry in it becomes an item — so a single blog/news link can deliver multiple
stories. Fetching always uses a hard timeout, so a dead host can never hang the
poll cycle.
"""
import hashlib
import re
import time

import feedparser
import httpx
import urllib.request

from ....foundation.logger import logger

TIMEOUT_SECONDS = 15
_USER_AGENT = "Mozilla/5.0 (compatible; ZZ_QuantOS_AI_BOAT/1.0; +news collector)"


def _fingerprint(item):
    return hashlib.sha256(
        f"{item.get('url') or ''}|{item.get('title') or ''}".encode("utf-8")
    ).hexdigest()


class WebRealtimeCollector:
    id = "web"
    name = "Web Pages (live)"
    collector_type = "web"

    def __init__(self, config=None):
        self.config = config or {}

    def collect(self, params=None):
        params = params or {}
        urls = self.config.get("urls") or self.config.get("pages") or []
        feed_urls = self.config.get("feedUrls") or []
        recent = params.get("recent") or []
        items = []
        # Feed links and plain pages are both accepted. A URL is tried as a feed
        # first (a blog/news-site feed yields multiple stories); if it is not a
        # feed, it falls back to single-page extraction (title + description).
        for url in list(dict.fromkeys(feed_urls + urls)):
            try:
                entries = self._collect_feed(url, params, recent)
                if not entries:
                    item = self._fetch_page(url)
                    if item:
                        item["contentHash"] = _fingerprint(item)
                        if not self._is_duplicate(item, recent):
                            entries = [item]
                items.extend(entries)
            except Exception as exc:  # noqa: BLE001 - non-fatal
                logger.warn(f"Web fetch failed for {url}: {exc}")
        return items

    def _collect_feed(self, url, params, recent):
        """Parse an RSS/Atom feed URL into multiple news items."""
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            res = client.get(url, headers={"User-Agent": _USER_AGENT})
            res.raise_for_status()
            body = res.text
        parsed = feedparser.parse(body)
        feed_title = (parsed.get("feed") or {}).get("title") or url
        out = []
        for entry in (parsed.get("entries") or [])[: (params or {}).get("limit", 10)]:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            published_ms = int(time.mktime(published)) * 1000 if published else int(time.time() * 1000)
            item = {
                "source": self.config.get("sourceName") or feed_title,
                "title": title[:400],
                "summary": (entry.get("summary") or "")[:2000],
                "url": entry.get("link"),
                "category": self.config.get("category", "macro"),
                "impact": self.config.get("impact", 0.5),
                "collector": self.id,
                "collectorType": self.collector_type,
                "time": published_ms,
                "raw": True,
            }
            item["contentHash"] = _fingerprint(item)
            if self._is_duplicate(item, recent):
                continue
            out.append(item)
        return out

    def _is_duplicate(self, item, recent):
        """True when the page matches the last persisted item for the source.

        Compared against the per-source ``lastContentHash`` and against the
        most-recent stored items passed in by the poll cycle (title+URL or
        content hash), so an unchanged page is not inserted twice.
        """
        fingerprint = item.get("contentHash")
        if fingerprint and self.config.get("lastContentHash") == fingerprint:
            return True
        title = item.get("title") or ""
        url = item.get("url")
        for prev in recent or []:
            if fingerprint and prev.get("contentHash") == fingerprint:
                return True
            if url and prev.get("url") == url and (prev.get("title") or "") == title:
                return True
        return False

    def _fetch_page(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        resp = urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS)
        try:
            html = resp.read().decode("utf-8", errors="replace")
        finally:
            resp.close()
        title = _extract_title(html) or url
        summary = _extract_meta(html, "description") or title
        return {
            "source": self.config.get("sourceName") or url,
            "title": title.strip()[:400],
            "summary": summary.strip()[:2000],
            "url": url,
            "category": self.config.get("category", "macro"),
            "impact": self.config.get("impact", 0.5),
            "collector": self.id,
            "collectorType": self.collector_type,
            "time": int(time.time() * 1000),
            "raw": True,
        }


def _extract_title(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if m:
        return _clean(m.group(1))
    return ""


def _extract_meta(html, name):
    m = re.search(rf'<meta[^>]+name=["\']{name}["\'][^>]+content=["\'](.*?)["\']', html, re.DOTALL | re.IGNORECASE)
    if not m:
        m = re.search(rf'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']{name}["\']', html, re.DOTALL | re.IGNORECASE)
    return _clean(m.group(1)) if m else ""


def _clean(text):
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"').strip()


def register(config=None):
    return WebRealtimeCollector(config or {})

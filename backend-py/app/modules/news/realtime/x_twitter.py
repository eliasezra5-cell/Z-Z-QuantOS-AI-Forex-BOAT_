"""Real X / Twitter collector.

Uses the official Twitter API v2 (``search/recent``) when a bearer token is
configured (``config.bearerToken`` or ``TWITTER_BEARER_TOKEN`` env), otherwise
falls back to Nitter public RSS feeds for the configured handles. Nothing is
faked: an unconfigured collector returns an empty list.
"""
import os
import time

import httpx

from ....foundation.logger import logger

TIMEOUT_SECONDS = 15

# Nitter instances are community mirrors that come and go. The collector tries
# the configured/primary host first, then falls back through this list until one
# responds. Override with the comma-separated NITTER_FALLBACK_HOSTS env var.
DEFAULT_NITTER_FALLBACK_HOSTS = [
    "nitter.privacyredirect.com",
    "nitter.tiekoetter.com",
    "xcancel.com",
    "nitter.poast.org",
    "lightbrd.com",
]


def _parse_hosts(value):
    if not value:
        return []
    return [h.strip() for h in value.split(",") if h and h.strip()]


class XTwitterRealtimeCollector:
    id = "twitter"
    name = "X / Twitter (live)"
    collector_type = "twitter"

    def __init__(self, config=None):
        self.config = config or {}
        self.bearer_token = self.config.get("bearerToken") or os.environ.get("TWITTER_BEARER_TOKEN", "")
        self.nitter_host = self.config.get("nitterHost") or os.environ.get("NITTER_HOST", "nitter.net")
        self.nitter_fallback_hosts = _parse_hosts(os.environ.get("NITTER_FALLBACK_HOSTS", "")) or DEFAULT_NITTER_FALLBACK_HOSTS

    def collect(self, params=None):
        handles = self.config.get("handles") or []
        items = []
        for handle in handles:
            handle = str(handle).lstrip("@")
            if self.bearer_token:
                items.extend(self._api_tweets(handle, (params or {}).get("limit", 10)))
            else:
                items.extend(self._nitter_rss(handle, (params or {}).get("limit", 10)))
        return [i for i in items if i["title"]]

    def _api_tweets(self, handle, limit):
        url = "https://api.twitter.com/2/tweets/search/recent"
        query = f"from:{handle} -is:retweet lang:en"
        headers = {"Authorization": f"Bearer {self.bearer_token}"}
        params = {"query": query, "max_results": min(limit, 10), "tweet.fields": "created_at,public_metrics"}
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                res = client.get(url, headers=headers, params=params)
                if res.status_code == 401:
                    raise RuntimeError(f"X API bearer token invalid for @{handle} (401)")
                res.raise_for_status()
                data = res.json()
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"X API fetch failed for @{handle}: {exc}")
            raise
        items = []
        for t in (data.get("data") or []):
            created = t.get("created_at", "")
            published_ms = _parse_twitter_time(created)
            text = (t.get("text") or "").strip()
            items.append({
                "source": f"X@{handle}",
                "title": text[:280],
                "summary": text[:2000],
                "url": f"https://x.com/{handle}/status/{t['id']}",
                "category": "social",
                "impact": 0.3,
                "collector": self.id,
                "collectorType": self.collector_type,
                "handle": handle,
                "time": published_ms,
                "raw": True,
            })
        return items

    def _nitter_rss(self, handle, limit):
        import feedparser

        hosts = [self.nitter_host] + [h for h in self.nitter_fallback_hosts if h and h != self.nitter_host]
        last_error = None
        for host in hosts:
            url = f"https://{host}/{handle}/rss"
            try:
                # Fetch with a real network timeout via httpx, then parse the
                # body string. (Newer feedparser versions dropped the `timeout`
                # kwarg, and a plain parse(url) call would hang forever on a
                # dead instance.)
                with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
                    res = client.get(url)
                    res.raise_for_status()
                    body = res.text
                parsed = feedparser.parse(body)
                entries = (parsed.get("entries") or [])[:limit]
                if entries:
                    items = []
                    for entry in entries:
                        published = entry.get("published_parsed")
                        published_ms = int(time.mktime(published)) * 1000 if published else int(time.time() * 1000)
                        title = (entry.get("title") or "").strip()
                        items.append({
                            "source": f"X@{handle}",
                            "title": title[:280],
                            "summary": title[:2000],
                            "url": entry.get("link"),
                            "category": "social",
                            "impact": 0.3,
                            "collector": self.id,
                            "collectorType": self.collector_type,
                            "handle": handle,
                            "time": published_ms,
                            "raw": True,
                        })
                    return items
                last_error = f"{host}: empty feed"
            except Exception as exc:  # noqa: BLE001
                last_error = f"{host}: {exc}"
                logger.warn(f"Nitter RSS fetch failed for @{handle} via {host}: {exc}")
        if last_error:
            raise RuntimeError(f"all Nitter hosts failed for @{handle} ({last_error})")
        return []


def _parse_twitter_time(iso_str):
    try:
        from datetime import datetime, timezone

        return int(datetime.fromisoformat(iso_str.replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError):
        return int(time.time() * 1000)


def register(config=None):
    return XTwitterRealtimeCollector(config or {})

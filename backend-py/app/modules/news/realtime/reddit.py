"""Dedicated Reddit sentiment collector (public RSS + optional PRAW).

Default mode uses Reddit's public RSS feeds (no API key required) for the
configured subreddits (e.g. ``r/Forex``, ``r/wallstreetbets``, ``r/economy``).
When ``REDDIT_CLIENT_ID`` and ``REDDIT_CLIENT_SECRET`` are configured *and* the
``praw`` package is installed, a full Reddit-API path is used instead for richer
post data.

Resilience contract (never crash the pipeline):
  - unreachable feeds/API, timeouts, HTTP errors, rate limits and missing
    optional dependencies are caught and logged; ``collect`` returns ``[]``.
  - no fabricated data: sentiment is left for the downstream AI enrichment
    engine to score, nothing is invented here.
"""
import os
import time

import feedparser

from ....foundation.logger import logger

DEFAULT_SUBREDDITS = ["Forex", "wallstreetbets", "economy"]
USER_AGENT = "ZZ_QuantOS_AI_BOAT/1.0 (+institutional forex sentiment aggregator)"


class RedditRealtimeCollector:
    id = "reddit"
    name = "Reddit (live)"
    collector_type = "reddit"

    def __init__(self, config=None):
        self.config = config or {}

    def _subreddits(self):
        subs = self.config.get("subreddits") or self.config.get("subs") or DEFAULT_SUBREDDITS
        cleaned = []
        for s in subs:
            s = str(s or "").strip()
            if s:
                cleaned.append(s.lstrip("r/"))
        return cleaned

    def _client_credentials(self):
        cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
        secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
        return (cid, secret) if cid and secret else None

    def collect(self, params=None):
        """Return normalized Reddit items or ``[]`` (never raises)."""
        params = params or {}
        limit = int(params.get("limit", 10))
        creds = self._client_credentials()
        if creds:
            items = self._collect_via_praw(creds, limit)
            if items:
                return items
            logger.warn("Reddit PRAW path yielded no items - falling back to public RSS")
        return self._collect_via_rss(limit)

    def _collect_via_rss(self, limit):
        items = []
        for sub in self._subreddits():
            url = f"https://www.reddit.com/r/{sub}/.rss"
            try:
                try:
                    parsed = feedparser.parse(url, agent=USER_AGENT, timeout=15)
                except TypeError:
                    parsed = feedparser.parse(url, agent=USER_AGENT)
                entries = parsed.get("entries") or []
                if parsed.get("bozo", False) and not entries:
                    exc = parsed.get("bozo_exception")
                    logger.warn(f"Reddit RSS parse failed for {url}: {exc}")
                    continue
                for entry in entries[:limit]:
                    published = entry.get("published_parsed") or entry.get("updated_parsed")
                    published_ms = int(time.mktime(published)) * 1000 if published else int(time.time() * 1000)
                    items.append({
                        "source": self.config.get("sourceName") or f"r/{sub}",
                        "title": (entry.get("title") or "").strip()[:400],
                        "summary": (entry.get("summary") or "")[:2000],
                        "url": entry.get("link"),
                        "category": "social",
                        "impact": 0.3,
                        "collector": self.id,
                        "collectorType": self.collector_type,
                        "time": published_ms,
                        "raw": True,
                    })
            except Exception as exc:  # noqa: BLE001 - network errors must not crash polling
                logger.warn(f"Reddit RSS fetch failed for {url}: {exc}")
        return [i for i in items if i["title"]]

    def _collect_via_praw(self, creds, limit):
        try:
            import praw
        except ImportError:
            logger.warn("Reddit PRAW configured but 'praw' package is not installed - using RSS")
            return []
        cid, secret = creds
        items = []
        try:
            reddit = praw.Reddit(
                client_id=cid,
                client_secret=secret,
                user_agent=USER_AGENT,
                check_for_async=False,
            )
        except Exception as exc:  # noqa: BLE001 - bad credentials must not crash
            logger.warn(f"Reddit PRAW client init failed: {exc}")
            return []
        for sub in self._subreddits():
            try:
                subreddit = reddit.subreddit(sub)
                for post in subreddit.hot(limit=limit):
                    title = (getattr(post, "title", "") or "").strip()
                    if not title:
                        continue
                    permalink = getattr(post, "permalink", "") or ""
                    items.append({
                        "source": f"r/{getattr(subreddit, 'display_name', sub) or sub}",
                        "title": title[:400],
                        "summary": (getattr(post, "selftext", "") or "")[:2000],
                        "url": f"https://www.reddit.com{permalink}" if permalink else getattr(post, "url", ""),
                        "category": "social",
                        "impact": 0.3,
                        "collector": self.id,
                        "collectorType": self.collector_type,
                        "time": int(float(getattr(post, "created_utc", time.time())) * 1000),
                        "raw": True,
                    })
            except Exception as exc:  # noqa: BLE001 - one bad subreddit must not stop the rest
                logger.warn(f"Reddit PRAW fetch failed for r/{sub}: {exc}")
        return items


def register(config=None):
    return RedditRealtimeCollector(config or {})

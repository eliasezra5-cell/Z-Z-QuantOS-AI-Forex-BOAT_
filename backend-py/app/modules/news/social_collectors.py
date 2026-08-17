"""Social Sentiment Collectors (Feature 2, additive).

Polls a public sentiment/social endpoint (StockTwits-compatible) per symbol and
normalizes every message into the same item shape ``news/collectors.py`` already
produces for news items, so the existing news intelligence pipeline can ingest
and enrich them.

Resilience contract (never crash the pipeline):
  - network errors, timeouts, HTTP 4xx/5xx and rate limits (429) are caught;
    a failed poll returns ``[]`` and logs a warning.
  - The collector is disabled by default (``SOCIAL_STOCKTWITS_ENABLED``) and
    uses no hardcoded secrets; the token is read from user-facing env config.
"""
import time

import httpx

from ...config import settings
from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from .collectors import NewsCollector

COLLECTOR_TYPES = {
    "social": "Social Sentiment",
}

SENTIMENT_LABEL_TO_SIGN = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}


def _normalize_message(msg, symbol):
    """Map a social API message into the normalized news-item shape."""
    created = msg.get("created_at")
    ts = int(time.time() * 1000)
    if created:
        try:
            ts = int(time.mktime(time.strptime(created, "%Y-%m-%dT%H:%M:%SZ"))) * 1000
        except (ValueError, OverflowError, OSError):
            ts = int(time.time() * 1000)
    body = (msg.get("body") or "").strip()
    label = (msg.get("sentiment") or {}).get("basic")
    sentiment = SENTIMENT_LABEL_TO_SIGN.get(label, 0.0) if label is not None else 0.0
    return {
        "source": "StockTwits",
        "title": body[:240] or f"[social] {symbol}",
        "category": "social",
        "impact": 0.2,
        "sentiment": sentiment,
        "collector": "social-stocktwits",
        "collectorType": "social",
        "url": f"https://stocktwits.com/symbol/{symbol}",
        "time": ts,
        "symbol": symbol,
        "raw": True,
    }


class SocialSentimentCollector(NewsCollector):
    """Polls a StockTwits-compatible social endpoint for one symbol."""

    id = "social-stocktwits"
    name = "StockTwits Social Sentiment"
    collector_type = "social"

    def __init__(self, config=None):
        config = config or {
            "enabled": settings.SOCIAL_STOCKTWITS_ENABLED,
            "baseUrl": settings.SOCIAL_STOCKTWITS_BASE_URL,
            "token": settings.SOCIAL_STOCKTWITS_TOKEN,
            "timeout": settings.SOCIAL_POLL_TIMEOUT_SECONDS,
            "limit": settings.SOCIAL_POLL_LIMIT,
        }
        super().__init__(config)
        self.base_url = str(self.config.get("baseUrl") or "").rstrip("/")
        self.token = self.config.get("token") or ""
        self.timeout = float(self.config.get("timeout", 10))
        self.limit = int(self.config.get("limit", 20))
        self._client = httpx.Client(timeout=self.timeout)

    def collect(self, symbol=None):
        """Fetch and normalize social messages for ``symbol`` (e.g. XAUUSD)."""
        symbol = (symbol or "").upper().strip()
        if not symbol:
            return []
        if not self.enabled:
            return []
        if not self.token:
            logger.warn(f"Social collector: no token configured, skipping {symbol}")
            return []
        url = f"{self.base_url}/streams/symbol/{symbol}.json"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        params = {"limit": self.limit, "filter": "top"}
        try:
            resp = self._client.get(url, params=params, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
            logger.warn(f"Social collector: fetch failed for {symbol}: {exc}")
            return []
        if resp.status_code == 429:
            logger.warn(f"Social collector: rate limited for {symbol}")
            return []
        if resp.status_code >= 400:
            logger.warn(f"Social collector: HTTP {resp.status_code} for {symbol}")
            return []
        try:
            data = resp.json()
        except ValueError as exc:
            logger.warn(f"Social collector: invalid JSON for {symbol}: {exc}")
            return []
        messages = (data or {}).get("messages") or []
        if not isinstance(messages, list) or not messages:
            return []
        return [_normalize_message(m, symbol) for m in messages]

    def emit(self, item):
        event_bus.emit("news:ingest", {"payload": item})
        return item


SOCIAL_COLLECTORS = {"social-stocktwits": SocialSentimentCollector}


def collect_social_sentiment(symbol=None, limit=20):
    """Convenience: run all enabled social collectors for a symbol, bounded.

    Never raises. Returns a list of normalized items with a ``sentiment`` field
    in [-1.0, 1.0] (or [] when the source is unreachable / unconfigured).
    """
    items = []
    for coll in SOCIAL_COLLECTORS.values():
        try:
            coll_instance = coll()
            items.extend(coll_instance.collect(symbol))
        except Exception as exc:  # noqa: BLE001 - resilience contract
            logger.warn(f"Social collector '{coll.id}' failed: {exc}")
    return items[: max(0, int(limit))]

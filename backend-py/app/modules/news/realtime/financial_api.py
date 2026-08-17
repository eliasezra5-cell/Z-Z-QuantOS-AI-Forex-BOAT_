"""Real financial news API collector.

Generic client for financial news APIs (e.g. Finnhub, Marketaux, NewsAPI).
Requires ``config.apiKey`` (or ``FINANCIAL_API_KEY`` env) plus
``config.baseUrl`` / ``config.sources``; without a key it returns [] rather
than fabricating headlines.
"""
import os
import time

import httpx

from ....foundation.logger import logger

TIMEOUT_SECONDS = 15


class FinancialApiRealtimeCollector:
    id = "financial_api"
    name = "Financial News API (live)"
    collector_type = "financial_api"

    def __init__(self, config=None):
        self.config = config or {}
        self.api_key = self.config.get("apiKey") or os.environ.get("FINANCIAL_API_KEY", "")
        self.base_url = self.config.get("baseUrl") or os.environ.get("FINANCIAL_API_BASE_URL", "")
        self.sources = self.config.get("sources") or []

    def collect(self, params=None):
        if not self.api_key or not self.base_url:
            logger.warn("Financial API collector not configured (apiKey/baseUrl missing)")
            return []
        url = self.base_url.rstrip("/") + "/news"
        query = {"token": self.api_key}
        if self.sources:
            query["sources"] = ",".join(self.sources)
        query.setdefault("minId", 0)
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                res = client.get(url, params=query)
                res.raise_for_status()
                data = res.json()
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"Financial API fetch failed: {exc}")
            return []
        articles = data.get("data") or data.get("articles") or (data if isinstance(data, list) else [])
        items = []
        for article in articles[: (params or {}).get("limit", 20)]:
            ts = article.get("datetime") or article.get("publishedAt") or article.get("time")
            published_ms = _parse_time(ts)
            title = (article.get("headline") or article.get("title") or "").strip()
            if not title:
                continue
            items.append({
                "source": article.get("source") or article.get("sourceName") or "Financial API",
                "title": title[:400],
                "summary": (article.get("summary") or article.get("description") or "")[:2000],
                "url": article.get("url"),
                "category": "macro",
                "impact": 0.5,
                "collector": self.id,
                "collectorType": self.collector_type,
                "time": published_ms,
                "raw": True,
            })
        return items


def _parse_time(ts):
    if isinstance(ts, (int, float)):
        return int(ts) if ts > 1e12 else int(ts * 1000)
    try:
        from datetime import datetime, timezone

        return int(datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError):
        return int(time.time() * 1000)


def register(config=None):
    return FinancialApiRealtimeCollector(config or {})

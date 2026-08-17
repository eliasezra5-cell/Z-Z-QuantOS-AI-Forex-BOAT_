"""Per-endpoint API analytics.

Records method/path/status/latency into the JSON store collection
`api_analytics` and keeps in-memory counters so `summary()` can answer "top
endpoints by calls and error rate" without scanning the store on every call.
"""
import time
from collections import defaultdict

from .json_store import db
from .logger import logger

ANALYTICS_MAX_ROWS = 5000


class ApiAnalytics:
    def __init__(self):
        self.col = db.collection("api_analytics")
        self._counts = defaultdict(int)
        self._latency = defaultdict(float)
        self._statuses = defaultdict(lambda: defaultdict(int))

    def _key(self, method, path):
        return f"{method} {path}"

    def record(self, method, path, status, latency_ms):
        method = (method or "GET").upper()
        key = self._key(method, path)
        self._counts[key] += 1
        self._latency[key] += float(latency_ms or 0)
        self._statuses[key][str(int(status))] += 1
        self.col.insert({
            "timestamp": int(time.time() * 1000),
            "method": method,
            "path": path,
            "status": int(status),
            "latencyMs": float(latency_ms or 0),
        })
        if self.col.count() > ANALYTICS_MAX_ROWS:
            oldest = self.col.find({}, {"sort": ["timestamp", "asc"]})[:1000]
            for row in oldest:
                self.col.remove(row["id"])

    def summary(self, limit=20):
        endpoints = []
        for key, calls in self._counts.items():
            method, path = key.split(" ", 1)
            statuses = dict(self._statuses[key])
            errors = sum(v for k, v in statuses.items() if int(k) >= 400)
            avg_latency = self._latency[key] / calls if calls else 0
            endpoints.append({
                "method": method,
                "path": path,
                "calls": calls,
                "avgLatencyMs": round(avg_latency, 2),
                "errorRate": round(errors / calls, 4) if calls else 0,
                "errors": errors,
                "statuses": statuses,
            })
        endpoints.sort(key=lambda e: e["calls"], reverse=True)
        return {
            "generatedAt": int(time.time() * 1000),
            "totalCalls": sum(e["calls"] for e in endpoints),
            "endpoints": endpoints[:limit],
        }


api_analytics = ApiAnalytics()


def init_api_analytics():
    logger.info("API analytics foundation initialized")
    return api_analytics

"""Rate limiter mirroring the Node foundation rateLimit.js."""
import threading
import time

from ..config import settings


class RateLimiter:
    def __init__(self):
        self.buckets = {}
        self._lock = threading.Lock()
        self.window_ms = settings.RATE_LIMIT_WINDOW_MS
        self.max = settings.RATE_LIMIT_MAX

    def _cleanup(self, now):
        if len(self.buckets) > 10000:
            expired = [k for k, b in self.buckets.items() if now - b["windowStart"] >= self.window_ms]
            for k in expired:
                self.buckets.pop(k, None)

    def check(self, key):
        now = int(time.time() * 1000)
        with self._lock:
            self._cleanup(now)
            bucket = self.buckets.get(key)
            if not bucket or now - bucket["windowStart"] >= self.window_ms:
                bucket = {"windowStart": now, "count": 0}
                self.buckets[key] = bucket
            bucket["count"] += 1
            return {
                "allowed": bucket["count"] <= self.max,
                "remaining": max(0, self.max - bucket["count"]),
                "resetAt": bucket["windowStart"] + self.window_ms,
            }

    def snapshot(self):
        return {"windowMs": self.window_ms, "max": self.max, "trackedKeys": len(self.buckets)}


rate_limiter = RateLimiter()

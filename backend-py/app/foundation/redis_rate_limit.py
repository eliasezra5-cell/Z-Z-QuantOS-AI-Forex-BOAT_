"""Redis sliding-window rate limiting (additive Module 3.3).

Implements a true sliding-window rate limiter backed by Redis sorted sets
(ZADD on a timestamp score, ZREMRANGEBYSCORE to prune, ZCARD to count). When
Redis is not reachable (no REDIS_URL / import failure / connection error) the
limiter degrades to an in-memory sliding window so the API never hard-fails —
while still enforcing per-endpoint, per-user and per-IP limits in-process.

Keys: ``rl:{prefix}:{entity}:{bucket}``.
"""
import os
import threading
import time

from ..config import settings


def _now_ms():
    return int(time.time() * 1000)


class RedisSlidingWindowLimiter:
    def __init__(self, url=None, window_ms=None, max_requests=None, key_prefix="quantos:rl"):
        self.url = (url or settings.REDIS_URL or os.environ.get("REDIS_URL", "")).strip()
        self.window_ms = int(window_ms or settings.RATE_LIMIT_WINDOW_MS)
        self.max_requests = int(max_requests or settings.RATE_LIMIT_MAX)
        self.key_prefix = key_prefix
        self._redis = None
        self._lock = threading.Lock()
        self._mem = {}
        self.backend = "memory"
        self.last_error = None

    # ------------------------------------------------------------------ #
    # Redis connection
    # ------------------------------------------------------------------ #
    def _connect(self):
        if self._redis is not None:
            return self._redis
        if not self.url:
            self.backend = "memory"
            return None
        try:
            import redis as redis_py  # lazily imported; redis-py is optional
            self._redis = redis_py.Redis.from_url(self.url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True)
            self._redis.ping()
            self.backend = "redis"
        except Exception as err:  # noqa: BLE001 - fall back to memory
            self._redis = None
            self.backend = "memory"
            self.last_error = str(err)
        return self._redis

    # ------------------------------------------------------------------ #
    # Sliding window
    # ------------------------------------------------------------------ #
    def check(self, entity, limit=None, window_ms=None):
        """Check one request against the sliding window.

        ``entity`` is the rate-limit bucket key (e.g. ``ip:1.2.3.4``,
        ``user:<id>``, ``endpoint:/api/orders``). Returns a result dict.
        """
        client = self._connect()
        limit = int(limit or self.max_requests)
        window_ms = int(window_ms or self.window_ms)
        key = f"{self.key_prefix}:{entity}"
        now = _now_ms()

        if client is not None:
            try:
                return self._redis_check(client, key, now, limit, window_ms)
            except Exception as err:  # noqa: BLE001 - fall back to memory
                self.last_error = str(err)

        return self._memory_check(key, now, limit, window_ms)

    def _redis_check(self, client, key, now, limit, window_ms):
        window_start = now - window_ms
        with client.pipeline() as pipe:
            pipe.zremrangebyscore(key, "-inf", window_start)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, max(1, window_ms // 1000) + 1)
            _, _, count, _ = pipe.execute()
        return {
            "allowed": int(count) <= limit,
            "count": int(count),
            "remaining": max(0, limit - int(count)),
            "resetAt": now + window_ms,
            "backend": "redis",
            "windowMs": window_ms,
            "limit": limit,
        }

    def _memory_check(self, key, now, limit, window_ms):
        window_start = now - window_ms
        with self._lock:
            if len(self._mem) > 20000:
                self._prune(now, window_ms)
            timestamps = [t for t in self._mem.get(key, []) if t > window_start]
            timestamps.append(now)
            self._mem[key] = timestamps
            count = len(timestamps)
        return {
            "allowed": count <= limit,
            "count": count,
            "remaining": max(0, limit - count),
            "resetAt": now + window_ms,
            "backend": "memory",
            "windowMs": window_ms,
            "limit": limit,
        }

    def _prune(self, now, window_ms):
        window_start = now - window_ms
        expired = [k for k, v in self._mem.items() if not any(t > window_start for t in v)]
        for k in expired:
            self._mem.pop(k, None)

    def reset(self, entity=None):
        if entity:
            self._mem.pop(f"{self.key_prefix}:{entity}", None)
            if self._redis is not None:
                try:
                    self._redis.delete(f"{self.key_prefix}:{entity}")
                except Exception:  # noqa: BLE001
                    pass
            return
        self._mem.clear()
        if self._redis is not None:
            try:
                for key in self._redis.scan_iter(match=f"{self.key_prefix}:*"):
                    self._redis.delete(key)
            except Exception:  # noqa: BLE001
                pass

    def snapshot(self):
        return {
            "backend": self.backend,
            "windowMs": self.window_ms,
            "max": self.max_requests,
            "memoryKeys": len(self._mem),
            "lastError": self.last_error,
        }


redis_limiter = RedisSlidingWindowLimiter()

# Tiered limits keyed by endpoint path pattern (fnmatch). More sensitive
# endpoints get stricter budgets regardless of the default RATE_LIMIT_MAX.
RATE_LIMIT_TIERS = [
    ("/api/auth/login", 10, 60000),
    ("/api/auth/*", 20, 60000),
    ("/api/orders/*", 30, 60000),
    ("/api/trades/*", 30, 60000),
    ("/api/ai/*", 60, 60000),
    ("/api/integrations/*", 30, 60000),
    ("/api/admin/*", 20, 60000),
    ("/api/health", 600, 60000),
]


def rate_limit_tier(path):
    """Resolve the (limit, window_ms) tier for an endpoint path."""
    for pattern, limit, window_ms in RATE_LIMIT_TIERS:
        if _fnmatch(path, pattern):
            return int(limit), int(window_ms)
    return None, None


def rate_limit_key(request):
    """Build an entity key for a FastAPI request: endpoint + user/IP."""
    user = getattr(request.state, "user", None)
    identity = user.get("id") if isinstance(user, dict) else None
    ip = request.client.host if request.client else "unknown"
    bucket = f"ip:{ip}" if not identity else f"user:{identity}"
    return f"endpoint:{request.url.path}::{bucket}"


def check_request_limits(request, limiter=None):
    """Enforce per-endpoint + per-IP + per-user sliding-window buckets.

    A request is allowed only if every applicable bucket is within its tier
    limit. The response carries the strictest bucket's remaining/limit.
    """
    limiter = limiter or redis_limiter
    user = getattr(request.state, "user", None)
    identity = user.get("id") if isinstance(user, dict) else None
    ip = request.client.host if request.client else "unknown"
    path = request.url.path
    limit, window_ms = rate_limit_tier(path)
    if limit is None:
        limit = limiter.max_requests
        window_ms = limiter.window_ms

    results = []
    results.append(limiter.check(f"ip:{ip}:{path}", limit=limit, window_ms=window_ms))
    if identity:
        results.append(limiter.check(f"user:{identity}:{path}", limit=limit, window_ms=window_ms))
    results.append(limiter.check(f"endpoint:{path}", limit=limit, window_ms=window_ms))

    allowed = all(r["allowed"] for r in results)
    strictest = min(results, key=lambda r: r["remaining"])
    return {
        "allowed": allowed,
        "count": max(r["count"] for r in results),
        "remaining": strictest["remaining"],
        "resetAt": max(r["resetAt"] for r in results),
        "limit": strictest["limit"],
        "backend": results[0]["backend"],
        "buckets": results,
    }


def _fnmatch(name, pattern):
    import fnmatch
    return fnmatch.fnmatch(name, pattern)


def init_redis_rate_limit():
    global redis_limiter
    redis_limiter._connect()
    return redis_limiter

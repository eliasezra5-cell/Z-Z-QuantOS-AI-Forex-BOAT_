"""Cache layer: Redis-backed with graceful in-memory fallback.

Mirrors the Node foundation cache.js contract (``get``/``set``/``has``/
``del_key``/``flush``/``stats`` with millisecond TTLs) while adding a Redis
back end. When Redis is configured and reachable, entries are written to both
Redis and an in-memory mirror; if Redis is down or unconfigured the cache
transparently falls back to the in-memory mirror so callers (e.g. the
Connections Manager 60s TTL cache) never break.
"""
import json
import os
import threading
import time

TTL_DEFAULT = 60 * 1000


class MemoryCache:
    def __init__(self):
        self._lock = threading.Lock()
        self.store = {}

    def get(self, key):
        with self._lock:
            entry = self.store.get(key)
            if not entry:
                return None
            if entry["expiresAt"] < int(time.time() * 1000):
                del self.store[key]
                return None
            return entry["value"]

    def set(self, key, value, ttl_ms=TTL_DEFAULT):
        with self._lock:
            self.store[key] = {"value": value, "expiresAt": int(time.time() * 1000) + ttl_ms}

    def has(self, key):
        return self.get(key) is not None

    def del_key(self, key):
        with self._lock:
            self.store.pop(key, None)

    def flush(self):
        with self._lock:
            self.store.clear()

    def stats(self):
        with self._lock:
            return {"entries": len(self.store)}


class RedisBackedCache:
    """Dual-layer cache: Redis primary, in-memory mirror as fallback.

    Values are JSON-serialized for Redis and always written to the in-memory
    mirror as well, so a Redis outage degrades to the mirror (same TTLs) with
    no data loss and no caller-visible errors.
    """

    def __init__(self, url=""):
        self._memory = MemoryCache()
        self._url = (url or os.environ.get("REDIS_URL", "")).strip()
        self._redis = None
        self._checked = False
        self._lock = threading.Lock()
        self.last_error = None

    # ------------------------------------------------------------------ #
    # Connection management (lazy, best-effort)
    # ------------------------------------------------------------------ #
    @property
    def available(self):
        return self._redis is not None

    def _connect(self):
        """Return the Redis client or None (fall back to memory)."""
        if self._redis is not None:
            return self._redis
        if not self._url:
            self.last_error = "REDIS_URL not configured"
            return None
        if self._checked:
            return None
        try:
            import redis  # noqa: F401 - lazily imported; redis-py is optional
        except ImportError:
            self._checked = True
            self.last_error = "redis package not installed"
            return None
        with self._lock:
            if self._redis is None and not self._checked:
                try:
                    client = redis.Redis.from_url(self._url, socket_connect_timeout=2, socket_timeout=3, decode_responses=True)
                    client.ping()
                    self._redis = client
                    self.last_error = None
                except Exception as exc:  # noqa: BLE001 - connectivity failure is normal
                    self._redis = None
                    self._checked = True
                    self.last_error = str(exc)
        return self._redis

    def _disable(self, exc):
        """Drop the Redis client after a transient failure; memory mirror takes over."""
        self._redis = None
        self.last_error = str(exc)

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #
    @staticmethod
    def _serialize(value):
        return json.dumps(value, default=str)

    @staticmethod
    def _deserialize(raw):
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------ #
    # Cache contract (same API as MemoryCache)
    # ------------------------------------------------------------------ #
    def get(self, key):
        client = self._connect()
        if client is not None:
            try:
                raw = client.get(key)
                if raw is not None:
                    value = self._deserialize(raw)
                    if value is not None:
                        return value
            except Exception as exc:  # noqa: BLE001 - fall back to memory mirror
                self._disable(exc)
        return self._memory.get(key)

    def set(self, key, value, ttl_ms=TTL_DEFAULT):
        self._memory.set(key, value, ttl_ms)
        client = self._connect()
        if client is not None:
            try:
                client.set(key, self._serialize(value), px=max(int(ttl_ms), 1))
            except Exception as exc:  # noqa: BLE001 - memory mirror already holds the value
                self._disable(exc)

    def has(self, key):
        return self.get(key) is not None

    def del_key(self, key):
        self._memory.del_key(key)
        client = self._connect()
        if client is not None:
            try:
                client.delete(key)
            except Exception as exc:  # noqa: BLE001 - memory mirror already cleared
                self._disable(exc)

    def flush(self):
        self._memory.flush()
        client = self._connect()
        if client is not None:
            try:
                client.flushdb()
            except Exception as exc:  # noqa: BLE001 - memory mirror already cleared
                self._disable(exc)

    def stats(self):
        return {
            "entries": len(self._memory.store),
            "redisAvailable": self.available,
            "redisUrlConfigured": bool(self._url),
            "lastError": self.last_error,
        }


cache = RedisBackedCache()


def init_cache():
    from .logger import logger

    cache._connect()
    logger.info(f"Cache initialized (redis_available={cache.available})")
    return cache


def memoize(fn, key_fn=None, ttl_ms=TTL_DEFAULT):
    import asyncio

    def make_key(args, kwargs):
        if key_fn:
            return key_fn(*args, **kwargs)
        return json.dumps([args, kwargs], default=str)

    async def wrapped_async(*args, **kwargs):
        key = make_key(args, kwargs)
        hit = cache.get(key)
        if hit is not None:
            return hit
        result = await fn(*args, **kwargs)
        cache.set(key, result, ttl_ms)
        return result

    def wrapped_sync(*args, **kwargs):
        key = make_key(args, kwargs)
        hit = cache.get(key)
        if hit is not None:
            return hit
        result = fn(*args, **kwargs)
        cache.set(key, result, ttl_ms)
        return result

    if asyncio.iscoroutinefunction(fn):
        return wrapped_async
    return wrapped_sync

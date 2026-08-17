"""Redis Pub/Sub publisher for frontend live channels (additive module).

The prompt mandates that processed news be pushed to Redis Pub/Sub channel
``ws_news`` so the frontend News Terminal receives it. This module publishes
to Redis when available and degrades gracefully to the local event bus (which
the existing WebSocket hub already relays to the ``news`` channel) otherwise.
"""
import json
import os
import threading
import time

from ..config import settings
from .event_bus import event_bus
from .logger import logger


class RedisPubSub:
    def __init__(self, url=None):
        self.url = (url or settings.REDIS_URL or os.environ.get("REDIS_URL", "")).strip()
        self._redis = None
        self._lock = threading.Lock()
        self.available = False
        self.last_error = None

    def _connect(self):
        if self._redis is not None:
            return self._redis
        if not self.url:
            self.available = False
            self.last_error = "REDIS_URL not configured"
            return None
        try:
            import redis  # noqa: F401 - lazily imported; redis-py is optional
        except ImportError:
            self.available = False
            self.last_error = "redis package not installed"
            return None
        with self._lock:
            if self._redis is None:
                try:
                    client = redis.Redis.from_url(self.url, socket_connect_timeout=2, socket_timeout=3, decode_responses=True)
                    client.ping()
                    self._redis = client
                    self.available = True
                    self.last_error = None
                except Exception as exc:  # noqa: BLE001 - connectivity failure is normal
                    self._redis = None
                    self.available = False
                    self.last_error = str(exc)
        return self._redis

    def publish(self, channel, payload, meta=None):
        """Publish a payload to a Redis Pub/Sub channel; also emit locally."""
        payload = payload or {}
        meta = meta or {}
        message = {
            "payload": payload,
            "meta": meta,
            "timestamp": int(time.time() * 1000),
        }
        # Always deliver locally so the WebSocket hub relays it to frontends.
        event_bus.emit(f"{channel}:message", payload, meta)
        client = self._connect()
        if client is None:
            return {"published": False, "local": True, "reason": self.last_error}
        try:
            client.publish(channel, json.dumps(message))
            return {"published": True, "local": True, "channel": channel}
        except Exception as exc:  # noqa: BLE001 - transient failure; still delivered locally
            self.available = False
            self._redis = None
            self.last_error = str(exc)
            return {"published": False, "local": True, "reason": str(exc)}

    def status(self):
        return {
            "available": self.available,
            "urlConfigured": bool(self.url),
            "lastError": self.last_error,
        }


redis_pubsub = RedisPubSub()


def init_redis_pubsub():
    redis_pubsub._connect()
    logger.info(f"Redis pub/sub initialized (available={redis_pubsub.available})")
    return redis_pubsub

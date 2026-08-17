"""Distributed Event Bus — Redis Streams + outbox/inbox (additive module).

Extends the in-process ``EventBus`` with cross-process distribution while
leaving the existing bus untouched:

  - ``publish(topic, payload, meta)``: persists the event to a durable outbox
    (``event_outbox``), delivers it locally *immediately* (identical behaviour
    to today), and — when Redis is connected — relays it to a Redis Stream.
  - a consumer group reads new stream entries into a durable inbox
    (``event_inbox``) and dispatches remote events to the local ``event_bus``
    handlers so every process sees every event.
  - a bounded dedup set (keyed by ``event_id``) prevents a node from handling
    its own relayed events twice.

Graceful degradation: if Redis is not configured (``REDIS_URL`` empty) or
unreachable, the bus reports itself unavailable but ``publish`` still works
(local + durable outbox). Nothing else in the system changes.
"""
import json
import os
import threading
import time
import uuid
from contextlib import suppress

from ..config import settings
from .event_bus import event_bus
from .json_store import db
from .logger import logger

STREAM_NAME = "quantos:events"
CONSUMER_GROUP = "quantos-consumers"
OUTBOX_COLLECTION = "event_outbox"
INBOX_COLLECTION = "event_inbox"
RELAY_BATCH = 100


class DedupSet:
    """Bounded set of recently seen event ids (thread-safe)."""

    def __init__(self, max_size=5000):
        self._ids = set()
        self._order = []
        self._max = int(max_size)
        self._lock = threading.Lock()

    def add(self, event_id):
        with self._lock:
            if event_id in self._ids:
                return False
            self._ids.add(event_id)
            self._order.append(event_id)
            if len(self._order) > self._max:
                self._ids.discard(self._order.pop(0))
            return True

    def contains(self, event_id):
        with self._lock:
            return event_id in self._ids


class DistributedEventBus:
    def __init__(self, url=None, stream=STREAM_NAME, group=CONSUMER_GROUP):
        self.url = (url or settings.REDIS_URL or os.environ.get("REDIS_URL", "")).strip()
        self.stream = stream
        self.group = group
        self._redis = None
        self._redis_lock = threading.Lock()
        self.available = False
        self.last_error = None
        self.relay_running = False
        self.consume_running = False
        self.relay_thread = None
        self.consume_thread = None
        self.outbox = db.collection(OUTBOX_COLLECTION)
        self.inbox = db.collection(INBOX_COLLECTION)
        self.dedup = DedupSet()
        self.stats = {
            "published": 0,
            "relayed": 0,
            "relayFailed": 0,
            "consumed": 0,
            "skipped": 0,
        }
        self.last_relay = None
        self.last_consume = None

    # ---- connection ------------------------------------------------------ #
    def _connect(self):
        """Return a live redis client or None (never raises)."""
        if self._redis is not None:
            return self._redis
        if not self.url:
            self.available = False
            self.last_error = "REDIS_URL not configured"
            return None
        try:
            import redis  # noqa: F401 - imported lazily so redis-py is optional
        except ImportError:
            self.available = False
            self.last_error = "redis package not installed"
            return None
        with self._redis_lock:
            if self._redis is None:
                try:
                    client = redis.Redis.from_url(
                        self.url,
                        socket_connect_timeout=2,
                        socket_timeout=3,
                        decode_responses=True,
                    )
                    client.ping()
                    self._redis = client
                    self.available = True
                    self.last_error = None
                except Exception as exc:  # noqa: BLE001 - connectivity failure is normal
                    self._redis = None
                    self.available = False
                    self.last_error = str(exc)
        return self._redis

    # ---- publish ---------------------------------------------------------- #
    def publish(self, topic, payload=None, meta=None):
        """Persist to outbox, deliver locally, and return the event dict."""
        payload = payload or {}
        meta = meta or {}
        event = {
            "event_id": f"evt-{uuid.uuid4().hex[:16]}",
            "topic": topic,
            "payload": payload,
            "meta": meta,
            "timestamp": int(time.time() * 1000),
        }
        row = self.outbox.insert({
            "event_id": event["event_id"],
            "topic": topic,
            "payload": payload,
            "meta": meta,
            "timestamp": event["timestamp"],
            "status": "PENDING",
            "sentAt": None,
        })
        event["outbox_id"] = row["id"]
        # Mark as locally delivered so the consumer does not re-dispatch it.
        self.dedup.add(event["event_id"])
        event_bus.emit(topic, payload, meta)
        self.stats["published"] += 1
        return event

    # ---- relay (outbox -> redis stream) ----------------------------------- #
    def _relay_once(self):
        client = self._connect()
        if client is None:
            return 0
        pending = self.outbox.find({"status": "PENDING"})[:RELAY_BATCH]
        relayed = 0
        for row in pending:
            try:
                client.xadd(self.stream, {
                    "event_id": row["event_id"],
                    "topic": row["topic"],
                    "payload": json.dumps(row["payload"] or {}),
                    "meta": json.dumps(row["meta"] or {}),
                    "timestamp": str(row["timestamp"]),
                })
            except Exception as exc:  # noqa: BLE001 - connection drop; retry next cycle
                self.stats["relayFailed"] += 1
                self.last_error = str(exc)
                self.available = False
                self._redis = None
                break
            self.outbox.update(row["id"], {"status": "SENT", "sentAt": int(time.time() * 1000)})
            self.stats["relayed"] += 1
            relayed += 1
        self.last_relay = int(time.time() * 1000)
        return relayed

    # ---- consume (redis stream -> inbox -> local dispatch) ----------------- #
    def _consume_once(self):
        client = self._connect()
        if client is None:
            return 0
        with suppress(Exception):
            client.xgroup_create(self.stream, self.group, id="$", mkstream=True)
        try:
            entries = client.xreadgroup(
                self.group,
                f"node-{os.getpid()}-{threading.get_ident()}",
                {self.stream: ">"},
                count=50,
                block=1000,
            )
        except Exception as exc:  # noqa: BLE001 - transient stream error
            self.last_error = str(exc)
            return 0
        consumed = 0
        streams = entries.items() if isinstance(entries, dict) else (entries or [])
        for _stream, messages in streams:
            items = messages.items() if isinstance(messages, dict) else (messages or [])
            for message_id, fields in items:
                event_id = fields.get("event_id") or f"remote-{message_id}"
                if not self.dedup.add(event_id):
                    # Already handled locally (self-published); ack and move on.
                    self.stats["skipped"] += 1
                    with suppress(Exception):
                        client.xack(self.stream, self.group, message_id)
                    continue
                topic = fields.get("topic") or "system:event"
                payload = self._safe_json(fields.get("payload"))
                meta = self._safe_json(fields.get("meta"))
                self.inbox.insert({
                    "event_id": event_id,
                    "topic": topic,
                    "payload": payload,
                    "meta": meta,
                    "message_id": message_id,
                    "receivedAt": int(time.time() * 1000),
                })
                event_bus.emit(topic, payload, meta)
                self.stats["consumed"] += 1
                consumed += 1
                with suppress(Exception):
                    client.xack(self.stream, self.group, message_id)
        self.last_consume = int(time.time() * 1000)
        return consumed

    @staticmethod
    def _safe_json(raw):
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    # ---- loops ------------------------------------------------------------- #
    def _relay_loop(self):
        while self.relay_running:
            try:
                self._relay_once()
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
            time.sleep(1.0)

    def _consume_loop(self):
        while self.consume_running:
            try:
                self._consume_once()
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
            time.sleep(0.2)

    def start(self):
        client = self._connect()
        if client is None:
            logger.warn(f"Distributed event bus disabled: {self.last_error}")
            return self
        self.relay_running = True
        self.consume_running = True
        self.relay_thread = threading.Thread(target=self._relay_loop, daemon=True)
        self.consume_thread = threading.Thread(target=self._consume_loop, daemon=True)
        self.relay_thread.start()
        self.consume_thread.start()
        logger.info(f"Distributed event bus connected to {self.url} (stream {self.stream})")
        return self

    def stop(self):
        self.relay_running = False
        self.consume_running = False
        if self.relay_thread:
            self.relay_thread.join(timeout=1.0)
        if self.consume_thread:
            self.consume_thread.join(timeout=1.0)

    def status(self):
        return {
            "available": self.available,
            "stream": self.stream,
            "consumerGroup": self.group,
            "urlConfigured": bool(self.url),
            "lastError": self.last_error,
            "lastRelay": self.last_relay,
            "lastConsume": self.last_consume,
            "stats": dict(self.stats),
            "outboxPending": len(self.outbox.find({"status": "PENDING"})),
            "outboxTotal": self.outbox.count(),
            "inboxTotal": self.inbox.count(),
        }


distributed_event_bus = DistributedEventBus()


def init_distributed_event_bus():
    distributed_event_bus.start()
    return distributed_event_bus

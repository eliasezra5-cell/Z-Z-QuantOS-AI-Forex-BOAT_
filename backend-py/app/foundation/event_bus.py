"""In-process event bus mirroring the Node foundation eventBus.js."""
import threading
import time

from .logger import logger

HISTORY_LIMIT = 5000


class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._subs = {}  # topic -> list[callable]
        self._any = []  # wildcard handlers

    def emit(self, topic, payload=None, meta=None):
        payload = payload or {}
        meta = meta or {}
        event = {"topic": topic, "payload": payload, "timestamp": int(time.time() * 1000), "meta": meta}
        with self._lock:
            handlers = list(self._subs.get(topic, []))
            any_handlers = list(self._any)
        for h in handlers:
            try:
                h(event)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Event handler failed on {topic}", {"error": str(e)})
        for h in any_handlers:
            try:
                h(event)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Wildcard handler failed on {topic}", {"error": str(e)})

    def on(self, topic, handler):
        with self._lock:
            self._subs.setdefault(topic, []).append(handler)

        def off():
            with self._lock:
                if handler in self._subs.get(topic, []):
                    self._subs[topic].remove(handler)

        return off

    def on_any(self, handler):
        with self._lock:
            self._any.append(handler)

        def off():
            with self._lock:
                if handler in self._any:
                    self._any.remove(handler)

        return off

    def once(self, topic, handler):
        def wrapped(event):
            self.off(topic, wrapped)
            handler(event)

        self.on(topic, wrapped)


event_bus = EventBus()

event_history = []


def track_events():
    event_bus.on_any(lambda e: _push_history(e))


def _push_history(event):
    global event_history
    event_history.append(event)
    if len(event_history) > HISTORY_LIMIT:
        event_history = event_history[-HISTORY_LIMIT:]


def get_event_history(topic=None, limit=200):
    lst = [e for e in event_history if e["topic"] == topic] if topic else event_history
    return lst[-limit:]


def init_events():
    track_events()
    logger.info("Event bus initialized")

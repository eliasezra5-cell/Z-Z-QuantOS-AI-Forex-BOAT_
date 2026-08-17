"""Unit tests for the distributed event bus (outbox/inbox + Redis Streams).

Redis is mocked; no server is required. Graceful degradation (no Redis
configured) is also verified.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ebus_test")

import pytest  # noqa: E402

from app.foundation.distributed_event_bus import (  # noqa: E402
    DedupSet,
    DistributedEventBus,
)
from app.foundation.event_bus import event_bus  # noqa: E402
from app.foundation.json_store import db  # noqa: E402


class FakeRedis:
    """In-memory redis stand-in with only the methods the bus uses."""

    def __init__(self):
        self.stream = {}
        self.added = []
        self.acked = []
        self.group_created = []
        self.xadd_raises = False

    def ping(self):
        return True

    def xadd(self, name, fields, id="*"):
        if self.xadd_raises:
            raise RuntimeError("connection lost")
        self.added.append((name, fields))
        msg_id = f"1-{len(self.added)}"
        self.stream.setdefault(name, {})[msg_id] = fields
        return msg_id

    def xgroup_create(self, name, group, id="$", mkstream=False):
        self.group_created.append((name, group))
        return True

    def xreadgroup(self, group, consumer, streams, count=None, block=None):
        stream_name = next(iter(streams))
        start = streams[stream_name]
        pending = [m for m in self.stream.get(stream_name, {}).items() if start == ">" or m[0] > start]
        return [[stream_name, pending[: count or 50]]]

    def xack(self, name, group, *ids):
        self.acked.extend(ids)
        return len(ids)


@pytest.fixture(autouse=True)
def clean_store():
    for name in ("event_outbox", "event_inbox"):
        db.collection(name).clear()
    yield


def _fresh(url=""):
    bus = DistributedEventBus(url=url)
    bus.dedup = DedupSet()
    bus.stats = {k: 0 for k in ("published", "relayed", "relayFailed", "consumed", "skipped")}
    return bus


# --------------------------------------------------------------------------- #
# Graceful degradation
# --------------------------------------------------------------------------- #
def test_disabled_when_no_redis_configured():
    bus = _fresh(url="")
    bus.start()
    assert bus.available is False
    assert bus.relay_thread is None
    assert bus.consume_thread is None


def test_publish_still_works_when_disabled():
    received = []
    off = event_bus.on("test:event", lambda e: received.append(e))
    bus = _fresh(url="")
    event = bus.publish("test:event", {"a": 1}, {"src": "unit"})
    assert event["event_id"]
    assert len(received) == 1
    pending = bus.outbox.find({"status": "PENDING"})
    assert len(pending) == 1
    assert pending[0]["event_id"] == event["event_id"]
    off()


def test_start_with_bad_url_is_disabled():
    bus = _fresh(url="redis://127.0.0.1:9/0")  # nothing listens on port 9
    bus.start()
    assert bus.available is False
    assert bus.last_error


# --------------------------------------------------------------------------- #
# Outbox relay
# --------------------------------------------------------------------------- #
def test_relay_marks_rows_sent():
    bus = _fresh()
    fake = FakeRedis()
    bus._redis = fake
    bus.available = True
    e1 = bus.publish("t1", {"x": 1})
    bus.publish("t2", {"y": 2})
    assert bus._relay_once() == 2
    assert len(fake.added) == 2
    assert fake.added[0][0] == bus.stream
    assert json.loads(fake.added[0][1]["payload"]) == {"x": 1}
    assert bus.outbox.find({"status": "SENT"})[0]["event_id"] == e1["event_id"]
    assert bus.stats["relayed"] == 2


def test_relay_stops_on_connection_error():
    bus = _fresh()
    fake = FakeRedis()
    fake.xadd_raises = True
    bus._redis = fake
    bus.available = True
    bus.publish("t1", {})
    assert bus._relay_once() == 0
    assert bus.available is False
    assert bus._redis is None
    assert bus.outbox.find({"status": "PENDING"})  # stays pending for retry


# --------------------------------------------------------------------------- #
# Consumer + dedup
# --------------------------------------------------------------------------- #
def test_consume_dispatches_remote_event_to_subscribers():
    received = []
    off = event_bus.on("remote:event", lambda e: received.append(e))
    bus = _fresh()
    fake = FakeRedis()
    bus._redis = fake
    bus.available = True
    remote_id = "evt-remote123"
    fake.xadd(bus.stream, {"event_id": remote_id, "topic": "remote:event", "payload": json.dumps({"p": 1}), "meta": json.dumps({})})
    assert bus._consume_once() == 1
    assert len(received) == 1
    assert bus.inbox.find({"event_id": remote_id})
    assert "1-1" in fake.acked
    off()


def test_consume_skips_self_published_event():
    bus = _fresh()
    fake = FakeRedis()
    bus._redis = fake
    bus.available = True
    bus.publish("self:event", {})
    # The event was already locally delivered; relay to stream, then consume.
    bus._relay_once()
    assert bus._consume_once() == 0
    assert bus.stats["skipped"] == 1
    assert "1-1" in fake.acked


def test_consume_handles_dict_form_entries():
    bus = _fresh()
    fake = FakeRedis()
    bus._redis = fake
    bus.available = True
    fake.xadd(bus.stream, {"event_id": "evt-d1", "topic": "dict:event", "payload": json.dumps({}), "meta": json.dumps({})})
    received = []
    off = event_bus.on("dict:event", lambda e: received.append(e))
    # Force dict-form response.
    original = fake.xreadgroup
    fake.xreadgroup = lambda *a, **kw: {bus.stream: dict(original(*a, **kw)[0][1])}
    assert bus._consume_once() == 1
    assert len(received) == 1
    off()


# --------------------------------------------------------------------------- #
# Dedup set
# --------------------------------------------------------------------------- #
def test_dedup_set_bounded_and_unique():
    d = DedupSet(max_size=3)
    assert d.add("a") is True
    assert d.add("a") is False
    assert d.add("b") is True
    assert d.add("c") is True
    assert d.add("d") is True  # evicts "a"
    assert d.contains("b") is True
    assert d.contains("a") is False


# --------------------------------------------------------------------------- #
# Publish returns event with outbox id
# --------------------------------------------------------------------------- #
def test_publish_returns_outbox_id():
    bus = _fresh()
    event = bus.publish("audit:event", {"n": 5})
    assert event["outbox_id"]
    assert bus.outbox.find_one({"event_id": event["event_id"]})["id"] == event["outbox_id"]

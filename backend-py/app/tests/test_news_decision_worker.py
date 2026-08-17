"""Regression tests for the single background news-decision worker.

Guards the fix that replaced the old thread-per-event spawning in
``init_decision_pipeline``: a burst of ``news:processed`` events must never
create more than one worker thread (previously each event spawned a daemon
thread running a full 5-agent decision cycle, serializing on the internal
``threading.Lock`` and starving the HTTP request path).
"""
import threading
import time
from unittest import mock

import app.modules.ai.decision_pipeline as dp
from app.modules.ai.decision_pipeline import NewsDecisionWorker, decision_pipeline
from app.foundation.event_bus import event_bus

WORKER_THREAD_NAME = "news-decision-worker"

_initialized = {"done": False}


def _count_worker_threads():
    return sum(1 for t in threading.enumerate() if t.name == WORKER_THREAD_NAME)


class _FakeAnalyze:
    """Async stand-in for ``DecisionPipeline.analyze``.

    Signals ``started`` when the worker begins processing and blocks on
    ``release`` so tests can hold the worker "busy" while firing more events.
    """

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self._lock = threading.Lock()

    async def __call__(self, symbol="XAUUSD", context=None, persist=True):
        with self._lock:
            self.calls += 1
        self.started.set()
        self.release.wait(10)
        return {"direction": "no_trade", "status": "no_trade", "symbol": symbol}


def test_burst_of_events_uses_single_worker_thread():
    fake = _FakeAnalyze()
    worker = NewsDecisionWorker(max_pending=1)
    baseline = _count_worker_threads()
    worker.start()
    try:
        with mock.patch.object(decision_pipeline, "analyze", new=fake):
            # Burst of back-to-back events with tiny gaps, as in production.
            for i in range(25):
                worker.enqueue({"i": i})
                if i % 5 == 0:
                    time.sleep(0.02)
            assert fake.started.wait(5), "worker did not start processing events"

            before = _count_worker_threads()
            assert before == baseline + 1, f"expected 1 new worker thread, got {before - baseline}"
            assert worker.worker_thread is not None
            assert worker.worker_thread.name == WORKER_THREAD_NAME

            # Worker is busy: more events must coalesce, never spawn threads.
            for i in range(25, 50):
                worker.enqueue({"i": i})
            time.sleep(0.2)

            during = _count_worker_threads()
            assert during == baseline + 1, f"worker thread count grew: {during - baseline}"
            assert worker.pending <= 1, f"pending queue unbounded: {worker.pending}"

            fake.release.set()
            time.sleep(0.3)
            # Coalesced: at most the in-flight decision + one latest pending.
            assert fake.calls <= 3, f"expected coalesced analyze calls, got {fake.calls}"
    finally:
        fake.release.set()


def test_init_pipeline_wires_news_events_to_single_worker():
    fake = _FakeAnalyze()
    worker = NewsDecisionWorker(max_pending=1)
    baseline = _count_worker_threads()

    if not _initialized["done"]:
        with mock.patch.object(dp, "news_decision_worker", worker), mock.patch.object(
            decision_pipeline, "analyze", new=fake
        ):
            dp.init_decision_pipeline()
            for i in range(12):
                event_bus.emit("news:processed", {"item": {"id": f"evt-{i}"}})
            assert fake.started.wait(5), "news events were not processed"
            assert worker.worker_thread is not None
            assert worker.worker_thread.name == WORKER_THREAD_NAME
            assert _count_worker_threads() == baseline + 1
            for i in range(12, 24):
                event_bus.emit("news:processed", {"item": {"id": f"evt-{i}"}})
            time.sleep(0.2)
            assert _count_worker_threads() == baseline + 1, "event burst created extra threads"
            assert worker.pending <= 1
            fake.release.set()
        _initialized["done"] = True

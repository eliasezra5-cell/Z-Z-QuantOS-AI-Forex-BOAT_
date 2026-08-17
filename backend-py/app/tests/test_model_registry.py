"""Tests for Phase 3 (Batch 21): model registry approval workflow, promotion, rollback and drift monitoring."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_phase3_test")

from app.foundation.json_store import db  # noqa: E402
from app.modules.ai.learning import learning_engine  # noqa: E402
from app.modules.ai.model_registry import APPROVED, CHAMPION, PENDING, REJECTED, model_registry  # noqa: E402


def _reset():
    db.collection("model_registry").clear()
    db.collection("learning_log").clear()
    db.collection("challenger_state").clear()
    db.collection("ai_model_state").clear()
    m = learning_engine.model.insert({
        "version": 1,
        "weights": {"trend": 1.0, "indicators": 1.0, "patterns": 1.0, "smc": 1.0, "news": 1.0, "macro": 1.0},
        "trainedAt": 1,
        "sampleCount": 0,
    })
    return m["id"]


def test_register_creates_pending_model():
    _reset()
    doc = model_registry.register("candidate-a", {"author": "test"}, {"trend": 1.1})
    assert doc["status"] == PENDING
    assert doc["version"] == 1
    assert model_registry.get(doc["id"])["status"] == PENDING


def test_approval_workflow():
    _reset()
    doc = model_registry.register("candidate-a")
    model_registry.approve(doc["id"], reviewer="alice")
    assert model_registry.get(doc["id"])["status"] == APPROVED
    assert model_registry.get(doc["id"])["approvedBy"] == "alice"
    model_registry.reject(doc["id"], reason="bad weights")
    assert model_registry.get(doc["id"])["status"] == REJECTED
    assert model_registry.get(doc["id"])["rejectionReason"] == "bad weights"


def test_promote_requires_approval():
    _reset()
    doc = model_registry.register("candidate-a", weights={"trend": 1.5})
    res = model_registry.promote(doc["id"])
    assert res["ok"] is False
    assert res["error"] == "model-not-approved"


def test_promote_approved_model_updates_champion():
    _reset()
    doc = model_registry.register("candidate-a", weights={"trend": 1.5, "indicators": 1.0, "patterns": 1.0, "smc": 1.0, "news": 1.0, "macro": 1.0})
    model_registry.approve(doc["id"])
    res = model_registry.promote(doc["id"])
    assert res["ok"] is True
    m = learning_engine.model.find_one({})
    assert m["weights"]["trend"] == 1.5
    assert m["version"] == 2
    assert model_registry.get(doc["id"])["status"] == CHAMPION


def test_rollback_restores_previous_weights():
    _reset()
    doc = model_registry.register("candidate-a", weights={"trend": 1.5, "indicators": 1.0, "patterns": 1.0, "smc": 1.0, "news": 1.0, "macro": 1.0})
    model_registry.approve(doc["id"])
    model_registry.promote(doc["id"])
    res = model_registry.rollback(doc["id"])
    assert res["ok"] is True
    m = learning_engine.model.find_one({})
    assert m["weights"]["trend"] == 1.0


def test_drift_report_empty_state():
    _reset()
    report = model_registry.drift_report()
    assert report["driftLevel"] == "low"
    assert report["reason"] == "no-outcomes"


def test_drift_report_low_on_stable():
    _reset()
    for i in range(30):
        learning_engine.record_outcome(
            {"symbol": "XAUUSD", "consensus": {"direction": "buy"}, "confidence": {"score": 0.8}},
            {"profit": 1 if i % 2 == 0 else -1},
        )
    report = model_registry.drift_report(window=10)
    assert report["windowSampleCount"] == 10
    assert report["driftLevel"] in ("low", "medium", "high")


def test_get_state_counts():
    _reset()
    model_registry.register("a")
    model_registry.register("b")
    state = model_registry.get_state()
    assert state["pendingCount"] == 2

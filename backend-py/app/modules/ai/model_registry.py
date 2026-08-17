"""Model registry: versioned model governance with approval workflow, promotion, rollback and drift monitoring.

Batch 21 governance layer: every candidate model is registered, must be
approved before it can be promoted to champion, and is continuously checked
for concept/data drift against its historical baseline.
"""
import time
import uuid

from ...foundation.logger import logger
from ...foundation.json_store import db
from .memory import ai_memory

APPROVED = "approved"
PENDING = "pending"
REJECTED = "rejected"
CHAMPION = "champion"

DRIFT_LOW = "low"
DRIFT_MEDIUM = "medium"
DRIFT_HIGH = "high"


class ModelRegistry:
    def __init__(self):
        self.col = db.collection("model_registry")

    # ---- lifecycle ----
    def register(self, name, metadata=None, weights=None):
        """Register a new candidate model version (status: pending)."""
        version = self.col.count() + 1
        doc = self.col.insert({
            "id": str(uuid.uuid4()),
            "name": name,
            "version": version,
            "status": PENDING,
            "metadata": metadata or {},
            "weights": weights or {},
            "registeredAt": int(time.time() * 1000),
            "approvalHistory": [],
        })
        logger.info(f"Model registry: registered {name} v{version} (pending approval)")
        return doc

    def list_models(self, status=None):
        rows = self.col.find({})
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return sorted(rows, key=lambda r: r.get("registeredAt", 0), reverse=True)

    def get(self, model_id):
        return self.col.find_one({"id": model_id})

    def _set_status(self, model_id, status):
        doc = self.get(model_id)
        if not doc:
            return None
        now = int(time.time() * 1000)
        history = list(doc.get("approvalHistory") or [])
        history.append({"status": status, "at": now})
        updated = self.col.update(doc["id"], {
            "status": status,
            "reviewedAt": now,
            "approvalHistory": history,
        })
        return updated

    def approve(self, model_id, reviewer="system"):
        """Approve a pending candidate so it becomes promotable."""
        updated = self._set_status(model_id, APPROVED)
        if updated:
            self.col.update(model_id, {"approvedBy": reviewer})
            logger.info(f"Model registry: approved {model_id} by {reviewer}")
        return updated

    def reject(self, model_id, reason="", reviewer="system"):
        """Reject a candidate; it can never be promoted."""
        updated = self._set_status(model_id, REJECTED)
        if updated:
            self.col.update(model_id, {"rejectionReason": reason, "rejectedBy": reviewer})
        return updated

    def promote(self, model_id):
        """Promote an APPROVED model to champion, replacing the live weights/version."""
        from .learning import learning_engine

        doc = self.get(model_id)
        if not doc:
            return {"ok": False, "error": "model-not-found"}
        if doc.get("status") != APPROVED:
            return {"ok": False, "error": "model-not-approved"}

        m = learning_engine.model.find_one({})
        previous = {
            "version": m.get("version"),
            "weights": m.get("weights"),
            "sampleCount": m.get("sampleCount"),
            "previousWeights": m.get("weights"),
        }
        learning_engine.model.update(m["id"], {
            "version": m.get("version", 0) + 1,
            "weights": doc.get("weights") or m.get("weights"),
            "trainedAt": int(time.time() * 1000),
            "sampleCount": m.get("sampleCount", 0),
            "promotedFromRegistry": True,
            "previousWeights": previous["weights"],
        })
        self.col.update(model_id, {"status": CHAMPION, "promotedAt": int(time.time() * 1000)})
        ai_memory.remember("last-promotion", {"modelId": model_id, "at": int(time.time() * 1000)})
        logger.info(f"Model registry: promoted {model_id} to champion")
        return {"ok": True, "model": self.get(model_id)}

    def rollback(self, model_id=None):
        """Roll the champion back to the previous weights snapshot (model_id = candidate to demote, optional)."""
        from .learning import learning_engine

        m = learning_engine.model.find_one({})
        previous = m.get("previousWeights")
        if previous is None:
            return {"ok": False, "error": "no-previous-weights"}
        learning_engine.model.update(m["id"], {
            "version": m.get("version", 0) + 1,
            "weights": previous,
            "trainedAt": int(time.time() * 1000),
            "previousWeights": None,
            "promotedFromRegistry": False,
        })
        if model_id:
            self.col.update(model_id, {"status": APPROVED})
        logger.info("Model registry: rolled back champion to previous weights")
        return {"ok": True}

    # ---- drift monitoring ----
    def drift_report(self, window=20, baseline_days=30, threshold_low=0.03, threshold_high=0.08):
        """Concept drift: compare the recent window win rate to the cumulative baseline.

        Drift is flagged low/medium/high depending on how far the recent window
        win rate has fallen (or risen) relative to the baseline, with a minimum
        sample guard so tiny windows are not over-triggered.
        """
        from .learning import learning_engine

        logs = sorted(learning_engine.col.find({}), key=lambda l: l["timestamp"])
        total = len(logs)
        if total == 0:
            return {"driftLevel": DRIFT_LOW, "reason": "no-outcomes", "baselineWinRate": 0.0, "windowWinRate": None, "windowSampleCount": 0, "totalOutcomes": 0}

        recent = logs[-window:]
        baseline = logs[:-window]
        recent_wins = sum(1 for l in recent if l.get("win"))
        base_wins = sum(1 for l in baseline if l.get("win"))

        base_rate = round(base_wins / len(baseline) * 100) / 100 if baseline else round(recent_wins / len(recent) * 100) / 100
        recent_rate = round(recent_wins / len(recent) * 100) / 100 if recent else 0.0
        delta = round(recent_rate - base_rate, 4)

        if len(recent) < 5:
            level = DRIFT_LOW
            reason = "insufficient-recent-samples"
        elif abs(delta) > threshold_high:
            level = DRIFT_HIGH
            reason = "major-win-rate-shift"
        elif abs(delta) > threshold_low:
            level = DRIFT_MEDIUM
            reason = "moderate-win-rate-shift"
        else:
            level = DRIFT_LOW
            reason = "stable"

        report = {
            "driftLevel": level,
            "reason": reason,
            "baselineWinRate": base_rate,
            "windowWinRate": recent_rate,
            "delta": delta,
            "windowSampleCount": len(recent),
            "baselineSampleCount": len(baseline),
            "totalOutcomes": total,
            "evaluatedAt": int(time.time() * 1000),
        }
        if level == DRIFT_HIGH:
            ai_memory.remember("drift-alert", report)
        return report

    def get_state(self):
        return {
            "models": self.list_models(),
            "pendingCount": len(self.list_models(status=PENDING)),
            "approvedCount": len(self.list_models(status=APPROVED)),
            "drift": self.drift_report(),
        }


model_registry = ModelRegistry()


def init_model_registry():
    logger.info("Model registry initialized")
    return model_registry

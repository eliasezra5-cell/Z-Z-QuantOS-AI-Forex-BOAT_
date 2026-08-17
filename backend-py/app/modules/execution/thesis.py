"""Trade Thesis Versioning + Opposite-News Close Logic (Batch 13).

Every open trade stores: original thesis, current thesis, thesis version,
supporting/contradicting news IDs, technical snapshot, risk snapshot, model
versions, market regime, expected move distribution, invalidation conditions.
Every re-analysis creates a new immutable thesis version.

Opposite-news action engine: HOLD / TIGHTEN_STOP / MOVE_TO_BREAK_EVEN /
REDUCE_POSITION / PARTIAL_CLOSE / CLOSE / REVERSE. REVERSE is gated by
confirmed close + cooldown + full re-validation + new risk approval.

Hysteresis prevents flip-flopping: min action interval, contradiction
persistence window, repeated confirmation, post-close cooldown, max reversals.
"""
import time
import uuid

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db


class ThesisManager:
    def __init__(self):
        self.col = db.collection("trade_theses")
        self.hyst_col = db.collection("action_hysteresis")

    # ---- Create / version ----
    def create_thesis(self, position_id, thesis):
        doc = {
            "id": str(uuid.uuid4()),
            "position_id": position_id,
            "thesis_version": 1,
            "original": thesis,
            "current": thesis,
            "supporting_news_ids": thesis.get("supportingNewsIds") or [],
            "contradicting_news_ids": thesis.get("contradictingNewsIds") or [],
            "technical_snapshot": thesis.get("technicalSnapshot") or {},
            "risk_snapshot": thesis.get("riskSnapshot") or {},
            "model_versions": thesis.get("modelVersions") or {},
            "market_regime": thesis.get("marketRegime"),
            "expected_move": thesis.get("expectedMove") or {},
            "invalidation_conditions": thesis.get("invalidationConditions") or [],
            "history": [{"version": 1, "thesis": thesis, "at": int(time.time() * 1000), "reason": "initial"}],
            "createdAt": int(time.time() * 1000),
        }
        self.col.insert(doc)
        return doc

    def get_thesis(self, position_id):
        return self.col.find_one({"position_id": position_id})

    def new_version(self, position_id, patch, reason):
        doc = self.get_thesis(position_id)
        if not doc:
            return self.create_thesis(position_id, patch)
        new_thesis = {**doc["current"], **patch}
        new_version = doc["thesis_version"] + 1
        doc["history"].append({"version": new_version, "thesis": new_thesis, "at": int(time.time() * 1000), "reason": reason})
        if patch.get("contradictingNewsIds"):
            doc["contradicting_news_ids"] = list(dict.fromkeys(doc.get("contradicting_news_ids") + patch["contradictingNewsIds"]))
        if patch.get("supportingNewsIds"):
            doc["supporting_news_ids"] = list(dict.fromkeys(doc.get("supporting_news_ids") + patch["supportingNewsIds"]))
        updated = self.col.update(doc["id"], {
            "current": new_thesis,
            "thesis_version": new_version,
            "history": doc["history"],
            "contradicting_news_ids": doc.get("contradicting_news_ids"),
            "supporting_news_ids": doc.get("supporting_news_ids"),
            "updatedAt": int(time.time() * 1000),
        })
        event_bus.emit("thesis:versioned", {"position_id": position_id, "version": new_version, "reason": reason})
        return updated

    def get_history(self, position_id):
        doc = self.get_thesis(position_id)
        return doc.get("history") if doc else []

    def invalidation_violated(self, position_id, current_quote):
        doc = self.get_thesis(position_id)
        if not doc:
            return False
        for cond in doc.get("invalidation_conditions", []):
            price = cond.get("price")
            side = cond.get("side") or "above"
            if price is None:
                continue
            if side == "below" and current_quote < price:
                return True
            if side == "above" and current_quote > price:
                return True
        return False


thesis_manager = ThesisManager()

ACTIONS = ["HOLD", "TIGHTEN_STOP", "MOVE_TO_BREAK_EVEN", "REDUCE_POSITION", "PARTIAL_CLOSE", "CLOSE", "REVERSE"]

# Hysteresis config
HYSTERESIS_CONFIG = {
    "min_action_interval_seconds": 300,
    "contradiction_persistence_window_seconds": 600,
    "repeated_confirmation_required": 2,
    "post_close_cooldown_seconds": 900,
    "max_reversals_per_event": 1,
}


class OppositeNewsEngine:
    def __init__(self):
        self.col = db.collection("opposite_news_actions")

    def _last_action(self, position_id):
        rows = self.col.find({"position_id": position_id})
        return rows[-1] if rows else None

    def _reversal_count(self, position_id):
        rows = self.col.find({"position_id": position_id})
        return len([r for r in rows if r["action"] == "REVERSE"])

    def evaluate(self, position, news, thesis, context=None):
        """Produce an action with hysteresis checks. Returns action + reason."""
        now = int(time.time() * 1000)
        action = "HOLD"
        reason = ""

        # 1. Relevance check
        if not news.get("relevant"):
            return {"action": "HOLD", "reason": "news not relevant to instrument/time horizon"}

        # 2. Contradiction severity
        severity = news.get("contradictionSeverity") or 0.0
        source_authority = news.get("sourceAuthority") or 0.0
        if severity < 0.5:
            return {"action": "HOLD", "reason": f"contradiction severity {severity:.2f} below 0.5"}

        # 3. Hysteresis: min action interval
        last = self._last_action(position["id"])
        if last:
            interval = now - last["timestamp"]
            if interval < HYSTERESIS_CONFIG["min_action_interval_seconds"] * 1000:
                return {"action": last["action"], "reason": "within min action interval (hysteresis)"}

        # 4. Contradiction persistence window (require repeated confirmation)
        persistence = news.get("persistenceSeconds") or 0
        if persistence < HYSTERESIS_CONFIG["contradiction_persistence_window_seconds"]:
            if news.get("confirmationCount", 0) < HYSTERESIS_CONFIG["repeated_confirmation_required"]:
                return {"action": "HOLD", "reason": "contradiction not yet persistent/confirmed (hysteresis)"}

        # 5. Choose action based on severity + P&L + spread/liquidity
        pnl = position.get("profit") or 0
        pnl_pct = context.get("pnlPct") if context else 0
        spread_ok = context.get("spreadOk") if context else True
        liquidity_ok = context.get("liquidityOk") if context else True

        if severity >= 0.9 and source_authority >= 0.7 and spread_ok and liquidity_ok:
            if pnl_pct and pnl_pct > 0.2:
                action = "REVERSE" if self._reversal_count(position["id"]) < HYSTERESIS_CONFIG["max_reversals_per_event"] else "CLOSE"
                reason = f"High severity ({severity:.2f}) authoritative contradiction"
            else:
                action = "CLOSE"
                reason = f"High severity contradiction, not in profit"
        elif severity >= 0.7:
            action = "PARTIAL_CLOSE"
            reason = f"Moderate-high contradiction ({severity:.2f}), reducing exposure"
        elif severity >= 0.6:
            action = "REDUCE_POSITION"
            reason = f"Moderate contradiction ({severity:.2f})"
        elif pnl_pct and pnl_pct > 0.2:
            action = "MOVE_TO_BREAK_EVEN"
            reason = "Contradiction detected while in profit - protect gains"

        self.col.insert({
            "position_id": position["id"],
            "symbol": position.get("symbol"),
            "news_id": news.get("id"),
            "action": action,
            "reason": reason,
            "severity": severity,
            "source_authority": source_authority,
            "timestamp": now,
        })
        event_bus.emit("news:opposite-action", {"position": position, "action": action, "reason": reason})
        return {"action": action, "reason": reason}

    def allow_reverse(self, position_id, thesis, validation_passed, risk_approved):
        """REVERSE only after: confirmed close, cooldown, full validation, risk approval."""
        last = self._last_action(position_id)
        if last and last["action"] != "REVERSE":
            return {"allowed": False, "reason": "no prior reverse"}
        if not thesis:
            return {"allowed": False, "reason": "no thesis"}
        now = int(time.time() * 1000)
        if last and now - last["timestamp"] < HYSTERESIS_CONFIG["post_close_cooldown_seconds"] * 1000:
            return {"allowed": False, "reason": "post-close cooldown active"}
        if not validation_passed:
            return {"allowed": False, "reason": "validation not passed"}
        if not risk_approved:
            return {"allowed": False, "reason": "risk approval missing"}
        return {"allowed": True, "reason": "ok"}

    def recent(self, limit=50):
        rows = self.col.find({})
        return rows[-limit:]


opposite_news_engine = OppositeNewsEngine()


def init_thesis_and_opposite_news():
    logger.info("Thesis manager + opposite-news engine initialized")
    return thesis_manager, opposite_news_engine

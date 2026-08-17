"""Auto Trade Controller (Batch 17 + Core Trading Logic).

Checks in order: mode -> emergency stop -> shield level -> schedule ->
profile constraints -> daily limits -> open trade limits -> confidence
gates -> validation engine -> risk approval -> THEN execute.

Confidence gates (configurable via ``ai/confidence_gates.py``, defaults shown):
  >= 0.90  -> AUTO EXECUTE
  0.70-0.89 -> SUGGESTED TRADE (approval required in SEMI_AUTO)
  < 0.70   -> NO TRADE (logged and discarded)
"""
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...config import settings
from ..risk.capital_protection import capital_protection
from ..validation.engine import validation_engine, OVERALL_SCORE_AUTO_EXECUTE
from .modes import trading_modes, AUTO_EXECUTION_MODES, SUGGEST_MODES


class AutoTradeController:
    def __init__(self):
        self.col = db.collection("suggested_trades")
        self.reanalysis_log = db.collection("trade_reanalysis_log")

    # ---- Suggested trades ----
    def create_suggested_trade(self, decision, expiry_seconds=None):
        confidence = (decision.get("confidence") or {}).get("score", 0)
        expiry = expiry_seconds or settings.SUGGESTED_TRADE_EXPIRY_SECONDS
        row = self.col.insert({
            "symbol": decision["symbol"],
            "side": (decision.get("recommendation") or {}).get("direction"),
            "confidence": confidence,
            "decision_id": decision.get("id"),
            "status": "pending",
            "createdAt": int(time.time() * 1000),
            "expiresAt": int(time.time() * 1000) + expiry * 1000,
            "reasoning": (decision.get("xai") or decision.get("recommendation") or {}).get("rationale"),
        })
        event_bus.emit("suggested:trade-created", {"suggested": row})
        return row

    def approve_suggested(self, trade_id, modify=None):
        row = self.col.find_one({"id": trade_id})
        if not row:
            return None
        if row["status"] != "pending":
            return {"status": "not-pending", "row": row}
        if row.get("expiresAt") and row["expiresAt"] < int(time.time() * 1000):
            self.col.update(trade_id, {"status": "expired"})
            return {"status": "expired"}
        patch = {"status": "accepted", "approvedAt": int(time.time() * 1000)}
        if modify:
            patch["modification"] = modify
        self.col.update(trade_id, patch)
        event_bus.emit("suggested:trade-approved", {"trade_id": trade_id, "modify": modify})
        return self.col.find_one({"id": trade_id})

    def reject_suggested(self, trade_id):
        row = self.col.find_one({"id": trade_id})
        if not row:
            return None
        self.col.update(trade_id, {"status": "rejected", "rejectedAt": int(time.time() * 1000)})
        return self.col.find_one({"id": trade_id})

    def expire_stale_suggestions(self):
        now = int(time.time() * 1000)
        for row in self.col.find({"status": "pending"}):
            if row.get("expiresAt") and row["expiresAt"] < now:
                self.col.update(row["id"], {"status": "expired", "expiredAt": now})

    def suggested_trades(self, status=None):
        self.expire_stale_suggestions()
        rows = self.col.find({})
        if status:
            rows = [r for r in rows if r["status"] == status]
        return rows

    # ---- Pre-trade gate evaluation ----
    def evaluate(self, decision, context=None):
        """Return (verdict, reasons). verdict in {auto-execute, suggest, no-trade, blocked}."""
        context = context or {}
        reasons = []
        confidence = (decision.get("confidence") or {}).get("score", 0)

        # 1. Mode check
        mode = trading_modes.get_mode()
        if mode == "DISABLED":
            return "no-trade", ["auto-trading-disabled"]
        if mode == "EMERGENCY_STOP":
            return "no-trade", ["emergency-stop"]
        if mode == "ANALYSIS_ONLY":
            return "no-trade", ["analysis-only-mode"]

        # 2. Capital protection
        blocked, why = capital_protection.is_blocked()
        if blocked:
            return "no-trade", [f"capital-protection:{why}"]

        # 3. Kill switches / schedule
        blocked_reasons = trading_modes.blocked_reasons()
        if blocked_reasons:
            return "no-trade", blocked_reasons
        if not trading_modes.schedule_allows(decision.get("symbol")):
            return "no-trade", ["outside-schedule"]

        # 4. Profile constraints
        profile = trading_modes.get_profile()
        if confidence < profile.get("min_confidence", 0.80):
            reasons.append(f"below-profile-min-confidence {profile.get('min_confidence')}")
        spread_pips = context.get("spreadPips") or 0
        if spread_pips > profile.get("max_spread_pips", 3.0):
            reasons.append(f"spread {spread_pips:.2f} > profile max {profile.get('max_spread_pips')}")

        # 5. Validation engine (6 checks + hard blockers)
        vres = validation_engine.evaluate(context)
        if vres["hard_blockers"]["blocked"]:
            reasons.append(f"hard-blockers: {vres['hard_blockers']['blockers']}")
        if not vres["can_auto_execute"] and mode in AUTO_EXECUTION_MODES:
            reasons.append(f"validation-score {vres['overall_score']} < {OVERALL_SCORE_AUTO_EXECUTE}")

        # 5b. User-trained preferences ("never trade X" style hard constraints)
        try:
            from ..ai.conversation import preference_blocks

            reasons.extend(preference_blocks(decision.get("symbol")))
        except Exception:  # noqa: BLE001 - preferences must never break the gate
            pass

        # 6. Confidence gates (configurable via the conversational assistant)
        from ..ai.confidence_gates import get_gates

        gates = get_gates()
        auto_thr = gates["auto_execute"]
        suggest_thr = gates["suggest"]
        if confidence >= auto_thr and mode in AUTO_EXECUTION_MODES and not reasons:
            return "auto-execute", []
        if suggest_thr <= confidence < auto_thr:
            return "suggest", reasons
        return "no-trade", reasons + [f"confidence {confidence:.2f} < {suggest_thr:.2f}"]

    # ---- Re-analysis & auto-close ----
    def record_reanalysis(self, position, decision, action, reason):
        self.reanalysis_log.insert({
            "position_id": position.get("id"),
            "symbol": position.get("symbol"),
            "decision": decision,
            "action": action,
            "reason": reason,
            "timestamp": int(time.time() * 1000),
        })

    def evaluate_open_trade(self, position, current_confidence, initial_confidence=None, emergency=False):
        """Auto-close logic: current < 70% of initial -> close; < 50% -> emergency."""
        initial = initial_confidence or position.get("initialConfidence") or current_confidence
        threshold = settings.AUTO_CLOSE_CONFIDENCE_THRESHOLD  # 0.70
        if current_confidence < threshold:
            action = "emergency-close" if current_confidence < settings.EMERGENCY_CLOSE_CONFIDENCE_THRESHOLD else "auto-close"
            reason = f"Confidence degradation below {int(threshold*100)}% threshold (current={current_confidence:.2f}, initial={initial:.2f})"
            if action == "emergency-close":
                event_bus.emit("trading:emergency-close", {"position": position, "confidence": current_confidence, "reason": reason})
            return {"action": action, "reason": reason, "confidence": current_confidence, "initial": initial}
        return {"action": "hold", "confidence": current_confidence, "initial": initial}

    def status(self):
        return {
            "mode": trading_modes.get_mode(),
            "profile": trading_modes.get_profile()["id"],
            "blocked_reasons": trading_modes.blocked_reasons(),
            "capital_shield": capital_protection.get_status()["shield_level"],
            "emergency_stop": capital_protection.get_status()["emergency_stop"],
        }


auto_trade_controller = AutoTradeController()


def init_auto_trade_controller():
    logger.info("Auto trade controller initialized")
    return auto_trade_controller

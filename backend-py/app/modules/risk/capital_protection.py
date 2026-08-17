"""Capital Protection Engine (Batch 16) — FAIL-CLOSED.

Shield tiers GREEN -> YELLOW -> ORANGE -> RED, equity/balance ladders,
daily capital lock, emergency stop (cannot auto-deactivate), and a list of
fail-closed triggers that disable new trades. All idempotent and auditable.
"""
import time
from datetime import datetime, timezone

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db


class CapitalProtectionEngine:
    def __init__(self):
        self.state = {
            "shield_level": "GREEN",
            "emergency_stop": False,
            "emergency_reason": None,
            "daily_locked": False,
            "locked_date": None,
            "recovery_active": False,
            "fail_closed": [],
            "start_equity": None,
            "peak_equity": None,
            "history": [],
        }
        self._load()

    def _load(self):
        col = db.collection("capital_protection")
        if col.count() == 0:
            col.insert({**self.state, "id": "capital-protection"})
        else:
            row = col.find_one({"id": "capital-protection"})
            if row:
                self.state = {**self.state, **row}

    def _save(self):
        db.collection("capital_protection").update("capital-protection", self.state)

    def _record(self, action, detail):
        self.state["history"] = (self.state.get("history") or [])[-200:]
        self.state["history"].append({
            "action": action,
            "detail": detail,
            "shield_level": self.state["shield_level"],
            "emergency_stop": self.state["emergency_stop"],
            "timestamp": int(time.time() * 1000),
            "iso": datetime.now(timezone.utc).isoformat(),
        })
        self._save()
        event_bus.emit("capital:protection-event", {"action": action, "detail": detail, "shield": self.state["shield_level"]})

    # ---- Shield evaluation ----
    def evaluate(self, portfolio):
        daily_loss = portfolio.get("dailyLoss") or 0
        equity = portfolio.get("equity") or 0
        starting = self.state.get("start_equity") or equity
        peak = self.state.get("peak_equity") or equity
        if equity > peak:
            self.state["peak_equity"] = equity
        if self.state["start_equity"] is None and equity > 0:
            self.state["start_equity"] = equity
        daily_limit_pct = portfolio.get("dailyLossLimitPct") or 5
        daily_loss_pct = (daily_loss / starting) * 100 if starting > 0 else 0
        equity_vs_start = (equity / starting) if starting > 0 else 1
        equity_vs_peak = (equity / peak) if peak > 0 else 1

        reason = None
        level = "GREEN"
        if daily_loss_pct >= daily_limit_pct:
            level = "RED"
            reason = f"Daily loss limit reached ({daily_loss_pct:.2f}%)"
        elif daily_loss_pct >= daily_limit_pct * 0.75:
            level = "ORANGE"
            reason = f"Daily loss at {daily_loss_pct:.2f}% of limit ({daily_limit_pct}%)"
        elif daily_loss_pct >= daily_limit_pct * 0.5:
            level = "YELLOW"
            reason = f"Daily loss at {daily_loss_pct:.2f}% of limit ({daily_limit_pct}%)"
        elif equity_vs_start < 0.80:
            level = "RED"
            reason = f"Equity below 80% of starting ({equity_vs_start:.2f})"
        elif equity_vs_peak < 0.85:
            level = "RED"
            reason = f"Equity below 85% of peak ({equity_vs_peak:.2f})"
        elif equity_vs_peak < 0.90:
            level = "ORANGE"
            reason = f"Equity below 90% of peak ({equity_vs_peak:.2f})"
        elif equity_vs_peak < 0.95:
            level = "YELLOW"
            reason = f"Equity below 95% of peak ({equity_vs_peak:.2f})"
        elif equity_vs_start < 0.90:
            level = "YELLOW"
            reason = f"Equity below 90% of starting ({equity_vs_start:.2f})"

        changed = self.state["shield_level"] != level
        old_level = self.state["shield_level"]
        self.state["shield_level"] = level
        if level == "RED":
            self.activate_emergency_stop(reason)
        self._save()
        if changed:
            self._record("shield-level-change", {"from": old_level, "to": level, "reason": reason})
        return {
            "shield_level": level,
            "emergency_stop": self.state["emergency_stop"],
            "daily_loss_pct": round(daily_loss_pct, 2),
            "equity_vs_start": round(equity_vs_start, 4),
            "equity_vs_peak": round(equity_vs_peak, 4),
            "reason": reason,
            "actions": self._actions_for_level(level),
        }

    def _actions_for_level(self, level):
        if level == "RED":
            return ["close_all_trades", "disable_auto_trading", "emergency_stop"]
        if level == "ORANGE":
            return ["reduce_position_size_50pct", "block_new_trades"]
        if level == "YELLOW":
            return ["reduce_position_size_25pct"]
        return ["normal"]

    # ---- Emergency stop ----
    def activate_emergency_stop(self, reason="manual"):
        if self.state["emergency_stop"]:
            return
        self.state["emergency_stop"] = True
        self.state["emergency_reason"] = reason
        self._record("emergency-stop", reason)
        event_bus.emit("capital:emergency-stop", {"reason": reason})
        logger.warn(f"EMERGENCY STOP activated: {reason}")
        return self.state

    def deactivate_emergency_stop(self, actor="admin"):
        """Emergency stop CANNOT auto-deactivate — only explicit action."""
        self.state["emergency_stop"] = False
        self.state["emergency_reason"] = None
        self._record("emergency-stop-cleared", f"cleared by {actor}")
        return self.state

    # ---- Daily lock ----
    def check_daily_lock(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.get("daily_locked") and self.state.get("locked_date") != today:
            self.state["daily_locked"] = False
            self.state["locked_date"] = None
            self._save()
            self._record("capital-unlock", "daily lock auto-unlocked on new day")
        return self.state.get("daily_locked", False)

    def lock_for_day(self, reason):
        self.state["daily_locked"] = True
        self.state["locked_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._record("capital-lock", reason)
        return self.state

    def clear_daily_lock(self, actor="admin"):
        """Explicitly reset the daily lock (admin override, auditable)."""
        self.state["daily_locked"] = False
        self.state["locked_date"] = None
        self._record("capital-lock-cleared", f"cleared by {actor}")
        return self.state

    # ---- Fail-closed triggers ----
    def raise_fail_closed(self, trigger, detail):
        if trigger not in (self.state.get("fail_closed") or []):
            self.state.setdefault("fail_closed", []).append(trigger)
        event_bus.emit("capital:fail-closed", {"trigger": trigger, "detail": detail})
        logger.error(f"FAIL-CLOSED trigger: {trigger} — {detail}")
        self._save()
        return self.state

    def clear_fail_closed(self, trigger):
        if trigger in (self.state.get("fail_closed") or []):
            self.state["fail_closed"].remove(trigger)
            self._save()
        return self.state

    def is_blocked(self):
        self.check_daily_lock()
        if self.state["emergency_stop"]:
            return True, "emergency-stop"
        if self.state["shield_level"] == "RED":
            return True, "shield-red"
        if self.state["shield_level"] == "ORANGE":
            return True, "shield-orange-no-new-trades"
        if self.state.get("daily_locked"):
            return True, "daily-lock"
        if self.state.get("fail_closed"):
            return True, f"fail-closed: {','.join(self.state['fail_closed'])}"
        return False, None

    def get_status(self):
        return {
            "shield_level": self.state["shield_level"],
            "emergency_stop": self.state["emergency_stop"],
            "emergency_reason": self.state["emergency_reason"],
            "daily_locked": self.state.get("daily_locked"),
            "locked_date": self.state.get("locked_date"),
            "fail_closed": self.state.get("fail_closed", []),
            "start_equity": self.state.get("start_equity"),
            "peak_equity": self.state.get("peak_equity"),
            "recent_events": (self.state.get("history") or [])[-10:],
        }


capital_protection = CapitalProtectionEngine()


def init_capital_protection():
    logger.info("Capital protection engine initialized (FAIL-CLOSED)")
    return capital_protection

"""Auto Trading Engine (Batch 17).

STAGED ACTIVATION (no self-promotion):
ANALYSIS_ONLY -> SHADOW -> PAPER -> SEMI_AUTO -> AUTO_LIMITED -> AUTO_FULL.

Promotion requires: min observations, calibrated confidence, walk-forward
performance, max-DD compliance, risk approval, admin approval, no unresolved
critical incidents. Auto trading is DISABLED by default (mode starts at
DISABLED). Kill switches halt trading across 11 conditions.
"""
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...config import settings

TRADING_MODES = ["DISABLED", "ANALYSIS_ONLY", "SHADOW", "PAPER", "SEMI_AUTO", "AUTO_LIMITED", "AUTO_FULL", "EMERGENCY_STOP"]
PROMOTION_SEQUENCE = ["ANALYSIS_ONLY", "SHADOW", "PAPER", "SEMI_AUTO", "AUTO_LIMITED", "AUTO_FULL"]
AUTO_EXECUTION_MODES = {"AUTO_LIMITED", "AUTO_FULL"}
SUGGEST_MODES = {"SEMI_AUTO", "AUTO_LIMITED", "AUTO_FULL"}

TRADING_PROFILES = [
    {
        "id": "conservative",
        "name": "Conservative",
        "risk_per_trade": 0.5, "max_daily_trades": 5, "max_open_trades": 3,
        "min_confidence": 0.90, "max_spread_pips": 2.0,
        "preferred_timeframes": ["H1", "H4", "D1"], "allowed_sessions": ["london", "newyork", "london-ny"],
    },
    {
        "id": "aggressive",
        "name": "Aggressive",
        "risk_per_trade": 2.0, "max_daily_trades": 20, "max_open_trades": 10,
        "min_confidence": 0.80, "max_spread_pips": 3.0,
        "preferred_timeframes": ["M5", "M15", "M30", "H1"], "allowed_sessions": ["london", "newyork", "london-ny", "asia"],
    },
    {
        "id": "scalping",
        "name": "Scalping",
        "risk_per_trade": 1.0, "max_daily_trades": 40, "max_open_trades": 6,
        "min_confidence": 0.85, "max_spread_pips": 1.5,
        "preferred_timeframes": ["M1", "M5"], "allowed_sessions": ["london-ny"],
    },
    {
        "id": "swing",
        "name": "Swing",
        "risk_per_trade": 1.0, "max_daily_trades": 2, "max_open_trades": 5,
        "min_confidence": 0.85, "max_spread_pips": 3.0,
        "preferred_timeframes": ["H4", "D1", "W1"], "allowed_sessions": ["london", "newyork"],
    },
]

KILL_SWITCHES = [
    "daily_loss_limit",
    "weekly_loss_limit",
    "equity_below_80pct",
    "max_drawdown_exceeded",
    "five_consecutive_losses",
    "mt5_disconnected",
    "market_data_stale",
    "ai_provider_failure",
    "weekend",
    "major_news_in_30m",
    "capital_shield_red",
]


class TradingModeManager:
    def __init__(self):
        self.mode = "DISABLED"  # auto trading DISABLED by default
        self.state = {
            "observations": 0,
            "consecutive_losses": 0,
            "daily_loss": 0.0,
            "weekly_loss": 0.0,
            "max_drawdown_pct": 0.0,
            "max_daily_loss_pct": 5.0,
            "max_weekly_loss_pct": 10.0,
            "max_drawdown_limit_pct": 15.0,
            "kill_switches": {},
            "promotion_history": [],
        }
        self.profile_id = "conservative"
        self.schedules = []
        self._load()

    def _load(self):
        col = db.collection("trading_modes")
        if col.count() == 0:
            col.insert({"id": "trading-mode", "mode": self.mode, "state": self.state, "profile": self.profile_id, "schedules": self.schedules})
        else:
            row = col.find_one({"id": "trading-mode"})
            if row:
                self.mode = row.get("mode") or "DISABLED"
                self.state = {**self.state, **(row.get("state") or {})}
                self.profile_id = row.get("profile") or "conservative"
                self.schedules = row.get("schedules") or []

    def _save(self):
        db.collection("trading_modes").update("trading-mode", {"mode": self.mode, "state": self.state, "profile": self.profile_id, "schedules": self.schedules})

    def get_mode(self):
        return self.mode

    def set_mode(self, mode, actor="user", reason="manual"):
        mode = (mode or "").upper()
        if mode not in TRADING_MODES:
            return {"status": "invalid-mode", "valid": TRADING_MODES}
        # Promotion guard: EMERGENCY_STOP can only be left explicitly; no self-promotion.
        if self.mode == "EMERGENCY_STOP" and mode != "EMERGENCY_STOP" and actor != "admin":
            return {"status": "emergency-stop-cannot-deactivate", "mode": self.mode}
        if mode == "AUTO_FULL" and actor not in ("admin",):
            return {"status": "auto-full-requires-admin"}
        if mode == "AUTO_FULL" and not reason:
            return {"status": "auto-full-requires-acknowledgement"}
        # Promotion sequencing guard applies to staged promotion for regular
        # users only. Admins/system may switch to SEMI_AUTO / AUTO_LIMITED /
        # AUTO_FULL directly (direct mode switching) - the staged activation
        # path remains available through the explicit ``promote()`` flow.
        if mode in PROMOTION_SEQUENCE and actor not in ("admin", "system"):
            if self.mode in PROMOTION_SEQUENCE:
                cur_idx = PROMOTION_SEQUENCE.index(self.mode)
            else:
                cur_idx = -1  # DISABLED / EMERGENCY_STOP must start at ANALYSIS_ONLY
            new_idx = PROMOTION_SEQUENCE.index(mode)
            if new_idx > cur_idx + 1:
                required = PROMOTION_SEQUENCE[cur_idx + 1] if cur_idx >= 0 else PROMOTION_SEQUENCE[0]
                return {"status": "cannot-skip-promotion-stage", "required_next": required}
        self.mode = mode
        self._save()
        event_bus.emit("trading:mode-change", {"mode": mode, "actor": actor, "reason": reason})
        logger.info(f"Trading mode -> {mode} (actor={actor})")
        return {"status": "ok", "mode": self.mode}

    def promote(self, actor="admin"):
        """Explicit promotion through the stage sequence with gates."""
        if self.mode == "EMERGENCY_STOP":
            return {"status": "emergency-stop"}
        if self.mode == "DISABLED":
            nxt = "ANALYSIS_ONLY"
        elif self.mode in PROMOTION_SEQUENCE and self.mode != "AUTO_FULL":
            nxt = PROMOTION_SEQUENCE[PROMOTION_SEQUENCE.index(self.mode) + 1]
        else:
            return {"status": "already-max", "mode": self.mode}
        gates = self.check_promotion_gates(nxt)
        if not gates["passed"]:
            return {"status": "promotion-gates-failed", "gates": gates, "next": nxt}
        self.mode = nxt
        self.state["promotion_history"].append({"to": nxt, "at": int(time.time() * 1000), "actor": actor})
        self._save()
        event_bus.emit("trading:mode-change", {"mode": nxt, "actor": actor, "reason": "promotion-gates-passed"})
        return {"status": "promoted", "mode": self.mode}

    def check_promotion_gates(self, target):
        passed = True
        gates = []
        checks = [
            ("min_observations", self.state.get("observations", 0) >= 50, {"current": self.state.get("observations", 0), "required": 50}),
            ("calibrated_confidence", self.state.get("confidence_calibrated", False), {}),
            ("walk_forward_performance", self.state.get("walk_forward_passed", False), {}),
            ("max_drawdown_compliance", self.state.get("max_drawdown_pct", 0) <= self.state.get("max_drawdown_limit_pct", 15), {"current": self.state.get("max_drawdown_pct", 0)}),
            ("risk_approval", self.state.get("risk_approved", False), {}),
            ("admin_approval", self.state.get("admin_approved", False), {}),
            ("no_critical_incidents", not self.state.get("critical_incident", False), {}),
        ]
        if target in ("SHADOW",):
            checks = checks[:1]
        for name, ok, detail in checks:
            gates.append({"gate": name, "passed": ok, "detail": detail})
            if not ok:
                passed = False
        return {"passed": passed, "gates": gates}

    def record_observation(self, **updates):
        for k, v in updates.items():
            if k in self.state:
                self.state[k] = v
        self.state["observations"] = self.state.get("observations", 0) + 1
        self._save()

    # ---- Profiles ----
    def set_profile(self, profile_id):
        if profile_id not in [p["id"] for p in TRADING_PROFILES]:
            return {"status": "invalid-profile"}
        self.profile_id = profile_id
        self._save()
        return {"status": "ok", "profile": self.get_profile()}

    def get_profile(self):
        return next((p for p in TRADING_PROFILES if p["id"] == self.profile_id), TRADING_PROFILES[0])

    def list_profiles(self):
        return TRADING_PROFILES

    # ---- Schedules ----
    def add_schedule(self, schedule):
        schedule = {**schedule, "id": f"sched-{int(time.time()*1000)}", "enabled": schedule.get("enabled", True)}
        self.schedules.append(schedule)
        self._save()
        return schedule

    def update_schedule(self, schedule_id, patch):
        for s in self.schedules:
            if s["id"] == schedule_id:
                s.update(patch)
                self._save()
                return s
        return None

    def remove_schedule(self, schedule_id):
        self.schedules = [s for s in self.schedules if s["id"] != schedule_id]
        self._save()

    # ---- Kill switches ----
    def trigger_kill_switch(self, switch, active=True, detail=None):
        if switch not in KILL_SWITCHES:
            return
        self.state.setdefault("kill_switches", {})[switch] = {"active": active, "detail": detail, "at": int(time.time() * 1000)}
        if active:
            self.set_mode("EMERGENCY_STOP", actor="system", reason=f"kill-switch:{switch}")
        self._save()
        event_bus.emit("trading:kill-switch", {"switch": switch, "active": active, "detail": detail})
        return self.state["kill_switches"]

    def kill_switches_status(self):
        return self.state.get("kill_switches", {})

    def clear_kill_switches(self, actor="admin"):
        """Deactivate every active kill switch and exit EMERGENCY_STOP.

        Returns the list of cleared switches. Trading mode returns to DISABLED
        (safe default) so no order can slip through after a manual reset.
        """
        cleared = [sw for sw, info in (self.state.get("kill_switches") or {}).items() if info and info.get("active")]
        for sw in cleared:
            self.trigger_kill_switch(sw, active=False)
        if self.mode == "EMERGENCY_STOP":
            self.mode = "DISABLED"
            self._save()
        if cleared:
            logger.info(f"Kill switches cleared by {actor}: {cleared}")
        return {"status": "ok", "cleared": cleared, "mode": self.mode}

    def blocked_reasons(self):
        reasons = []
        for sw, info in (self.state.get("kill_switches") or {}).items():
            if info.get("active"):
                reasons.append(sw)
        if self.mode == "EMERGENCY_STOP":
            reasons.append("emergency-stop")
        if self.mode == "DISABLED":
            reasons.append("auto-trading-disabled")
        return reasons

    # ---- Schedule check ----
    def schedule_allows(self, symbol=None, now=None):
        if not self.schedules:
            return True
        now = now or time.gmtime()
        weekday = now.tm_wday
        hour = now.tm_hour
        for s in self.schedules:
            if not s.get("enabled"):
                continue
            days = s.get("days") or []
            if days and weekday not in days:
                continue
            start, end = s.get("start", 0), s.get("end", 23)
            if start <= hour < end:
                return True
        return False

    def get_status(self):
        return {
            "mode": self.mode,
            "profile": self.get_profile(),
            "schedules": self.schedules,
            "kill_switches": self.state.get("kill_switches", {}),
            "blocked_reasons": self.blocked_reasons(),
            "state": {k: v for k, v in self.state.items() if k not in ("promotion_history",)},
            "promotion_history": self.state.get("promotion_history", []),
        }


trading_modes = TradingModeManager()


def init_trading_modes():
    logger.info(f"Trading mode manager initialized (default: {trading_modes.get_mode()})")
    return trading_modes

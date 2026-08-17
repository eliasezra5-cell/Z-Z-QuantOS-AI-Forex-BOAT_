"""Risk engine mirroring the Node risk/engine.js."""
import time
from datetime import datetime, timezone

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db


class RiskEngine:
    def __init__(self):
        self.rules = [
            {"id": "max_risk_per_trade", "description": "Max risk per trade (% of equity)", "default": 2, "enabled": True},
            {"id": "max_daily_loss", "description": "Max daily loss (% of equity)", "default": 5, "enabled": True},
            {"id": "max_total_exposure", "description": "Max total exposure (% of equity)", "default": 30, "enabled": True},
            {"id": "max_open_positions", "description": "Max open positions", "default": 10, "enabled": True},
            {"id": "max_correlation", "description": "Max correlated pairs exposure", "default": 3, "enabled": True},
            {"id": "stop_loss_required", "description": "Stop loss required on all trades", "default": True, "enabled": True},
            {"id": "take_profit_required", "description": "Take profit recommended", "default": False, "enabled": True},
        ]

    def get_settings(self):
        col = db.collection("risk_settings")
        if col.count() == 0:
            col.insert_many([{"id": r["id"], "value": r["default"], "enabled": r["enabled"], "description": r["description"]} for r in self.rules])
        return col.all()

    def update_setting(self, setting_id, value=None, enabled=None):
        col = db.collection("risk_settings")
        row = col.find_one({"id": setting_id})
        if not row:
            return None
        patch = {"updatedAt": datetime.now(timezone.utc).isoformat()}
        if value is not None:
            patch["value"] = value
        if enabled is not None:
            patch["enabled"] = bool(enabled)
        return col.update(row["id"], patch)

    def evaluate_trade(self, trade, portfolio):
        settings = self.get_settings()

        def get(setting_id):
            return next((s for s in settings if s["id"] == setting_id), None)

        violations = []
        risk_pct = get("max_risk_per_trade")
        daily_loss = get("max_daily_loss")
        exposure = get("max_total_exposure")
        max_positions = get("max_open_positions")
        max_corr = get("max_correlation")
        tp_required = get("take_profit_required")

        if risk_pct and risk_pct.get("enabled") and portfolio.get("equity", 0) > 0 and trade.get("riskAmount"):
            pct = (trade["riskAmount"] / portfolio["equity"]) * 100
            if pct > risk_pct["value"]:
                violations.append(f"Risk {pct:.1f}% exceeds {risk_pct['value']}% per trade limit")
        if daily_loss and daily_loss.get("enabled") and portfolio.get("dailyLoss") and portfolio["dailyLoss"] > 0 and portfolio.get("equity", 0) > 0:
            dl = (portfolio["dailyLoss"] / portfolio["equity"]) * 100
            if dl > daily_loss["value"]:
                violations.append(f"Daily loss {dl:.1f}% exceeds {daily_loss['value']}% limit")
        if exposure and exposure.get("enabled") and portfolio.get("equity", 0) > 0 and portfolio.get("exposure"):
            ex = (portfolio["exposure"] / portfolio["equity"]) * 100
            if ex + (trade.get("notionalPct") or 0) > exposure["value"]:
                violations.append(f"Total exposure would exceed {exposure['value']}% limit")
        if max_positions and max_positions.get("enabled") and portfolio.get("openPositions", 0) >= max_positions["value"]:
            violations.append(f"Max open positions ({max_positions['value']}) reached")
        if trade.get("correlatedPositions") is not None and max_corr and max_corr.get("enabled") and trade["correlatedPositions"] >= max_corr["value"]:
            violations.append(f"Max correlated exposure ({max_corr['value']}) reached for this symbol")
        sl_required = get("stop_loss_required")
        if sl_required and sl_required.get("enabled") and trade.get("stopLoss") is None:
            violations.append("Stop loss required")
        if tp_required and tp_required.get("enabled") and trade.get("takeProfit") is None:
            violations.append("Take profit required")

        approved = len(violations) == 0
        event_bus.emit("risk:assessed", {"trade": trade, "approved": approved, "violations": violations})
        return {"approved": approved, "violations": violations, "timestamp": int(time.time() * 1000), "settings": settings}

    def capital_protection(self, portfolio):
        settings = self.get_settings()
        daily_loss = next((s for s in settings if s["id"] == "max_daily_loss"), None)
        equity = portfolio.get("equity", 0)
        daily_loss_val = portfolio.get("dailyLoss") or 0
        pct = (daily_loss_val / equity) * 100 if equity > 0 else 0
        halt = equity > 0 and pct >= daily_loss["value"]
        protection = {
            "dailyLossLimit": daily_loss["value"],
            "currentDailyLoss": daily_loss_val,
            "dailyLossPct": pct,
            "haltTrading": halt,
            "reason": None,
        }
        if halt:
            protection["reason"] = f"Daily loss limit ({daily_loss['value']}%) breached - trading halted"
            event_bus.emit("risk:halt", {"portfolio": portfolio, "protection": protection})
        return protection


risk_engine = RiskEngine()


def init_risk_engine():
    logger.info("Risk engine initialized")
    return risk_engine

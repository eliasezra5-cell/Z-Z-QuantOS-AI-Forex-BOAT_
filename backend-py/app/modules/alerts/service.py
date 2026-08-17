"""Alerts & notifications mirroring the Node alerts/service.js."""
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...foundation.feature_flags import feature_flags

CHANNELS = ["email", "telegram", "whatsapp", "push", "desktop", "mt5", "web"]

DEFAULT_RULES = [
    {"id": "r1", "name": "AI High Confidence Signal", "condition": "ai_decision", "threshold": 0.7, "channels": ["web", "telegram"], "enabled": True},
    {"id": "r2", "name": "Daily Loss Warning", "condition": "daily_loss", "threshold": 3, "channels": ["web", "telegram", "email"], "enabled": True},
    {"id": "r3", "name": "Take Profit Reached", "condition": "take_profit", "threshold": 0, "channels": ["web", "push"], "enabled": True},
    {"id": "r4", "name": "Stop Loss Hit", "condition": "stop_loss", "threshold": 0, "channels": ["web", "push", "mt5"], "enabled": True},
    {"id": "r5", "name": "High Impact News", "condition": "high_impact_news", "threshold": 3, "channels": ["web", "desktop"], "enabled": True},
]


class AlertService:
    def __init__(self):
        self.col = db.collection("alerts")
        self.rules = db.collection("alert_rules")
        if self.rules.count() == 0:
            self.rules.insert_many(DEFAULT_RULES)
        self.alertCount = self.col.count()

    def create(self, alert):
        row = self.col.insert({**alert, "timestamp": int(time.time() * 1000), "read": False, "delivered": {}})
        self.deliver(row)
        return row

    def deliver(self, alert):
        channels = alert.get("channels") or ["web"]
        for ch in channels:
            flag = feature_flags.get(f"alerts.{ch}", True)
            if not flag:
                continue
            self.col.update(alert["id"], {"delivered": {**alert.get("delivered", {}), ch: True}})
            event_bus.emit("alert:delivered", {"alert": alert, "channel": ch})

    def trigger(self, condition, payload):
        rules = self.rules.find({"enabled": True})
        for rule in rules:
            if rule["condition"] == condition and self._matches(rule, payload):
                self.create({
                    "title": payload.get("title") or f"{rule['name']}",
                    "message": payload.get("message"),
                    "type": condition,
                    "severity": payload.get("severity") or "info",
                    "channels": rule["channels"],
                    "symbol": payload.get("symbol"),
                })

    def _matches(self, rule, payload):
        if rule.get("threshold") is None:
            return True
        val = payload.get("value")
        if val is None:
            return True
        return abs(val) >= rule["threshold"]

    def notify(self, subject, message, severity="info", channels=None):
        return self.create({"title": subject, "message": message, "type": "notification", "severity": severity, "channels": channels or ["web", "telegram"]})

    def get_alerts(self, params=None):
        params = params or {}
        alerts = self.col.find({})
        if params.get("type"):
            alerts = [a for a in alerts if a["type"] == params["type"]]
        if params.get("severity"):
            alerts = [a for a in alerts if a["severity"] == params["severity"]]
        if params.get("unread") == "true":
            alerts = [a for a in alerts if not a["read"]]
        return sorted(alerts, key=lambda a: a["timestamp"], reverse=True)[: int(params.get("limit") or 100)]

    def mark_read(self, alert_id):
        return self.col.update(alert_id, {"read": True})

    def get_rules(self):
        return self.rules.find({})

    def add_rule(self, rule):
        return self.rules.insert(rule)

    def stats(self):
        alerts = self.col.find({})
        return {
            "total": len(alerts),
            "unread": len([a for a in alerts if not a["read"]]),
            "bySeverity": {
                "critical": len([a for a in alerts if a["severity"] == "critical"]),
                "warning": len([a for a in alerts if a["severity"] == "warning"]),
                "info": len([a for a in alerts if a["severity"] == "info"]),
            },
        }


alert_service = AlertService()


def init_alerts():
    def _on_ai_decision(event):
        d = event["payload"]["decision"]
        conf = d.get("confidence") or {}
        rec = d.get("recommendation") or {}
        if (conf.get("score") or 0) >= 0.7 and rec.get("action") == "recommend":
            alert_service.trigger("ai_decision", {
                "title": f"High confidence {(d.get('consensus') or {}).get('direction')} signal on {d['symbol']}",
                "message": rec.get("reason"),
                "value": conf.get("score"),
                "symbol": d["symbol"],
                "severity": "info",
            })

    def _on_trade_closed(event):
        p = event["payload"]["position"]
        if p.get("closeReason") == "take-profit":
            alert_service.trigger("take_profit", {"title": f"TP hit: {p['symbol']}", "message": f"Profit {p['profit']}", "symbol": p["symbol"], "severity": "info"})
        if p.get("closeReason") == "stop-loss":
            alert_service.trigger("stop_loss", {"title": f"SL hit: {p['symbol']}", "message": f"Loss {p['profit']}", "symbol": p["symbol"], "severity": "warning"})

    event_bus.on("ai:decision", _on_ai_decision)
    event_bus.on("trade:closed", _on_trade_closed)
    logger.info("Alerts & notifications initialized")
    return alert_service

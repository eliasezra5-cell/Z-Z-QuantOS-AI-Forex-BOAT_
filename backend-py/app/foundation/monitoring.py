"""Monitoring hub mirroring the Node foundation monitoring.js."""
import time

from .json_store import db
from .logger import logger


class MonitoringHub:
    def __init__(self):
        self.col = db.collection("metrics")
        self.health_checks = {}
        self.start_time = int(time.time() * 1000)

    def register_health_check(self, name, fn):
        self.health_checks[name] = fn

    def health(self):
        checks = []
        for name, fn in self.health_checks.items():
            try:
                fn()
                checks.append({"name": name, "status": "up"})
            except Exception as e:  # noqa: BLE001
                checks.append({"name": name, "status": "down", "error": str(e)})
        return {
            "status": "up" if all(c["status"] == "up" for c in checks) else "degraded",
            "uptime": int(time.time() * 1000) - self.start_time,
            "checks": checks,
        }

    def record(self, metric):
        row = {"timestamp": int(time.time() * 1000), **metric}
        self.col.insert(row)
        if self.col.count() > 5000:
            oldest = self.col.find({}, {"sort": ["timestamp", "asc"]})[:1000]
            for r in oldest:
                self.col.remove(r["id"])
        return row

    def query(self, name, opts=None):
        opts = opts or {}
        rows = self.col.find({"name": name})
        since = opts.get("since") or int(time.time() * 1000) - 60 * 60 * 1000
        return [r for r in rows if r["timestamp"] >= since][-(opts.get("limit") or 500):]


monitoring = MonitoringHub()


def init_monitoring():
    logger.info("Monitoring foundation initialized")
    return monitoring

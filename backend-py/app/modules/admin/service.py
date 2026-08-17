"""Admin panel mirroring the Node admin/service.js."""
import os
import time

from ...foundation.logger import logger
from ...foundation.json_store import db
from ...foundation.scheduler import scheduler
from ...foundation.queue import queue_system
from ...foundation.workers import workers
from ...foundation.monitoring import monitoring
from ...foundation.feature_flags import feature_flags
from ..pipeline.manager import list_pipelines
from ..integrations.service import list_integrations


def init_admin():
    logger.info("Admin panel initialized")
    return {
        "getSystemDashboard": get_system_dashboard,
        "getJobs": get_jobs,
        "runJob": run_job,
        "getConfiguration": get_configuration,
        "updateConfiguration": update_configuration,
        "getLogs": get_logs,
        "getHealth": get_health,
    }


def _heap_mb():
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 * 10) / 10
    except Exception:
        return 0


def get_system_dashboard():
    return {
        "health": {"status": "up", "uptime": _uptime()},
        "scheduler": scheduler.status(),
        "queues": queue_system.snapshot(),
        "workers": workers.status(),
        "pipelines": [{"id": p["id"], "name": p["name"], "status": p["status"], "lastRun": p["lastRun"]} for p in list_pipelines()],
        "integrations": [{"id": i["id"], "name": i["name"], "status": i["status"]} for i in list_integrations()],
        "featureFlags": feature_flags.all(),
        "db": {"collections": len(db.collections), "memory": f"{_heap_mb()} MB"},
    }


def _uptime():
    return time.time() - _START_TIME


_START_TIME = time.time()


def get_jobs():
    return scheduler.status()


def run_job(job_id):
    scheduler.run_now(job_id)
    return {"jobId": job_id, "status": "triggered"}


def get_configuration():
    col = db.collection("system_config")
    if col.count() == 0:
        col.insert_many([
            {"key": "exchange", "value": "ICMarkets-Demo", "type": "string"},
            {"key": "defaultLeverage", "value": "1:500", "type": "string"},
            {"key": "maxLotSize", "value": 5, "type": "number"},
            {"key": "newsSentimentThreshold", "value": 0.15, "type": "number"},
            {"key": "decisionConfidenceThreshold", "value": 0.6, "type": "number"},
        ])
    return col.find({})


def update_configuration(key, value):
    col = db.collection("system_config")
    row = col.find_one({"key": key})
    if row:
        return col.update(row["id"], {"value": value, "updatedAt": int(time.time() * 1000)})
    return col.insert({"key": key, "value": value, "type": type(value).__name__})


def get_logs(params=None):
    params = params or {}
    logs = db.collection("logs").find({})
    return sorted(logs, key=lambda l: l["timestamp"], reverse=True)[: int(params.get("limit") or 100)]


async def get_health():
    return monitoring.health()

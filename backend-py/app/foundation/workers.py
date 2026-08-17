"""Worker pool mirroring the Node foundation workers.js."""
import asyncio

from .event_bus import event_bus
from .logger import logger

RUN_EVENT = "quantos:worker:run"


class WorkerPool:
    def __init__(self, size=4):
        self.size = size
        self.active = 0
        self.pool = {}
        self.stats = {"total": 0, "running": 0, "failed": 0, "completed": 0}
        event_bus.on(RUN_EVENT, lambda e: self._kick(e["payload"].get("workerId")))

    def register(self, worker):
        if not worker.get("id"):
            raise ValueError("Worker requires id")
        self.pool[worker["id"]] = {**worker, "running": False, "lastPayload": {}}
        event_bus.emit("quantos:worker:registered", {"workerId": worker["id"]})
        logger.info(f"Worker registered: {worker['id']}")

    def trigger(self, worker_id, payload=None):
        payload = payload or {}
        w = self.pool.get(worker_id)
        if not w:
            return False
        w["lastPayload"] = payload
        event_bus.emit(RUN_EVENT, {"workerId": worker_id})
        return True

    def _kick(self, worker_id):
        w = self.pool.get(worker_id)
        if not w or w["running"]:
            return
        w["running"] = True
        self.active += 1
        self.stats["running"] += 1
        self.stats["total"] += 1
        try:
            result = w["handler"](w["lastPayload"] or {}, self)
            if asyncio.iscoroutine(result):
                asyncio.run(result)
            self.stats["completed"] += 1
            event_bus.emit("quantos:worker:completed", {"workerId": worker_id})
        except Exception as err:  # noqa: BLE001
            self.stats["failed"] += 1
            logger.error(f"Worker {worker_id} failed", {"error": str(err)})
        finally:
            w["running"] = False
            self.active -= 1
            self.stats["running"] -= 1

    def status(self):
        return {
            "size": self.size,
            "active": self.active,
            "stats": self.stats,
            "workers": [{"id": w["id"], "running": w["running"], "intervalMs": w.get("intervalMs")} for w in self.pool.values()],
        }


workers = WorkerPool()


def init_workers():
    logger.info("Background worker pool initialized")
    return workers

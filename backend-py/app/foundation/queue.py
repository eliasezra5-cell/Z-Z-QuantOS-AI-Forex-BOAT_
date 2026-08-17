"""Queue system mirroring the Node foundation queue.js (event-driven task queues)."""
import random
import string
import threading
import time

from .event_bus import event_bus
from .logger import logger

QUEUE_EVENT = "quantos:queue:run"


def _task_id(queue_name):
    return f"{queue_name}-{int(time.time() * 1000)}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}"


class QueueSystem:
    def __init__(self):
        self.queues = {}
        self.stats = {"processed": 0, "failed": 0, "pending": 0}
        self.running = set()
        self._lock = threading.Lock()
        event_bus.on(QUEUE_EVENT, lambda e: self._process_queue(e["payload"].get("queue")))

    def create_queue(self, name, opts=None):
        opts = opts or {"concurrency": 2}
        with self._lock:
            if name in self.queues:
                return self.queues[name]
            q = {
                "name": name,
                "opts": opts,
                "tasks": [],
                "workers": opts.get("concurrency", 2),
                "active": 0,
                "waiting": 0,
            }
            self.queues[name] = q
            logger.info(f"Queue created: {name}")
            return q

    def add(self, queue_name, task):
        q = self.create_queue(queue_name)
        item = {
            "id": task.get("id") or _task_id(queue_name),
            "fn": task["fn"],
            "meta": task.get("meta") or {},
        }
        with self._lock:
            q["tasks"].append(item)
            q["waiting"] = len(q["tasks"])
            self.stats["pending"] = self._total_pending()
        event_bus.emit(QUEUE_EVENT, {"queue": queue_name})
        return item["id"]

    def _total_pending(self):
        return sum(len(q["tasks"]) for q in self.queues.values())

    def _process_queue(self, queue_name):
        if queue_name in self.running:
            return
        self.running.add(queue_name)
        try:
            q = self.queues.get(queue_name)
            while q and q["tasks"] and q["active"] < q["workers"]:
                with self._lock:
                    if not q["tasks"]:
                        break
                    task = q["tasks"].pop(0)
                    q["active"] += 1
                    self.stats["pending"] = self._total_pending()
                self._execute(q, task)
        finally:
            self.running.discard(queue_name)

    def _execute(self, q, task):
        import asyncio
        try:
            result = task["fn"]()
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
            self.stats["processed"] += 1
            event_bus.emit("quantos:queue:completed", {"queue": q["name"], "taskId": task["id"], "result": result})
        except Exception as err:  # noqa: BLE001
            self.stats["failed"] += 1
            logger.error(f"Queue task failed [{q['name']}/{task['id']}]", {"error": str(err)})
            event_bus.emit("quantos:queue:failed", {"queue": q["name"], "taskId": task["id"], "error": str(err)})
        finally:
            q["active"] -= 1
            q["waiting"] = len(q["tasks"])
            if q["tasks"]:
                event_bus.emit(QUEUE_EVENT, {"queue": q["name"]})

    def get_queue(self, name):
        return self.queues.get(name)

    def snapshot(self):
        out = [{"name": name, "tasks": len(q["tasks"]), "active": q["active"], "workers": q["workers"]} for name, q in self.queues.items()]
        return {"queues": out, "stats": self.stats}


queue_system = QueueSystem()


def init_queues():
    logger.info("Queue system initialized")
    return queue_system

"""Scheduler mirroring the Node foundation scheduler.js (setTimeout-based)."""
import asyncio
import threading
import time

from .event_bus import event_bus
from .logger import logger


class Scheduler:
    def __init__(self):
        self.jobs = {}
        self.timers = {}
        self._lock = threading.Lock()

    def register(self, job):
        if not job.get("id"):
            raise ValueError("Job requires id")
        if "schedule" not in job and "intervalMs" not in job:
            raise ValueError(f"Job {job['id']} requires schedule() or intervalMs")
        with self._lock:
            self.jobs[job["id"]] = {**job, "lastRun": None, "nextRun": None, "runs": 0, "enabled": job.get("enabled", True) is not False}
        self._schedule(job["id"])
        logger.info(f"Scheduler job registered: {job['id']} (every {job.get('intervalMs')}ms)")
        return job["id"]

    def _interval(self, job):
        if job.get("schedule"):
            val = job["schedule"]()
            if isinstance(val, (int, float)):
                return val
            raise ValueError("schedule() must return ms")
        return job["intervalMs"]

    def _schedule(self, job_id):
        with self._lock:
            job = self.jobs.get(job_id)
            if not job or not job["enabled"]:
                return
            interval = self._interval(job)
            next_run = time.time() * 1000 + interval
            job["nextRun"] = next_run
            timer = threading.Timer(interval / 1000.0, lambda: self._run(job_id))
            timer.daemon = True
            timer.start()
            self.timers[job_id] = timer

    def _run(self, job_id):
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job["lastRun"] = time.time() * 1000
            job["runs"] += 1
        try:
            result = job["handler"]()
            if asyncio.iscoroutine(result):
                asyncio.run(result)
            event_bus.emit("quantos:scheduler:completed", {"jobId": job_id, "runs": job["runs"]})
        except Exception as err:  # noqa: BLE001
            logger.error(f"Scheduler job {job_id} failed", {"error": str(err)})
            event_bus.emit("quantos:scheduler:failed", {"jobId": job_id, "error": str(err)})
        with self._lock:
            if job_id in self.timers:
                del self.timers[job_id]
        self._schedule(job_id)

    def enable(self, job_id):
        with self._lock:
            job = self.jobs.get(job_id)
            if job:
                job["enabled"] = True
        self._schedule(job_id)

    def disable(self, job_id):
        with self._lock:
            job = self.jobs.get(job_id)
            if job:
                job["enabled"] = False
                timer = self.timers.pop(job_id, None)
        if timer:
            timer.cancel()

    def run_now(self, job_id):
        job = self.jobs.get(job_id)
        if job:
            self._run(job_id)

    def status(self):
        return [
            {"id": j["id"], "enabled": j["enabled"], "intervalMs": j.get("intervalMs"), "lastRun": j["lastRun"], "nextRun": j["nextRun"], "runs": j["runs"]}
            for j in self.jobs.values()
        ]

    def stop_all(self):
        with self._lock:
            timers = list(self.timers.values())
            self.timers.clear()
        for t in timers:
            t.cancel()


scheduler = Scheduler()


def init_scheduler():
    logger.info("Scheduler initialized")
    return scheduler

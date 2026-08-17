"""DevOps & CI/CD manager mirroring the Node devops/manager.js."""
import random
import threading
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db

PIPELINE_STEPS = [
    {"name": "Checkout", "durationSec": 15, "type": "source"},
    {"name": "Install Dependencies", "durationSec": 60, "type": "build"},
    {"name": "Run Unit Tests", "durationSec": 45, "type": "test"},
    {"name": "Run Integration Tests", "durationSec": 90, "type": "test"},
    {"name": "Lint & Typecheck", "durationSec": 20, "type": "quality"},
    {"name": "Build Docker Image", "durationSec": 120, "type": "build"},
    {"name": "Push to Registry", "durationSec": 30, "type": "deploy"},
    {"name": "Deploy to Staging", "durationSec": 60, "type": "deploy"},
    {"name": "Run Smoke Tests", "durationSec": 45, "type": "test"},
    {"name": "Promote to Production", "durationSec": 60, "type": "deploy"},
]

RELEASE_TYPES = ["major", "minor", "patch", "rc", "hotfix"]


class DevopsManager:
    def __init__(self):
        self.col = db.collection("devops_pipelines")
        self.release_col = db.collection("releases")

    def _seed(self):
        if self.col.count() > 0:
            return
        now = int(time.time() * 1000)
        self.col.insert_many([
            {"id": "gh-actions", "name": "GitHub Actions", "platform": "github", "enabled": True, "status": "idle", "lastRun": None, "triggers": ["push", "pull_request"], "workflows": ["ci.yml", "cd.yml", "security.yml"]},
            {"id": "gitlab-ci", "name": "GitLab CI", "platform": "gitlab", "enabled": True, "status": "idle", "lastRun": None, "triggers": ["push", "merge_request"], "workflows": [".gitlab-ci.yml"]},
            {"id": "docker", "name": "Docker Build & Scan", "platform": "docker", "enabled": True, "status": "idle", "lastRun": None, "triggers": ["tag"], "workflows": ["docker-build"]},
            {"id": "k8s", "name": "Kubernetes Deploy", "platform": "kubernetes", "enabled": True, "status": "idle", "lastRun": None, "triggers": ["release"], "workflows": ["quantos.yaml"]},
            {"id": "helm", "name": "Helm Charts", "platform": "helm", "enabled": True, "status": "idle", "lastRun": None, "triggers": ["release"], "workflows": ["quantos-chart"]},
        ])
        self.release_col.insert_many([
            {"id": "rel-1.0.0", "version": "1.0.0", "tag": "v1.0.0", "branch": "main", "createdAt": now - 6 * 86400000, "status": "released", "notes": "Initial production release", "artifacts": ["quantos-backend:1.0.0", "quantos-frontend:1.0.0"]},
            {"id": "rel-1.1.0", "version": "1.1.0", "tag": "v1.1.0", "branch": "main", "createdAt": now - 2 * 86400000, "status": "released", "notes": "Multi-asset + dynamic reanalysis", "artifacts": ["quantos-backend:1.1.0", "quantos-frontend:1.1.0"]},
        ])

    def init(self):
        self._seed()
        logger.info("DevOps & CI/CD manager initialized")
        return self

    def get_overview(self):
        pipelines = self.col.all()
        releases = self.release_col.find({}, {"sort": ["createdAt", "desc"]})
        runs = db.collection("devops_runs").find({}, {"sort": ["startedAt", "desc"]})
        deployed = db.collection("deployments").find({}, {"sort": ["deployedAt", "desc"]})
        return {
            "pipelines": pipelines,
            "releases": releases,
            "runs": runs[:20],
            "deployments": deployed[:20],
            "summary": {
                "pipelines": len(pipelines),
                "enabled": len([p for p in pipelines if p["enabled"]]),
                "releases": len(releases),
                "totalRuns": db.collection("devops_runs").count(),
                "totalDeployments": db.collection("deployments").count(),
                "successRate": self._success_rate(runs),
                "avgRunDurationSec": self._avg_duration(runs),
                "timestamp": int(time.time() * 1000),
            },
        }

    def _success_rate(self, runs):
        if not runs:
            return 0
        return round(len([r for r in runs if r["status"] == "success"]) / len(runs) * 1000) / 10

    def _avg_duration(self, runs):
        if not runs:
            return 0
        return round(sum(r.get("durationSec") or 0 for r in runs) / len(runs))

    def run_pipeline(self, pipeline_id):
        pipeline = self.col.find_one({"id": pipeline_id})
        if not pipeline:
            return None
        if pipeline["status"] == "running":
            return {"status": "already-running"}
        self.col.update(pipeline["id"], {"status": "running", "startedAt": int(time.time() * 1000)})

        steps = [
            {**s, "status": "pending", "durationSec": s["durationSec"] + round(random.random() * 30)}
            for s in PIPELINE_STEPS[: 6 + random.randint(0, 3)]
        ]
        run = db.collection("devops_runs").insert({
            "pipelineId": pipeline_id, "pipelineName": pipeline["name"], "platform": pipeline["platform"],
            "startedAt": int(time.time() * 1000), "status": "running", "steps": steps, "commit": "a1b2c3d",
            "branch": "main", "triggeredBy": "manual", "durationSec": 0,
        })
        event_bus.emit("devops:run-started", {"run": run})
        threading.Thread(target=self._run_steps, args=(run, steps, pipeline_id), daemon=True).start()
        return {**run, "steps": steps}

    def _run_steps(self, run, steps, pipeline_id):
        step_index = 0
        while step_index < len(steps):
            time.sleep(0.6)
            step = steps[step_index]
            if random.random() < 0.03:
                step["status"] = "failed"
                db.collection("devops_runs").update(run["id"], {"steps": steps})
                continue
            step["status"] = "completed"
            db.collection("devops_runs").update(run["id"], {"steps": steps})
            step_index += 1
        failed = any(s["status"] == "failed" for s in steps)
        status = "failed" if failed else "success"
        duration_sec = round((int(time.time() * 1000) - run["startedAt"]) / 1000)
        db.collection("devops_runs").update(run["id"], {"status": status, "durationSec": duration_sec, "completedAt": int(time.time() * 1000)})
        self.col.update(pipeline_id, {"status": "idle", "lastRun": int(time.time() * 1000)})
        event_bus.emit("devops:run-completed", {"run": {**run, "status": status, "durationSec": duration_sec}, "pipelineId": pipeline_id})
        if status == "success":
            releases = self.release_col.find({}, {"sort": ["createdAt", "desc"]})
            latest = releases[0]["version"] if releases else "1.0.0"
            db.collection("deployments").insert({
                "pipelineId": pipeline_id, "app": run.get("pipelineName", "unknown"), "environment": "staging", "version": latest, "status": "success",
                "deployedAt": int(time.time() * 1000), "strategy": "rolling", "durationSec": duration_sec,
            })

    def run_all(self):
        return [self.run_pipeline(p["id"]) for p in self.col.all()]

    def toggle_pipeline(self, pipeline_id, enabled):
        pipeline = self.col.find_one({"id": pipeline_id})
        if not pipeline:
            return None
        return self.col.update(pipeline["id"], {"enabled": enabled, "updatedAt": _iso_now()})

    def create_release(self, params):
        releases = self.release_col.find({}, {"sort": ["createdAt", "desc"]})
        latest = releases[0] if releases else None
        base_version = params.get("version") or (latest.get("version") if latest else "1.0.0")
        release_type = params.get("type") or "patch"
        next_version = self._bump_version(base_version, release_type)
        release = self.release_col.insert({
            "version": next_version,
            "tag": f"v{next_version}",
            "branch": params.get("branch") or "main",
            "createdAt": int(time.time() * 1000),
            "status": "pending",
            "type": release_type,
            "notes": params.get("notes") or f"Release {next_version}",
            "artifacts": [f"quantos-backend:{next_version}", f"quantos-frontend:{next_version}"],
        })
        event_bus.emit("devops:release-created", {"release": release})
        threading.Timer(2.0, lambda: self.release_col.update(release["id"], {"status": "released", "releasedAt": int(time.time() * 1000)})).start()
        return release

    def _bump_version(self, current, release_type):
        parts = [int(x) for x in str(current).split(".")]
        if release_type == "major":
            return f"{parts[0] + 1}.0.0"
        if release_type == "minor":
            return f"{parts[0]}.{parts[1] + 1}.0"
        if release_type == "rc":
            return f"{parts[0]}.{parts[1]}.{(parts[2] if len(parts) > 2 else 0) + 1}-rc"
        return f"{parts[0]}.{parts[1]}.{(parts[2] if len(parts) > 2 else 0) + 1}"

    def list_releases(self):
        return self.release_col.find({}, {"sort": ["createdAt", "desc"]})

    def get_k8s_state(self):
        return {
            "clusters": [
                {"name": "quantos-prod", "region": "us-east-1", "nodes": 3, "pods": 14, "cpuUtilization": 62, "memoryUtilization": 71, "version": "1.29.4", "status": "ready"},
                {"name": "quantos-staging", "region": "us-west-2", "nodes": 2, "pods": 10, "cpuUtilization": 48, "memoryUtilization": 55, "version": "1.29.4", "status": "ready"},
            ],
            "namespaces": ["quantos", "monitoring", "ingress"],
            "helmCharts": [
                {"name": "quantos", "version": "1.1.0", "status": "deployed", "appVersion": "1.1.0", "revision": 7, "chartPath": "helm/quantos"},
                {"name": "redis", "version": "18.0.0", "status": "deployed", "appVersion": "7.2.4", "revision": 3},
                {"name": "postgresql", "version": "14.2.0", "status": "deployed", "appVersion": "16.1.0", "revision": 2},
            ],
            "helmSimulated": True,
            "deployments": db.collection("deployments").find({}, {"sort": ["deployedAt", "desc"]})[:15],
            "timestamp": int(time.time() * 1000),
        }


def _iso_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


devops_manager = DevopsManager()


def init_devops():
    return devops_manager.init()

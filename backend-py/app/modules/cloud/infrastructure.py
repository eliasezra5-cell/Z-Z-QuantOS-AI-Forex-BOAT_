"""Cloud infrastructure manager mirroring the Node cloud/infrastructure.js."""
import random
import threading
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...foundation.monitoring import monitoring

PROVIDERS = {
    "aws": {
        "id": "aws", "name": "AWS", "regions": ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"],
        "services": ["EC2", "S3", "ELB", "CloudFront", "RDS", "EKS"],
        "baseCostPerInstance": 0.046,
        "cpuPerUnit": 2,
    },
    "azure": {
        "id": "azure", "name": "Azure", "regions": ["eastus", "westus2", "westeurope", "southeastasia"],
        "services": ["Virtual Machines", "Blob Storage", "Application Gateway", "Front Door", "AKS"],
        "baseCostPerInstance": 0.044,
        "cpuPerUnit": 2,
    },
    "gcp": {
        "id": "gcp", "name": "Google Cloud", "regions": ["us-central1", "us-west1", "europe-west1", "asia-southeast1"],
        "services": ["Compute Engine", "Cloud Storage", "Cloud Load Balancing", "Cloud CDN", "GKE"],
        "baseCostPerInstance": 0.042,
        "cpuPerUnit": 2,
    },
}

ZONES = ["a", "b", "c"]


class CloudInfrastructure:
    def __init__(self):
        self.col = db.collection("cloud_infrastructure")

    def _seed(self):
        if self.col.count() > 0:
            return
        rows = []
        for p in PROVIDERS.values():
            rows.append({
                "id": f"prov-{p['id']}",
                "provider": p["id"],
                "name": p["name"],
                "regions": p["regions"],
                "services": p["services"],
                "status": "healthy",
                "connected": True,
                "costPerInstance": p["baseCostPerInstance"],
                "latency": round(random.random() * 60 + 20),
                "instances": 2,
                "autoScaling": {"enabled": True, "min": 2, "max": 6, "targetCpu": 65},
                "loadBalancers": [
                    {
                        "id": f"lb-{p['id']}-{idx + 1}", "name": f"{p['id']}-lb-{idx + 1}", "region": r,
                        "type": "application" if idx % 2 == 0 else "network", "nodes": 2, "healthyNodes": 2,
                        "requestsPerSec": round(random.random() * 800 + 200), "status": "active",
                    }
                    for idx, r in enumerate(p["regions"])
                ],
                "cdn": {"enabled": True, "edgeLocations": round(random.random() * 30 + 60), "cacheHitRate": round(random.random() * 25 + 70), "bandwidth": round(random.random() * 40 + 10)},
                "storage": [
                    {"id": f"bkt-{p['id']}-data", "name": f"{p['id']}-market-data", "region": p["regions"][0], "sizeGb": round(random.random() * 900 + 100), "objects": round(random.random() * 500000 + 100000), "encrypted": True, "tier": "hot"},
                    {"id": f"bkt-{p['id']}-backup", "name": f"{p['id']}-backups", "region": p["regions"][1], "sizeGb": round(random.random() * 200 + 50), "objects": round(random.random() * 50000 + 5000), "encrypted": True, "tier": "cold"},
                ],
            })
        created = self.col.insert_many(rows)
        self._seed_backups(created)

    def _seed_backups(self, providers):
        backup_col = db.collection("cloud_backups")
        if backup_col.count() > 0:
            return
        now = int(time.time() * 1000)
        backups = []
        for p in providers:
            for i in range(1, 4):
                backups.append({
                    "id": f"bak-{p['id']}-{i}",
                    "provider": p["id"],
                    "name": f"snapshot-{p['id']}-{i}",
                    "sizeGb": round(random.random() * 80 + 20),
                    "type": "full" if i == 1 else "incremental",
                    "status": "completed",
                    "createdAt": now - i * 24 * 3600000 - random.randint(0, 3599999),
                    "retentionDays": 30,
                    "restoreTimeSec": round(random.random() * 300 + 60),
                })
        backup_col.insert_many(backups)

    def init(self):
        self._seed()
        threading.Thread(target=self._tick_loop, daemon=True).start()

        def _on_cloud_event(event):
            p = self.col.find_one({"id": f"prov-{event['payload']['provider']}"})
            if p:
                self.col.update(p["id"], {"status": event["payload"]["status"], "lastEvent": event["payload"]["event"], "updatedAt": _iso_now()})

        event_bus.on("cloud:event", _on_cloud_event)
        logger.info("Cloud infrastructure manager initialized")
        return self

    def _tick_loop(self):
        while True:
            time.sleep(20)
            try:
                self._tick()
            except Exception:
                pass

    def _tick(self):
        providers = self.col.all()
        for p in providers:
            health = random.random()
            status = "degraded" if health < 0.02 else "healthy"
            lb_health = -1 if random.random() < 0.02 else 0
            load_balancers = []
            for idx, lb in enumerate(p.get("loadBalancers") or []):
                if idx == 0 and lb_health != 0:
                    load_balancers.append({**lb, "healthyNodes": max(0, lb["nodes"] - 1)})
                else:
                    load_balancers.append(lb)
            auto_scaling = {**p["autoScaling"]}
            cpu = round(random.random() * 50 + 25)
            if cpu > auto_scaling["targetCpu"] and auto_scaling["instances"] < auto_scaling["max"]:
                auto_scaling["instances"] += 1
            if cpu < auto_scaling["targetCpu"] - 20 and auto_scaling["instances"] > auto_scaling["min"]:
                auto_scaling["instances"] -= 1
            cost = self._estimate_cost(p, auto_scaling["instances"])
            self.col.update(p["id"], {"status": status, "loadBalancers": load_balancers, "autoScaling": auto_scaling, "instances": auto_scaling["instances"], "cpu": cpu, "cost": cost, "updatedAt": _iso_now()})
            if status == "healthy":
                monitoring.record({"name": f"cloud.{p['id']}.cpu", "value": cpu, "unit": "%"})

    def _estimate_cost(self, p, instances):
        instances_cost = (p.get("costPerInstance") or 0.045) * instances * 730
        storage_cost = sum(b["sizeGb"] * (0.012 if b["tier"] == "cold" else 0.023) for b in p.get("storage") or [])
        lb_cost = len(p.get("loadBalancers") or []) * 0.025 * 730
        cdn_cost = ((p.get("cdn") or {}).get("bandwidth") or 10) * 0.085 * 730
        return {
            "monthly": round((instances_cost + storage_cost + lb_cost + cdn_cost) * 100) / 100,
            "instancesCost": instances_cost,
            "storageCost": storage_cost,
            "lbCost": lb_cost,
            "cdnCost": cdn_cost,
            "currency": "USD",
        }

    def _instance_count(self, p):
        return p.get("instances") if p.get("instances") is not None else ((p.get("autoScaling") or {}).get("instances") if (p.get("autoScaling") or {}).get("instances") is not None else 2)

    def get_overview(self):
        providers = []
        for p in self.col.all():
            cost = self._estimate_cost(p, self._instance_count(p))
            providers.append({**p, "instances": self._instance_count(p), "cost": cost, "updatedAt": p.get("updatedAt")})
        total_cost = sum(p["cost"]["monthly"] for p in providers)
        total_instances = sum(p["instances"] for p in providers)
        total_backups = db.collection("cloud_backups").count()
        healthy = len([p for p in providers if p["status"] == "healthy"])
        return {
            "providers": providers,
            "summary": {
                "providers": len(providers),
                "healthy": healthy,
                "degraded": len(providers) - healthy,
                "totalInstances": total_instances,
                "totalCost": round(total_cost * 100) / 100,
                "totalBackups": total_backups,
                "objectStorageGb": sum(sum(b["sizeGb"] for b in p.get("storage") or []) for p in providers),
                "cdnEdgeLocations": sum((p.get("cdn") or {}).get("edgeLocations") or 0 for p in providers),
                "timestamp": int(time.time() * 1000),
            },
        }

    def get_provider(self, provider_id):
        p = self.col.find_one({"provider": provider_id})
        if not p:
            return None
        return {**p, "instances": self._instance_count(p), "cost": self._estimate_cost(p, self._instance_count(p))}

    def list_buckets(self, provider_id):
        p = self.col.find_one({"provider": provider_id})
        return (p.get("storage") or []) if p else []

    def list_load_balancers(self, provider_id):
        p = self.col.find_one({"provider": provider_id})
        return (p.get("loadBalancers") or []) if p else []

    def get_cdn(self, provider_id):
        p = self.col.find_one({"provider": provider_id})
        return p.get("cdn") if p else None

    def scale_provider(self, provider_id, delta):
        p = self.col.find_one({"provider": provider_id})
        if not p:
            return None
        target = max(p["autoScaling"]["min"], min(p["autoScaling"]["max"], p["instances"] + delta))
        self.col.update(p["id"], {"instances": target, "lastScaleAction": {"delta": delta, "target": target, "at": int(time.time() * 1000)}, "updatedAt": _iso_now()})
        event_bus.emit("cloud:scaled", {"provider": provider_id, "instances": target})
        logger.info(f"Cloud scaling: {provider_id} instances -> {target}")
        return self.col.find_one({"id": p["id"]})

    def set_auto_scaling(self, provider_id, policy):
        p = self.col.find_one({"provider": provider_id})
        if not p:
            return None
        auto_scaling = {**p["autoScaling"], **policy}
        self.col.update(p["id"], {"autoScaling": auto_scaling, "updatedAt": _iso_now()})
        return auto_scaling

    def list_backups(self):
        return db.collection("cloud_backups").find({}, {"sort": ["createdAt", "desc"]})

    def create_backup(self, provider_id):
        p = self.col.find_one({"provider": provider_id})
        if not p:
            return None
        row = db.collection("cloud_backups").insert({
            "provider": provider_id,
            "name": f"snapshot-{provider_id}-{int(time.time() * 1000)}",
            "sizeGb": round(random.random() * 80 + 20),
            "type": "full",
            "status": "running",
            "createdAt": int(time.time() * 1000),
            "retentionDays": 30,
            "restoreTimeSec": round(random.random() * 300 + 60),
        })
        threading.Timer(3.0, lambda: _complete_backup(row["id"], row)).start()
        return row

    def restore_backup(self, backup_id):
        b = db.collection("cloud_backups").find_one({"id": backup_id})
        if not b:
            return None
        restore = db.collection("cloud_restores").insert({
            "backupId": backup_id,
            "provider": b["provider"],
            "status": "running",
            "startedAt": int(time.time() * 1000),
            "estimatedDurationSec": b.get("restoreTimeSec") or 120,
        })
        threading.Timer(min(b.get("restoreTimeSec") or 120, 5.0), lambda: db.collection("cloud_restores").update(restore["id"], {"status": "completed", "completedAt": int(time.time() * 1000)})).start()
        return restore

    def list_restores(self):
        return db.collection("cloud_restores").find({}, {"sort": ["startedAt", "desc"]})

    def simulate_failure(self, provider_id):
        p = self.col.find_one({"provider": provider_id})
        if not p:
            return None
        status = "degraded" if p["status"] == "healthy" else "healthy"
        event_name = f"simulated {'recovery' if status == 'healthy' else 'incident'}"
        self.col.update(p["id"], {"status": status, "lastEvent": event_name, "updatedAt": _iso_now()})
        event_bus.emit("cloud:event", {"provider": provider_id, "status": status, "event": event_name})
        return self.col.find_one({"id": p["id"]})


def _iso_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _complete_backup(backup_id, row):
    db.collection("cloud_backups").update(backup_id, {"status": "completed", "completedAt": int(time.time() * 1000)})
    event_bus.emit("cloud:backup-completed", {"backup": row})


cloud_infrastructure = CloudInfrastructure()


def init_cloud_infrastructure():
    return cloud_infrastructure.init()

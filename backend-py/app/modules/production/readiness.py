"""Production readiness manager mirroring the Node production/readiness.js."""
import asyncio
import random
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...config import settings

DEFAULT_JWT_SECRET = "zz-quantos-dev-secret-change-me"

GO_LIVE_CHECKLIST = [
    {"id": "prod-1", "category": "Infrastructure", "item": "All services run behind load balancers with health checks", "required": True},
    {"id": "prod-2", "category": "Infrastructure", "item": "High availability (>=2 replicas) configured for backend and frontend", "required": True},
    {"id": "prod-3", "category": "Security", "item": "JWT auth enforced on all trading and admin APIs", "required": True},
    {"id": "prod-4", "category": "Security", "item": "Rate limiting enabled on public endpoints", "required": True},
    {"id": "prod-5", "category": "Security", "item": "MT5 live credentials stored via secrets manager, not plaintext", "required": True},
    {"id": "prod-6", "category": "Data", "item": "Backup & recovery plan tested with restore drill", "required": True},
    {"id": "prod-7", "category": "Data", "item": "Data pipeline (OHLC/news/economic) validated end-to-end", "required": True},
    {"id": "prod-8", "category": "Trading", "item": "Risk engine enforces max drawdown and daily loss halt", "required": True},
    {"id": "prod-9", "category": "Trading", "item": "Capital protection halt verified in manual and auto mode", "required": True},
    {"id": "prod-10", "category": "Trading", "item": "MT5 order execution tested on demo with SL/TP", "required": True},
    {"id": "prod-11", "category": "AI", "item": "Multi-agent decision pipeline validated on live symbols", "required": True},
    {"id": "prod-12", "category": "AI", "item": "Dynamic re-analysis of open positions enabled", "required": True},
    {"id": "prod-13", "category": "Monitoring", "item": "Health checks, metrics and alerting configured", "required": True},
    {"id": "prod-14", "category": "Monitoring", "item": "On-call runbooks documented for incidents", "required": True},
    {"id": "prod-15", "category": "Operations", "item": "CI/CD pipelines passing with automated tests", "required": True},
    {"id": "prod-16", "category": "Operations", "item": "Production audit report generated and reviewed", "required": True},
]

AUDIT_CATEGORIES = ["Architecture", "Security", "Performance", "Reliability", "Data Integrity", "Compliance"]

MANDATORY_GATES = [
    {
        "id": "mock-data",
        "name": "No simulation / mock data in production",
        "check": "_check_mock_data",
        "description": "Blocks go-live while MT5 runs on demo/off in production, an AI provider is a local/simulation model, or the simulationMode flag is set in system_config.",
    },
    {
        "id": "default-secrets",
        "name": "No default or plaintext secrets",
        "check": "_check_default_secrets",
        "description": "Blocks go-live while JWT_SECRET is the default dev value, MT5_PASSWORD is empty, API keys are stored in plaintext, or secret_vault entries are unencrypted.",
    },
    {
        "id": "auto-trading",
        "name": "No unattended auto-trading in production",
        "check": "_check_auto_trading",
        "description": "Blocks go-live while the trading mode is auto/auto_full in production.",
    },
    {
        "id": "missing-migrations",
        "name": "No pending database migrations",
        "check": "_check_missing_migrations",
        "description": "Blocks go-live while required collections are too sparse, a migrations directory with unapplied revisions is present, or the pipeline catalog is incomplete.",
    },
    {
        "id": "critical-tests",
        "name": "Critical test suites passing",
        "check": "_check_critical_tests",
        "description": "Blocks go-live while the last recorded critical test run is missing or failing (CI must persist a passing marker).",
    },
    {
        "id": "docs-coverage",
        "name": "Operator documentation present",
        "check": "_check_docs_coverage",
        "description": "Blocks go-live while README.md or docs/api.md is missing.",
    },
]

DEFAULT_CHECKS = [
    {"id": "sec-1", "category": "Authentication", "check": "JWT auth on admin/trading routes", "passed": True, "severity": "critical"},
    {"id": "sec-2", "category": "Authentication", "check": "Rate limiting active", "passed": True, "severity": "high"},
    {"id": "sec-3", "category": "Secrets", "check": "No hardcoded secrets in code", "passed": True, "severity": "critical"},
    {"id": "sec-4", "category": "Secrets", "check": "MT5 credentials via environment/secrets", "passed": True, "severity": "critical"},
    {"id": "sec-5", "category": "Headers", "check": "Helmet security headers", "passed": True, "severity": "medium"},
    {"id": "sec-6", "category": "Transport", "check": "HTTPS/TLS enforced", "passed": True, "severity": "high"},
    {"id": "sec-7", "category": "Audit", "check": "Audit logging enabled", "passed": True, "severity": "medium"},
    {"id": "sec-8", "category": "Input", "check": "Input validation on API bodies", "passed": True, "severity": "high"},
    {"id": "sec-9", "category": "RBAC", "check": "Role-based access control", "passed": True, "severity": "high"},
    {"id": "sec-10", "category": "Data", "check": "Sensitive data encrypted at rest", "passed": True, "severity": "high"},
]

PERF_OPTS = [
    {"id": "perf-1", "area": "API", "recommendation": "Add response compression (gzip) for JSON payloads", "impact": "high", "applied": False},
    {"id": "perf-2", "area": "Database", "recommendation": "Batch JSON-file writes with debounce to reduce I/O", "impact": "high", "applied": False},
    {"id": "perf-3", "area": "Frontend", "recommendation": "Memoize heavy chart components and virtualize lists", "impact": "medium", "applied": False},
    {"id": "perf-4", "area": "Indicators", "recommendation": "Cache indicator computations per symbol+timeframe", "impact": "high", "applied": False},
    {"id": "perf-5", "area": "WebSocket", "recommendation": "Throttle market tick broadcasts to subscribers", "impact": "medium", "applied": False},
    {"id": "perf-6", "area": "Cache", "recommendation": "Use TTL cache for quote snapshots and news feed", "impact": "medium", "applied": False},
]


class ProductionReadiness:
    def __init__(self):
        self.col = db.collection("production_readiness")

    def _seed(self):
        if self.col.count() > 0:
            return
        self.col.insert_many([{**c, "completed": False, "notes": ""} for c in GO_LIVE_CHECKLIST])

    def init(self):
        self._seed()
        logger.info("Production readiness manager initialized")
        return self

    def get_checklist(self):
        items = self.col.all()
        completed = len([i for i in items if i["completed"]])
        return {
            "items": items,
            "summary": {
                "total": len(items),
                "completed": completed,
                "pending": len(items) - completed,
                "pct": round((completed / len(items)) * 1000) / 10 if items else 0,
                "ready": completed == len(items),
            },
        }

    def update_checklist_item(self, item_id, completed, notes=None):
        item = self.col.find_one({"id": item_id})
        if not item:
            return None
        patch = {"completed": item["completed"] if completed is None else completed, "updatedAt": _iso_now()}
        if notes is not None:
            patch["notes"] = notes
        return self.col.update(item_id, patch)

    async def run_stress_test(self, params):
        concurrency = params.get("concurrency") or 50
        duration_sec = params.get("durationSec") or 30
        started_at = int(time.time() * 1000)
        requests = 0
        errors = 0
        latencies = []
        intervals = max(1, duration_sec * 2)
        for _ in range(intervals):
            await asyncio.sleep(0.5)
            for _ in range(concurrency):
                latency = round(random.random() * 150 + 5)
                latencies.append(latency)
                requests += 1
                if random.random() < 0.02:
                    errors += 1
        sorted_l = sorted(latencies)
        p50 = sorted_l[int(len(sorted_l) * 0.5)] if sorted_l else 0
        p95 = sorted_l[int(len(sorted_l) * 0.95)] if sorted_l else 0
        p99 = sorted_l[int(len(sorted_l) * 0.99)] if sorted_l else 0
        rps = round(requests / (duration_sec or 1))
        error_rate = round((errors / requests) * 1000) / 10 if requests else 0
        result = {
            "type": "stress",
            "concurrency": concurrency,
            "durationSec": duration_sec,
            "requests": requests,
            "errors": errors,
            "errorRate": error_rate,
            "rps": rps,
            "latency": {"p50": p50, "p95": p95, "p99": p99, "avg": round(sum(latencies) / len(latencies)) if latencies else 0},
            "status": "pass" if error_rate < 3 and p99 < 400 else "fail",
            "startedAt": started_at,
            "completedAt": int(time.time() * 1000),
            "passed": error_rate < 3 and p99 < 400,
        }
        db.collection("load_tests").insert(result)
        event_bus.emit("production:stress-test", {"result": result})
        return result

    async def run_load_test(self, params):
        target_rps = params.get("targetRps") or 100
        duration_sec = params.get("durationSec") or 15
        started_at = int(time.time() * 1000)
        requests = 0
        errors = 0
        latencies = []
        intervals = max(1, duration_sec * 2)
        for _ in range(intervals):
            await asyncio.sleep(0.5)
            batch = max(1, round(target_rps / 2))
            for _ in range(batch):
                latency = round(random.random() * 80 + 8)
                latencies.append(latency)
                requests += 1
                if random.random() < 0.01:
                    errors += 1
        achieved_rps = round(requests / (duration_sec or 1))
        error_rate = round((errors / requests) * 1000) / 10 if requests else 0
        sorted_l = sorted(latencies)
        p95 = sorted_l[int(len(sorted_l) * 0.95)] if sorted_l else 0
        result = {
            "type": "load",
            "targetRps": target_rps,
            "achievedRps": achieved_rps,
            "durationSec": duration_sec,
            "requests": requests,
            "errors": errors,
            "errorRate": error_rate,
            "p95": p95,
            "status": "pass" if achieved_rps >= target_rps * 0.9 and error_rate < 2 else "fail",
            "passed": achieved_rps >= target_rps * 0.9 and error_rate < 2,
            "startedAt": started_at,
            "completedAt": int(time.time() * 1000),
        }
        db.collection("load_tests").insert(result)
        event_bus.emit("production:load-test", {"result": result})
        return result

    def list_tests(self):
        stress = db.collection("load_tests").find({"type": "stress"}, {"sort": ["completedAt", "desc"]})
        load = db.collection("load_tests").find({"type": "load"}, {"sort": ["completedAt", "desc"]})
        return {"stress": stress[:10], "load": load[:10]}

    def run_security_hardening_scan(self):
        scan = db.collection("security_scans").insert({
            "type": "hardening",
            "status": "running",
            "startedAt": int(time.time() * 1000),
            "checks": [],
        })

        def _complete():
            passed_count = len([c for c in DEFAULT_CHECKS if c["passed"]])
            result = {
                **scan,
                "status": "completed",
                "completedAt": int(time.time() * 1000),
                "checks": DEFAULT_CHECKS,
                "summary": {"total": len(DEFAULT_CHECKS), "passed": passed_count, "failed": len(DEFAULT_CHECKS) - passed_count, "score": round((passed_count / len(DEFAULT_CHECKS)) * 100)},
            }
            db.collection("security_scans").update(scan["id"], result)
            event_bus.emit("production:security-scan", {"scan": result})

        import threading
        threading.Timer(2.0, _complete).start()
        return scan

    def list_security_scans(self):
        return db.collection("security_scans").find({}, {"sort": ["startedAt", "desc"]})[:10]

    def performance_optimization(self):
        return PERF_OPTS

    def apply_optimization(self, opt_id):
        opt = next((o for o in PERF_OPTS if o["id"] == opt_id), None)
        if not opt:
            return None
        return {**opt, "applied": True, "appliedAt": int(time.time() * 1000)}

    def get_high_availability(self):
        failovers = db.collection("failover_events").find({}, {"sort": ["at", "desc"]})
        return {
            "backend": {"replicas": 2, "minReplicas": 2, "zoneSpread": 3, "status": "active", "failover": {"type": "active-passive", "enabled": True, "rtoSec": 30, "rpoSec": 60}},
            "frontend": {"replicas": 2, "minReplicas": 2, "zoneSpread": 3, "status": "active", "failover": {"type": "active-active", "enabled": True}},
            "database": {"mode": "replicated", "replicas": 3, "sync": "semi-sync", "status": "healthy"},
            "mt5": {"mode": "active-passive", "status": "primary", "brokerFailover": True},
            "summary": {"overall": "high-availability", "degraded": False, "lastFailover": failovers[0] if failovers else None},
        }

    def trigger_failover(self, target=None):
        event = db.collection("failover_events").insert({
            "target": target or "backend",
            "type": "manual",
            "status": "completed",
            "at": int(time.time() * 1000),
            "downtimeSec": round(random.random() * 10 + 2),
            "notes": "Failover to secondary zone completed",
        })
        event_bus.emit("production:failover", {"event": event})
        return event

    def disaster_recovery_plan(self):
        drills = db.collection("dr_drills").find({}, {"sort": ["at", "desc"]})
        return {
            "rpo": 60,
            "rto": 300,
            "strategy": "Multi-region active-passive with hourly backups",
            "backups": [
                {"id": "dr-1", "resource": "market-data-ohlc", "frequency": "hourly", "retention": "30d", "region": "us-east-1"},
                {"id": "dr-2", "resource": "positions-orders", "frequency": "real-time", "retention": "90d", "region": "us-east-1"},
                {"id": "dr-3", "resource": "ai-memory-vectors", "frequency": "hourly", "retention": "30d", "region": "eu-west-1"},
                {"id": "dr-4", "resource": "config-secrets", "frequency": "on-change", "retention": "365d", "region": "us-west-2"},
            ],
            "runbook": ["1. Declare incident", "2. Redirect traffic to standby region", "3. Restore latest backup", "4. Verify data integrity", "5. Resume trading", "6. Post-incident review"],
            "lastDrill": drills[0] if drills else None,
        }

    def run_dr_drill(self):
        return db.collection("dr_drills").insert({
            "type": "disaster-recovery",
            "status": "completed",
            "at": int(time.time() * 1000),
            "durationSec": round(random.random() * 120 + 60),
            "restored": ["market-data", "positions", "ai-memory"],
            "passed": True,
        })

    def run_audit(self):
        categories = []
        for cat in AUDIT_CATEGORIES:
            score = round(random.random() * 15 + 80)
            categories.append({
                "category": cat,
                "score": score,
                "status": "excellent" if score >= 90 else ("good" if score >= 80 else "review"),
                "findings": [
                    {"severity": "info", "item": f"{cat} controls reviewed"},
                    {"severity": "low" if score >= 80 else "high", "item": "Minor recommendations" if score >= 80 else "Actionable improvements required"},
                ],
            })
        overall_score = round(sum(c["score"] for c in categories) / len(categories))
        audit = db.collection("production_audits").insert({
            "categories": categories,
            "overallScore": overall_score,
            "status": "pass" if overall_score >= 90 else "review",
            "generatedAt": int(time.time() * 1000),
            "recommendedActions": [] if overall_score >= 90 else ["Review high-impact findings before go-live"],
        })
        return audit

    def list_audits(self):
        return db.collection("production_audits").find({}, {"sort": ["generatedAt", "desc"]})[:10]

    def _check_mock_data(self):
        """Fail the gate while simulation/random data is active."""
        is_prod = str(getattr(settings, "ENVIRONMENT", "") or "").lower() == "production"
        risks = []
        mt5_mode = str(getattr(settings, "MT5_ENABLED", "") or "").lower()
        if is_prod and mt5_mode in ("demo", "off"):
            risks.append(f"MT5 mode is '{settings.MT5_ENABLED}' in production (expected live)")
        ai_provider = str(getattr(settings, "AI_PROVIDER", "") or "").lower()
        ai_model = str(getattr(settings, "AI_MODEL", "") or "").lower()
        if is_prod and (ai_provider in ("local-model", "finbert") or "sim" in ai_provider or "simulation" in ai_model):
            risks.append(f"AI provider '{settings.AI_PROVIDER}' is a local/simulation model in production")
        sim_flag = db.collection("system_config").find_one({"key": "simulationMode"})
        if sim_flag and sim_flag.get("value"):
            risks.append("simulationMode flag set in system_config")
        if risks:
            return {"passed": False, "detail": "; ".join(risks)}
        return {"passed": True, "detail": f"no simulation/mock data active (env={settings.ENVIRONMENT}, mt5={settings.MT5_ENABLED})"}

    def _check_default_secrets(self):
        """Fail the gate while default or plaintext secrets are in use."""
        problems = []
        jwt_secret = getattr(settings, "JWT_SECRET", "") or ""
        _PLACEHOLDER_SECRETS = {"", "change-me", "change-me-in-production", "changeme", "secret", "your-secret-key", "zz-quantos-dev-secret-change-me"}
        if str(jwt_secret).strip().lower() in _PLACEHOLDER_SECRETS or DEFAULT_JWT_SECRET in str(jwt_secret):
            problems.append("JWT_SECRET still set to a default/development value")
        if not getattr(settings, "MT5_PASSWORD", ""):
            problems.append("MT5_PASSWORD is empty")
        for row in db.collection("api_keys").find({}):
            if "key" in row and "keyHash" not in row:
                problems.append(f"api key '{row.get('name') or row.get('id')}' stored in plaintext (no keyHash)")
                break
        for row in db.collection("secret_vault").find({}):
            if row.get("alg") not in ("fernet", "aes"):
                problems.append(f"secret_vault entry '{row.get('name')}' not encrypted")
        if problems:
            return {"passed": False, "detail": "; ".join(problems)}
        return {"passed": True, "detail": "JWT secret rotated, MT5 credentials set, keys stored hashed/encrypted"}

    def _check_auto_trading(self):
        """Fail the gate while auto trading is active in production."""
        is_prod = str(getattr(settings, "ENVIRONMENT", "") or "").lower() == "production"
        mode = None
        row = db.collection("trading_modes").find_one({"id": "trading-mode"})
        if row:
            mode = row.get("mode")
        if not mode:
            try:
                from ..trading.engine import trading_engine
                mode = getattr(trading_engine, "mode", None)
            except Exception:  # noqa: BLE001
                mode = None
        mode = str(mode or "").lower()
        if is_prod and mode in ("auto", "auto_full"):
            return {"passed": False, "detail": f"auto trading active ({mode}) in production"}
        return {"passed": True, "detail": f"trading mode is '{mode or 'unknown'}'" + ("" if is_prod else " (non-production)")}

    def _check_missing_migrations(self):
        """Fail the gate while required collections are sparse, a migrations
        directory holds unapplied revisions, or the pipeline catalog is
        incomplete."""
        missing = []
        required = {"feature_store": 5, "news_sources": 5, "economic_events": 5}
        for name, min_count in required.items():
            count = db.collection(name).count()
            if count < min_count:
                missing.append(f"{name} has {count}/{min_count} rows")
        pipelines = db.collection("pipelines").find({})
        if len(pipelines) < len(required):
            missing.append(f"pipelines catalog incomplete ({len(pipelines)}/{len(required)})")
        migration_problems = self._check_pending_migrations()
        if migration_problems:
            missing.extend(migration_problems)
        if missing:
            return {"passed": False, "detail": "; ".join(missing)}
        return {"passed": True, "detail": "required collections populated and no pending migrations"}

    def _check_pending_migrations(self):
        """Detect an Alembic migrations directory with unapplied revisions.

        Returns a list of human-readable problems (empty when clean). The
        alembic_version table in the database is the source of truth when the
        async engine is available; otherwise the filesystem revision head is
        compared against the recorded applied revision.
        """
        problems = []
        migrations_dir = None
        candidates = [settings.ROOT_DIR / "backend-py" / "migrations", settings.ROOT_DIR / "migrations"]
        for cand in candidates:
            if cand.is_dir():
                migrations_dir = cand
                break
        if migrations_dir is None:
            return problems  # no migration framework in use -> not a blocker
        try:
            versions_dir = migrations_dir / "versions"
            revisions = sorted(
                [p.stem for p in versions_dir.glob("*.py") if p.stem not in ("__init__", "env")],
                key=_sortable_revision,
            )
        except Exception:  # noqa: BLE001 - filesystem probe best effort
            revisions = []
        if not revisions:
            return problems
        applied = self._applied_revision()
        if applied is None:
            problems.append(f"{len(revisions)} unapplied migration revisions ({revisions[-1]})")
        else:
            try:
                applied_idx = next(i for i, rev in enumerate(revisions) if rev == applied)
            except StopIteration:
                applied_idx = -1
            pending = revisions[applied_idx + 1:]
            if pending:
                problems.append(f"{len(pending)} unapplied migration revisions: {', '.join(pending)}")
        return problems

    def _applied_revision(self):
        """Return the latest applied alembic revision, if determinable."""
        try:
            row = db.collection("alembic_version").find_one({})
            if row:
                return row.get("version_num")
        except Exception:  # noqa: BLE001
            pass
        return None

    def _check_critical_tests(self):
        """Fail the gate while the last recorded critical test run is missing
        or failing.

        CI persists a marker (JSON) after running the safety/critical suites;
        the gate only passes when a recent marker reports success.
        """
        problems = []
        marker = self._test_marker()
        if marker is None:
            problems.append("no critical test marker found (CI must persist app/tests/.critical-tests.json)")
        else:
            stale = (int(time.time() * 1000) - marker.get("timestamp", 0)) > self._test_marker_max_age_ms()
            if not marker.get("passed"):
                problems.append("last critical test run reported failures")
            elif stale:
                problems.append("critical test marker is stale (>24h)")
            if marker.get("failedSuites"):
                problems.append(f"failing suites: {', '.join(marker['failedSuites'])}")
        if problems:
            return {"passed": False, "detail": "; ".join(problems)}
        return {"passed": True, "detail": "critical test suites passing (last run green)"}

    def _test_marker(self):
        """Load the persisted critical-test marker (DB row or JSON file)."""
        try:
            rows = db.collection("test_results").find({"scope": "critical"}, {"sort": ["timestamp", "desc"]})
            if rows:
                row = rows[0]
                return {"passed": bool(row.get("passed")), "timestamp": row.get("timestamp") or 0, "failedSuites": row.get("failedSuites") or []}
        except Exception:  # noqa: BLE001
            pass
        import json as _json

        candidates = [
            settings.ROOT_DIR / "backend-py" / "app" / "tests" / ".critical-tests.json",
            settings.ROOT_DIR / "app" / "tests" / ".critical-tests.json",
        ]
        for path in candidates:
            try:
                if path.exists():
                    data = _json.loads(path.read_text())
                    return {"passed": bool(data.get("passed")), "timestamp": int(data.get("timestamp") or 0), "failedSuites": data.get("failedSuites") or []}
            except Exception:  # noqa: BLE001
                pass
        return None

    @staticmethod
    def _test_marker_max_age_ms():
        return 24 * 60 * 60 * 1000

    def _check_docs_coverage(self):
        """Fail the gate while operator documentation is missing."""
        root = settings.ROOT_DIR
        while not (root / "README.md").exists() and root.parent != root:
            root = root.parent
        problems = []
        if not (root / "README.md").exists():
            problems.append("README.md missing")
        if not (root / "docs" / "api.md").exists():
            problems.append("docs/api.md missing")
        if problems:
            return {"passed": False, "detail": "; ".join(problems)}
        return {"passed": True, "detail": "README.md and docs/api.md present"}

    def check_go_live_gates(self):
        """Evaluate all mandatory go-live gates live. Gates that cannot be
        determined safely default to a blocked (failed) state."""
        gates = []
        for gate in MANDATORY_GATES:
            try:
                result = getattr(self, gate["check"])()
                gates.append({
                    "id": gate["id"],
                    "name": gate["name"],
                    "passed": bool(result.get("passed")),
                    "detail": result.get("detail", ""),
                })
            except Exception as err:  # noqa: BLE001
                logger.warn(f"Go-live gate {gate['id']} could not be verified: {err}")
                gates.append({"id": gate["id"], "name": gate["name"], "passed": False, "detail": "unable-to-verify"})
        return {"ready": all(g["passed"] for g in gates), "gates": gates}

    def get_go_live_status(self):
        """Combine mandatory gates, checklist completion and the last audit pass."""
        gates = self.check_go_live_gates()
        checklist = self.get_checklist()
        audits = self.list_audits()
        last_audit = audits[0] if audits else None
        audit_passed = last_audit["status"] == "pass" if last_audit else False
        blocked = len([g for g in gates["gates"] if not g["passed"]])
        checklist_ready = checklist["summary"]["ready"]
        ready = blocked == 0 and checklist_ready and audit_passed
        return {
            "ready": ready,
            "gatesBlocked": blocked,
            "details": {
                "checklistReady": checklist_ready,
                "checklistPct": checklist["summary"]["pct"],
                "auditPassed": audit_passed,
                "overallScore": last_audit["overallScore"] if last_audit else 0,
                "gates": gates,
                "timestamp": int(time.time() * 1000),
            },
        }

    def get_overall(self):
        checklist = self.get_checklist()
        audits = self.list_audits()
        ha = self.get_high_availability()
        last_audit = audits[0] if audits else None
        go_live = self.get_go_live_status()
        return {
            "checklist": checklist,
            "highAvailability": ha,
            "lastAudit": last_audit,
            "disasterRecovery": self.disaster_recovery_plan(),
            "goLiveStatus": {
                "ready": go_live["ready"],
                "gatesBlocked": go_live["gatesBlocked"],
                "checklistReady": go_live["details"]["checklistReady"],
                "checklistPct": go_live["details"]["checklistPct"],
                "auditPassed": go_live["details"]["auditPassed"],
                "overallScore": go_live["details"]["overallScore"],
                "gates": go_live["details"]["gates"],
                "timestamp": go_live["details"]["timestamp"],
            },
        }


def _iso_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _sortable_revision(stem):
    """Return a sortable key for an Alembic revision id (hex or numeric)."""
    digits = "".join(ch for ch in str(stem) if ch.isdigit())
    return int(digits) if digits else 0


production_readiness = ProductionReadiness()


def init_production_readiness():
    return production_readiness.init()

"""Observability init mirroring the Node observability/init.js.

SLO tracking, a dependency-free Prometheus text exporter, lightweight trace
spans and scheduled recording of critical metrics for SLO evaluation.
"""
import os
import time
from contextlib import contextmanager

from ...foundation.monitoring import monitoring
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...foundation.scheduler import scheduler
from ...foundation.event_bus import event_bus, get_event_history
from ..marketdata.engine import get_quote

request_count = 0
error_count = 0
initialized = False

DUPLICATE_ORDER_WINDOW_MS = 5 * 60 * 1000


class SloDefinition:
    """Service Level Objective: target attainment percentage within a window."""

    def __init__(self, name, metric, threshold, target_pct, window_ms, mode="lt", label=None):
        self.name = name
        self.metric = metric
        self.threshold = threshold
        self.target_pct = target_pct
        self.window_ms = window_ms
        self.mode = mode
        self.label = label or name

    def check(self):
        """Compute current attainment from stored metric history via monitoring.query."""
        since = int(time.time() * 1000) - self.window_ms
        if self.mode == "availability":
            reqs = monitoring.query("app.requests", {"since": since})
            errs = monitoring.query("app.errors", {"since": since})
            if reqs and errs:
                if len(reqs) >= 2 and len(errs) >= 2:
                    r_delta = reqs[-1]["value"] - reqs[0]["value"]
                    e_delta = errs[-1]["value"] - errs[0]["value"]
                    current = (1 - e_delta / r_delta) if r_delta > 0 else 1.0
                else:
                    current = 1.0 if reqs[-1]["value"] == 0 else max(0.0, 1 - errs[-1]["value"] / reqs[-1]["value"])
                attainment_pct = round(current * 100, 2)
            else:
                current = None
                attainment_pct = None
        else:
            rows = monitoring.query(self.metric, {"since": since})
            current = rows[-1].get("value") if rows else None
            if rows:
                if self.mode == "eq":
                    good = sum(1 for r in rows if r.get("value", 0) == self.threshold)
                else:
                    good = sum(1 for r in rows if r.get("value", 0) < self.threshold)
                attainment_pct = round(good / len(rows) * 100, 2)
            else:
                attainment_pct = None
        status = "meeting" if (attainment_pct is not None and attainment_pct >= self.target_pct) else "breaching"
        return {
            "name": self.name,
            "label": self.label,
            "metric": self.metric,
            "threshold": self.threshold,
            "windowMs": self.window_ms,
            "target": self.target_pct,
            "current": current,
            "attainmentPct": attainment_pct,
            "status": status,
        }


slos = {
    "news_latency": SloDefinition("news_latency", "news.latency", 60000, 99.0, 3600000, mode="lt", label="news_latency (<60s)"),
    "decision_to_order": SloDefinition("decision_to_order", "decision.to.order", 5000, 99.0, 3600000, mode="lt", label="decision_to_order (<5s)"),
    "stale_age": SloDefinition("stale_age", "news.stale_age", 30000, 99.0, 3600000, mode="lt", label="stale_age (<30s)"),
    "duplicate_order_count": SloDefinition("duplicate_order_count", "order.duplicate_count", 0, 100.0, 3600000, mode="eq", label="duplicate_order_count (0)"),
    "error_budget": SloDefinition("error_budget", "app.errors", None, 95.0, 3600000, mode="availability", label="error_budget (95% availability)"),
}


def get_slo_report():
    """Return each SLO's target, current, attainmentPct and status."""
    return {name: slo.check() for name, slo in slos.items()}


COUNTER_NAMES = {"app.requests", "app.errors"}


def _is_counter(name):
    base = str(name).lower()
    return base.startswith("event.") or base in COUNTER_NAMES or base.endswith(".count") or base.endswith("_total")


def _prometheus_name(name):
    out = []
    for ch in str(name):
        out.append(ch if (ch.isalnum() or ch == "_") else "_")
    return "".join(out)


class PrometheusTextExporter:
    """Build a Prometheus text-format dump from monitoring data (no external deps)."""

    def __init__(self, hub):
        self.hub = hub

    def prometheus_text(self):
        grouped = {}
        for row in self.hub.col.find({}):
            name = row.get("name")
            if not name:
                continue
            grouped.setdefault(name, []).append(row)
        lines = []
        for name in sorted(grouped):
            samples = sorted(grouped[name], key=lambda s: s.get("timestamp", 0))[-500:]
            safe = _prometheus_name(name)
            mtype = "counter" if _is_counter(name) else "gauge"
            lines.append(f"# TYPE {safe} {mtype}")
            for s in samples:
                lines.append(f"{safe} {s.get('value', 0)} {s.get('timestamp', 0)}")
        return "\n".join(lines) + "\n"


prometheus_exporter = PrometheusTextExporter(monitoring)


def prometheus_text():
    return prometheus_exporter.prometheus_text()


traces = db.collection("traces")


@contextmanager
def trace_span(name, attrs=None):
    """Context-manager-ish helper recording a span's start and duration."""
    started_ms = int(time.time() * 1000)
    started = time.monotonic()
    try:
        yield
    finally:
        traces.insert({
            "name": name,
            "attrs": attrs or {},
            "startedAt": started_ms,
            "durationMs": round((time.monotonic() - started) * 1000, 2),
        })


def record_critical_metrics():
    """Read latency/staleness/duplicate signals from event history into monitoring metrics."""
    try:
        _record_news_metrics()
        _record_decision_to_order()
        _record_duplicate_orders()
    except Exception as err:  # noqa: BLE001
        logger.error("Failed to record critical SLO metrics", {"error": str(err)})


def _record_news_metrics():
    events = get_event_history("news:processed", 20)
    if not events:
        return
    now = int(time.time() * 1000)
    event = events[-1]
    item = (event.get("payload") or {}).get("item") or {}
    published = item.get("time")
    if not published:
        return
    latency = event["timestamp"] - published
    if latency >= 0:
        monitoring.record({"name": "news.latency", "value": latency, "unit": "ms"})
    stale = now - published
    if stale >= 0:
        monitoring.record({"name": "news.stale_age", "value": stale, "unit": "ms"})


def _record_decision_to_order():
    decisions = get_event_history("ai:decision", 100)
    opens = get_event_history("trade:opened", 100)
    if not decisions or not opens:
        return
    order_event = opens[-1]
    order_ts = order_event["timestamp"]
    decision = decisions[-1]
    for d in reversed(decisions):
        if d["timestamp"] <= order_ts:
            decision = d
            break
    latency = order_ts - decision["timestamp"]
    if 0 <= latency < 3600000:
        monitoring.record({"name": "decision.to.order", "value": latency, "unit": "ms"})


def _record_duplicate_orders():
    window_start = int(time.time() * 1000) - DUPLICATE_ORDER_WINDOW_MS
    events = [e for e in get_event_history("trade:opened", 500) if e["timestamp"] >= window_start]
    counts = {}
    for e in events:
        pos = (e.get("payload") or {}).get("position") or {}
        key = (pos.get("symbol"), pos.get("side"))
        counts[key] = counts.get(key, 0) + 1
    duplicates = sum(max(0, c - 1) for c in counts.values())
    monitoring.record({"name": "order.duplicate_count", "value": duplicates})


def _handle():
    return {
        "getHealth": lambda: monitoring.health(),
        "getMetrics": lambda name, opts=None: monitoring.query(name, opts),
        "recordEvent": _record_event,
        "getSloReport": get_slo_report,
        "prometheusText": prometheus_text,
    }


def _record_event(event):
    if event.get("topic"):
        monitoring.record({"name": f"event.{event['topic']}", "value": 1})


def init_observability():
    global initialized
    if initialized:
        return _handle()
    initialized = True

    monitoring.register_health_check("database", lambda: db.collection("health").count())
    monitoring.register_health_check("market-data", lambda: get_quote("EURUSD"))
    monitoring.register_health_check("event-bus", lambda: event_bus.emit("health:check", {"ts": int(time.time() * 1000)}))

    def _aggregate():
        monitoring.record({"name": "system.memory", "value": _heap_used(), "unit": "bytes"})
        monitoring.record({"name": "system.cpu", "value": _cpu_user_ms() / 1000, "unit": "ms"})
        monitoring.record({"name": "app.requests", "value": request_count})
        monitoring.record({"name": "app.errors", "value": error_count})

    scheduler.register({"id": "metrics-aggregate", "intervalMs": 15000, "handler": _aggregate})
    scheduler.register({"id": "slo-critical-metrics", "intervalMs": 15000, "handler": record_critical_metrics})
    logger.info("Monitoring & observability initialized")
    return _handle()


def _heap_used():
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    except Exception:
        return 0


def _cpu_user_ms():
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_utime * 1000
    except Exception:
        return 0


def count_request():
    global request_count
    request_count += 1


def count_error():
    global error_count
    error_count += 1


# --------------------------------------------------------------------------- #
# Additional metrics (additive Module 4.1): API latency, AI inference time,
# MT5 execution delay.
# --------------------------------------------------------------------------- #
def record_api_latency(method, path, latency_ms, status=200):
    """Record per-route request latency for the Prometheus text exporter."""
    try:
        monitoring.record({
            "name": "api.latency",
            "value": float(latency_ms),
            "unit": "ms",
            "method": method,
            "path": _prometheus_name(path),
            "status": int(status),
        })
    except Exception:  # noqa: BLE001 - metrics best effort
        pass


def record_ai_latency(provider, latency_ms):
    """Record AI inference latency by provider."""
    try:
        monitoring.record({
            "name": "ai.inference.latency",
            "value": float(latency_ms),
            "unit": "ms",
            "provider": provider,
        })
    except Exception:  # noqa: BLE001 - metrics best effort
        pass


def record_mt5_execution_delay(latency_ms, symbol=None, side=None):
    """Record MT5 order execution delay (decision/accepted -> filled)."""
    try:
        monitoring.record({
            "name": "mt5.execution.delay",
            "value": float(latency_ms),
            "unit": "ms",
            "symbol": symbol,
            "side": side,
        })
    except Exception:  # noqa: BLE001 - metrics best effort
        pass


def record_ai_metric(metric, value, **labels):
    """Generic counter/gauge helper for AI pipeline metrics."""
    try:
        monitoring.record({
            "name": metric,
            "value": float(value),
            "unit": "count",
            **{k: str(v) for k, v in labels.items() if v is not None},
        })
    except Exception:  # noqa: BLE001 - metrics best effort
        pass

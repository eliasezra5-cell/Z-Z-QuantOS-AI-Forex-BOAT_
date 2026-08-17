"""OpenTelemetry distributed tracing with correlation-ID propagation.

Provides a thin real-OTEL layer (additive Module 4.1) that:

  - Sets up an OTLP ``TracerProvider`` when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is
    configured (or a console exporter when ``OTEL_ENABLED=console``).
  - Keeps a process-wide correlation ID in a ``contextvars.ContextVar`` and
    propagates it outbound via ``traceparent``/``x-correlation-id`` headers and
    Celery task headers.
  - Exposes ``start_span`` used across the API -> Celery -> AI -> MT5 pipeline
    so one request's trace links every stage.

Graceful degradation: when OTEL is not installed or not configured, spans fall
back to the dependency-free JSON-store ``trace_span`` recorder already used by
the platform (``modules/observability/init.py``) — tracing never hard-fails.
"""
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar

from ..config import settings

try:  # OpenTelemetry is optional at runtime
    from opentelemetry import trace as _ot_trace
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    _OTEL_AVAILABLE = True
except Exception:  # noqa: BLE001 - OTEL optional
    _OTEL_AVAILABLE = False

_correlation_var = ContextVar("quantos_correlation_id", default=None)

_SERVICE_NAME = "quantos"


def _env(key, default=""):
    return os.environ.get(key, default)


def _new_id():
    import uuid
    return uuid.uuid4().hex


def get_correlation_id():
    """Return the current correlation ID, minting one if absent."""
    current = _correlation_var.get()
    if not current:
        current = _new_id()
        _correlation_var.set(current)
    return current


def set_correlation_id(correlation_id):
    """Set the correlation ID for the current context (thread/task/request)."""
    if correlation_id:
        _correlation_var.set(str(correlation_id))


def extract_correlation_id(headers=None):
    """Pull a correlation ID from ``traceparent`` / ``x-correlation-id`` headers."""
    headers = headers or {}
    raw = headers.get("traceparent") or headers.get("X-Correlation-Id") or headers.get("x-correlation-id")
    if raw:
        value = str(raw).strip()
        if "-" in value:  # W3C traceparent: version-traceid-parentid-flags
            parts = value.split("-")
            if len(parts) >= 2:
                return parts[1]
        return value
    return None


def propagation_headers():
    """Headers to attach to outbound calls so the trace keeps propagating."""
    return {
        "x-correlation-id": get_correlation_id(),
    }


class NullTracer:
    """Fallback tracer: records spans to the JSON store like the legacy path."""

    def __init__(self, name=_SERVICE_NAME):
        self.name = name

    def start_span(self, name, attrs=None):
        return FallbackSpan(name, attrs)


class FallbackSpan:
    def __init__(self, name, attrs=None):
        self._name = name
        self._attrs = attrs or {}
        self._started = None
        self._monotonic = None

    def __enter__(self):
        self._started = int(time.time() * 1000)
        self._monotonic = time.monotonic()
        return self

    def set_attribute(self, key, value):
        self._attrs[key] = value

    def add_event(self, name, attrs=None):
        self._attrs.setdefault("events", []).append({"name": name, "attrs": attrs or {}})

    def __exit__(self, exc_type, exc, tb):
        from ..modules.observability.init import traces  # lazy import

        traces.insert({
            "name": self._name,
            "attrs": {**self._attrs, "correlationId": get_correlation_id()},
            "startedAt": self._started,
            "durationMs": round((time.monotonic() - self._monotonic) * 1000, 2),
            "error": bool(exc_type),
        })


class _TracerProviderProxy:
    """Proxy so callers use the same API whether OTEL is configured or not."""

    def __init__(self):
        self._provider = None
        self.backend = "json"

    def _ensure(self):
        if self._provider is not None:
            return self._provider
        if not _OTEL_AVAILABLE:
            return NullTracer()
        endpoint = _env("OTEL_EXPORTER_OTLP_ENDPOINT")
        enabled = _env("OTEL_ENABLED")
        if not endpoint and enabled != "console":
            return NullTracer()
        resource = Resource.create({SERVICE_NAME: _env("OTEL_SERVICE_NAME", _SERVICE_NAME)})
        provider = TracerProvider(resource=resource)
        if endpoint:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")))
        else:
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        _ot_trace.set_tracer_provider(provider)
        self._provider = provider
        self.backend = "otel"
        return provider

    def tracer(self, name=None):
        provider = self._ensure()
        if isinstance(provider, NullTracer):
            return provider
        return _ot_trace.get_tracer(name or _SERVICE_NAME)

    def status(self):
        return {
            "backend": self.backend,
            "otelAvailable": _OTEL_AVAILABLE,
            "correlationId": _correlation_var.get(),
            "service": _env("OTEL_SERVICE_NAME", _SERVICE_NAME),
        }


_tracer_provider = _TracerProviderProxy()


def tracer():
    return _tracer_provider.tracer()


def tracing_status():
    return _tracer_provider.status()


@contextmanager
def start_span(name, attrs=None):
    """Start a span; real OTEL span when configured, JSON fallback otherwise.

    ``attrs`` values are coerced to strings/numbers for OTEL attribute safety.
    """
    t = tracer()
    otel_span = None
    fallback = None
    if not isinstance(t, NullTracer):
        otel_span = t.start_span(name)
        for k, v in (attrs or {}).items():
            if v is None:
                continue
            otel_span.set_attribute(str(k), v if isinstance(v, (str, int, float, bool)) else str(v))
        otel_span.set_attribute("correlation.id", get_correlation_id())
        otel_span.__enter__()
    else:
        fallback = FallbackSpan(name, attrs)
        fallback.__enter__()

    try:
        yield
    except Exception as exc:
        if otel_span is not None:
            otel_span.set_attribute("error", True)
            try:
                otel_span.record_exception(exc)
            except Exception:  # noqa: BLE001 - exporter-side best effort
                pass
        raise
    finally:
        if otel_span is not None:
            otel_span.__exit__(None, None, None)
        elif fallback is not None:
            fallback.__exit__(None, None, None)


def init_tracing():
    """Initialize the tracer provider (OTLP/console) and return the proxy."""
    _tracer_provider._ensure()
    return _tracer_provider


# --------------------------------------------------------------------------- #
# Celery correlation-ID propagation
# --------------------------------------------------------------------------- #
def setup_celery_tracing(celery_app):
    """Hook Celery signals to carry the correlation ID across task boundaries.

    - ``before_task_publish`` copies the current context correlation ID into
      the task headers so the worker can restore it.
    - ``task_prerun`` restores the correlation ID in the worker context and
      opens a span around the task.
    - ``task_postrun``/``task_failure`` close the span.
    """
    if celery_app is None:
        return

    try:
        from celery.signals import before_task_publish, task_prerun, task_postrun, task_failure
    except Exception:  # noqa: BLE001 - signals unavailable
        return

    _tasks = {}

    @before_task_publish.connect
    def _before_publish(headers=None, **kwargs):
        headers = headers or {}
        headers["x-correlation-id"] = get_correlation_id()

    @task_prerun.connect
    def _prerun(task_id=None, task=None, **kwargs):
        from celery._state import get_current_task

        current = get_current_task()
        headers = {}
        if current is not None and getattr(current, "request", None):
            headers = getattr(current.request, "headers", None) or {}
        correlation_id = headers.get("x-correlation-id") if isinstance(headers, dict) else None
        set_correlation_id(correlation_id or _new_id())
        span = start_span(f"celery:{task.name if task is not None else 'task'}", attrs={"task_id": task_id})
        span.__enter__()
        _tasks[task_id] = span

    @task_postrun.connect
    def _postrun(task_id=None, **kwargs):
        span = _tasks.pop(task_id, None)
        if span is not None:
            span.__exit__(None, None, None)

    @task_failure.connect
    def _failure(task_id=None, **kwargs):
        span = _tasks.pop(task_id, None)
        if span is not None:
            span.__exit__(None, None, None)

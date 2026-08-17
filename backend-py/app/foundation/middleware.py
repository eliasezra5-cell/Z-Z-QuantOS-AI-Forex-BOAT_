"""Combined ASGI middleware: API versioning, idempotency, and API analytics.

Installed via `app.add_middleware(QuantOSMiddleware, ...)` in main.py. It runs
as an outer layer so the scope can be rewritten (versioning) before routing and
so idempotent replays / unsupported-version responses bypass the handler.
"""
import json
import time

from ..config import settings
from .api_analytics import api_analytics
from .idempotency import IDEMPOTENCY_TTL_SECONDS, idempotency_store

IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH"}


class QuantOSMiddleware:
    def __init__(self, app, version="v1", supported_versions=None, ttl_seconds=IDEMPOTENCY_TTL_SECONDS):
        self.app = app
        self.version = version
        self.supported_versions = supported_versions or [version]
        self.ttl_seconds = ttl_seconds
        self.idempotency = idempotency_store
        self.analytics = api_analytics

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or "/"
        method = (scope.get("method") or "GET").upper()

        rewritten, unsupported = self._rewrite_version(path)
        if unsupported:
            await self._send_json(send, 410, {
                "error": "api-version-unsupported",
                "supportedVersions": self.supported_versions,
            })
            self.analytics.record(method, path, 410, 0)
            return
        if rewritten:
            scope["path"] = rewritten
            if scope.get("raw_path") is not None:
                scope["raw_path"] = rewritten.encode("utf-8")
            path = rewritten

        idem_key = self._header(scope, "idempotency-key")
        is_idempotent = method in IDEMPOTENT_METHODS and bool(idem_key)

        if is_idempotent:
            if self.idempotency.is_duplicate(idem_key, method, path):
                cached = self.idempotency.get(idem_key)
                if cached is not None and cached.get("status_code") is not None:
                    await self._send_bytes(send, cached["status_code"], cached.get("body") or b"")
                    self.analytics.record(method, path, cached["status_code"], 0)
                    return
                await self._send_json(send, 409, {"error": "idempotency-key-in-flight"})
                self.analytics.record(method, path, 409, 0)
                return
            self.idempotency.put(idem_key, method, path, None, b"", ttl_seconds=self.ttl_seconds)

        start = time.perf_counter()
        status_code = 500
        body_parts = []

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            elif message["type"] == "http.response.body":
                body_parts.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            if is_idempotent:
                self.idempotency.delete(idem_key)
            raise
        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            route = scope.get("route")
            record_path = getattr(route, "path", None) or path
            self.analytics.record(method, record_path, status_code, latency_ms)

        if is_idempotent:
            if status_code >= 500:
                self.idempotency.delete(idem_key)
            else:
                self.idempotency.put(idem_key, method, path, status_code, b"".join(body_parts), ttl_seconds=self.ttl_seconds)

    def _rewrite_version(self, path):
        prefix = settings.API_PREFIX
        if path.startswith(prefix + "/"):
            rest = path[len(prefix):]
            if rest.startswith("/v"):
                version_part = rest[2:].split("/", 1)[0]
                if version_part.isdigit():
                    supported = {v[1:] if v.startswith("v") else v for v in self.supported_versions}
                    if version_part not in supported:
                        return None, True
        marker = f"{prefix}/{self.version}"
        if path == marker:
            return prefix, False
        if path.startswith(marker + "/"):
            return prefix + path[len(marker):], False
        return None, False

    @staticmethod
    def _header(scope, name):
        target = name.encode("latin-1")
        for key, value in scope.get("headers") or []:
            if key.lower() == target:
                return value.decode("latin-1")
        return None

    @staticmethod
    async def _send_json(send, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": int(status_code),
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"access-control-allow-origin", b"*"),
            ],
        })
        await send({"type": "http.response.body", "body": body, "more_body": False})

    @staticmethod
    async def _send_bytes(send, status_code, body):
        await send({
            "type": "http.response.start",
            "status": int(status_code),
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"access-control-allow-origin", b"*"),
            ],
        })
        await send({"type": "http.response.body", "body": body, "more_body": False})

"""Idempotency support for write endpoints.

Backed by the JSON store collection `idempotency_keys`. Each entry is keyed by
the client-supplied `Idempotency-Key` header and records the method/path so a
replayed request can be detected and served the stored response.
"""
import base64
from datetime import datetime, timedelta, timezone

from .json_store import db
from .logger import logger

IDEMPOTENCY_TTL_SECONDS = 3600
IDEMPOTENCY_MAX_ROWS = 5000


def _now_utc():
    return datetime.now(timezone.utc)


class IdempotencyStore:
    def __init__(self, ttl_seconds=IDEMPOTENCY_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self.col = db.collection("idempotency_keys")

    def _expired(self, row):
        expires_at = row.get("expiresAt")
        if not expires_at:
            return False
        try:
            return datetime.fromisoformat(expires_at) <= _now_utc()
        except (TypeError, ValueError):
            return False

    def _purge_expired(self, key=None):
        for row in self.col.find({}):
            if self._expired(row) and (key is None or row.get("id") == key):
                self.col.remove(row["id"])

    def get(self, key):
        self._purge_expired(key=key)
        row = self.col.find_one({"id": key})
        if not row:
            return None
        return {
            "status_code": row.get("statusCode"),
            "body": base64.b64decode(row.get("body") or b""),
            "expiresAt": row.get("expiresAt"),
        }

    def put(self, key, method, path, status_code, body, ttl_seconds=IDEMPOTENCY_TTL_SECONDS):
        expires_at = _now_utc() + timedelta(seconds=ttl_seconds or self.ttl_seconds)
        encoded = base64.b64encode(body or b"").decode("ascii") if status_code is not None else ""
        doc = {
            "id": key,
            "key": key,
            "method": method,
            "path": path,
            "statusCode": status_code,
            "body": encoded,
            "expiresAt": expires_at.isoformat(),
        }
        self.col.upsert(doc)
        if self.col.count() > IDEMPOTENCY_MAX_ROWS:
            oldest = self.col.find({}, {"sort": ["createdAt", "asc"]})[:1000]
            for row in oldest:
                self.col.remove(row["id"])
        return doc

    def delete(self, key):
        return self.col.remove(key)

    def is_duplicate(self, key, method, path):
        self._purge_expired(key=key)
        row = self.col.find_one({"id": key})
        if not row or self._expired(row):
            return False
        return row.get("method") == method and row.get("path") == path


idempotency_store = IdempotencyStore()


def init_idempotency():
    logger.info(f"Idempotency foundation initialized (ttl={idempotency_store.ttl_seconds}s)")
    return idempotency_store

"""MT5 connection credentials repository (additive).

Stores the dashboard "Connect to MT5" form values (login, password, server,
bridge URL) in a dedicated collection. The password is Fernet-encrypted at rest
via the same helpers used by the other repositories, with a JSON-file fallback
when Postgres/CRYPTO_KEY are not configured.
"""
import time
import uuid

from ..foundation.json_store import db
from ..foundation.logger import logger
from .repository import decrypt_api_key, encrypt_api_key

_COLLECTION = "mt5_connections"


class MT5ConnectionRepository:
    """Read/write a single MT5 connection document (keyed provider_name=mt5)."""

    def __init__(self):
        self.col = db.collection(_COLLECTION)

    async def save(self, fields):
        doc = {
            "provider_name": "mt5",
            "login": fields.get("login") or "",
            "server": fields.get("server") or "",
            "bridgeUrl": fields.get("bridgeUrl") or "",
            "mode": fields.get("mode") or "live",
            "password": encrypt_api_key(fields.get("password")) if fields.get("password") else None,
            "updatedAt": int(time.time() * 1000),
        }
        existing = self.col.find_one({"provider_name": "mt5"})
        if existing:
            self.col.update(existing["id"], doc)
            return doc
        doc["id"] = str(uuid.uuid4())
        doc["createdAt"] = int(time.time() * 1000)
        self.col.insert(doc)
        return doc

    async def get(self):
        row = self.col.find_one({"provider_name": "mt5"})
        if not row:
            return None
        out = dict(row)
        if out.get("password"):
            out["password"] = decrypt_api_key(out["password"]) or ""
        return out


mt5_connection_repository = MT5ConnectionRepository()

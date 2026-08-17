"""Connections repository for the Connections Manager (additive).

Persists ``IntegrationSetting`` rows (Fernet-encrypted tokens) against
PostgreSQL when enabled, otherwise the JSON file store, following the same
fallback contract as the other repositories in this package. Public methods are
async; ``run_sync`` lets thread-based callers (event handlers) use them safely.
"""
import time
import uuid

from ..foundation.json_store import db
from ..foundation.logger import logger
from . import connections_models  # noqa: F401 - register model with Base.metadata
from .db import is_postgres_enabled, session_scope
from .repository import decrypt_api_key, encrypt_api_key

_schema_ensured = False


def _new_id():
    return str(uuid.uuid4())


def _now_ms():
    return int(time.time() * 1000)


async def ensure_schema():
    """Create the integration_settings table when Postgres is enabled (idempotent)."""
    global _schema_ensured
    if _schema_ensured or not is_postgres_enabled():
        return True
    from .db import get_engine

    eng = get_engine()
    if eng is None:
        return True
    from . import models

    async with eng.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    _schema_ensured = True
    logger.info("integration_settings schema ensured")
    return True


class ConnectionsRepository:
    """Read/write integration credentials through the active store."""

    def __init__(self):
        self.col = db.collection("integration_settings")
        self.schema_ready = False

    async def _ensure(self):
        if not self.schema_ready:
            self.schema_ready = await ensure_schema()

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _row_to_dict(row):
        return row.to_dict() if hasattr(row, "to_dict") else dict(row)

    def _decrypt(self, doc):
        out = dict(doc)
        for key in ("api_token", "webhook_secret", "password"):
            if out.get(key):
                out[key] = decrypt_api_key(out[key])
        return out

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    async def get(self, provider_name):
        await self._ensure()
        if is_postgres_enabled():
            from sqlalchemy import select

            from . import models

            async with session_scope() as session:
                rows = await session.execute(
                    select(models.IntegrationSetting).where(models.IntegrationSetting.provider_name == provider_name)
                )
                row = rows.first()
                return self._row_to_dict(row._mapping["IntegrationSetting"]) if row else None
        return self.col.find_one({"provider_name": provider_name})

    async def upsert(self, provider_name, fields):
        await self._ensure()
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        doc = {
            "provider_name": provider_name,
            "api_token": encrypt_api_key(fields.get("api_token")) if fields.get("api_token") else None,
            "phone_number_id": fields.get("phone_number_id"),
            "webhook_secret": encrypt_api_key(fields.get("webhook_secret")) if fields.get("webhook_secret") else None,
            "admin_number": fields.get("admin_number"),
            "chat_id": fields.get("chat_id"),
            "host": fields.get("host"),
            "port": fields.get("port"),
            "user": fields.get("user"),
            "password": encrypt_api_key(fields.get("password")) if fields.get("password") else None,
            "from_addr": fields.get("from_addr"),
            "to_addr": fields.get("to_addr"),
            "is_active": bool(fields.get("is_active", False)),
            "updatedAt": _now_ms(),
        }
        if is_postgres_enabled():
            from . import models

            async with session_scope() as session:
                row = await session.get(models.IntegrationSetting, provider_name)
                if row is None:
                    session.add(models.IntegrationSetting(
                        provider_name=provider_name,
                        api_token=doc["api_token"],
                        phone_number_id=doc["phone_number_id"],
                        webhook_secret=doc["webhook_secret"],
                        admin_number=doc["admin_number"],
                        chat_id=doc["chat_id"],
                        host=doc["host"],
                        port=doc["port"],
                        user=doc["user"],
                        password=doc["password"],
                        from_addr=doc["from_addr"],
                        to_addr=doc["to_addr"],
                        is_active=doc["is_active"],
                        created_at=now,
                    ))
                else:
                    for key in ("api_token", "phone_number_id", "webhook_secret", "admin_number", "chat_id", "host", "port", "user", "password", "from_addr", "to_addr", "is_active"):
                        setattr(row, key, doc[key])
                    row.updated_at = now
                return self._row_to_dict(row)
        existing = self.col.find_one({"provider_name": provider_name})
        if existing:
            self.col.update(existing["id"], doc)
            return self.col.find_one({"provider_name": provider_name})
        doc["id"] = _new_id()
        doc["createdAt"] = _now_ms()
        self.col.insert(doc)
        return self.col.find_one({"provider_name": provider_name})

    async def list(self):
        await self._ensure()
        if is_postgres_enabled():
            from sqlalchemy import select

            from . import models

            async with session_scope() as session:
                rows = await session.execute(select(models.IntegrationSetting))
                return [self._row_to_dict(r._mapping["IntegrationSetting"]) for r in rows]
        return self.col.find({})

    async def remove(self, provider_name):
        await self._ensure()
        if is_postgres_enabled():
            from . import models

            async with session_scope() as session:
                row = await session.get(models.IntegrationSetting, provider_name)
                if row is None:
                    return None
                await session.delete(row)
                return {"provider_name": provider_name}
        existing = self.col.find_one({"provider_name": provider_name})
        if not existing:
            return None
        self.col.remove(existing["id"])
        return {"provider_name": provider_name}


connections_repository = ConnectionsRepository()

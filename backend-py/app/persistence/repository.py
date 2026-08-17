"""Repository layer (Data Abstraction Layer) for the persistence migration.

Each repository exposes the same operations against PostgreSQL (when enabled)
or the JSON file store (fallback), so callers and API response formats stay
identical regardless of the backing store. Public methods are async; the
``run_sync`` helper lets thread-based callers (event handlers, collectors)
invoke them safely from contexts without a running event loop.
"""
import asyncio
import os
import time
import uuid

from ..config import settings
from ..foundation.json_store import db
from ..foundation.logger import logger
from .db import is_postgres_enabled, session_scope


def _new_id():
    return str(uuid.uuid4())


def _now_ms():
    return int(time.time() * 1000)


def run_sync(coro):
    """Run a coroutine synchronously from a thread (no running loop expected)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("run_sync cannot be used from an async context")


# --------------------------------------------------------------------------- #
# Custom agent API key encryption (Fernet via cryptography)
# --------------------------------------------------------------------------- #
def _fernet():
    from cryptography.fernet import Fernet

    key = (os.environ.get("CRYPTO_KEY") or settings.CRYPTO_KEY or "").strip()
    if not key:
        return None
    if not key.endswith("="):
        import base64

        key = base64.urlsafe_b64encode(key.encode()[:32].ljust(32, b"=")).decode()
    try:
        return Fernet(key.encode())
    except Exception:  # noqa: BLE001 - malformed key falls back to no encryption
        logger.warn("CRYPTO_KEY invalid; custom agent keys stored without encryption")
        return None


def encrypt_api_key(plaintext):
    if not plaintext:
        return None
    f = _fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext):
    if not ciphertext:
        return None
    f = _fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# Row <-> dict helpers (shared by repositories)
# --------------------------------------------------------------------------- #
def _as_model(model_cls, row_mapping):
    from sqlalchemy.orm import class_mapper

    keys = {c.key for c in class_mapper(model_cls).columns}
    return model_cls(**{k: v for k, v in row_mapping.items() if k in keys})


# --------------------------------------------------------------------------- #
# News repository
# --------------------------------------------------------------------------- #
class NewsRepository:
    """Read/write news sources and news items through the active store."""

    def __init__(self):
        self.sources_col = db.collection("news_sources")
        self.items_col = db.collection("news_items")

    # ---- sources -------------------------------------------------------- #
    async def list_sources(self):
        if is_postgres_enabled():
            async with session_scope() as session:
                from sqlalchemy import select

                from . import models

                rows = await session.execute(
                    select(models.NewsSource).order_by(models.NewsSource.priority.asc())
                )
                return [_as_model(models.NewsSource, r._mapping).to_dict() for r in rows]
        return self.sources_col.find({}, {"sort": ["priority", "asc"]})

    async def add_source(self, source):
        from datetime import datetime, timezone

        from . import models

        source_type = source.get("type") or source.get("source_type") or "rss"
        doc = {
            "id": source.get("id") or _new_id(),
            "name": source.get("name") or source_type,
            "type": source_type,
            "config": source.get("config") or {},
            "priority": source.get("priority", 1),
            "enabled": source.get("enabled", True),
            "reliability": source.get("reliability", 0.7),
            "lastCollectedAt": None,
            "createdAt": _now_ms(),
        }
        if is_postgres_enabled():
            async with session_scope() as session:
                session.add(models.NewsSource(
                    id=doc["id"],
                    name=doc["name"],
                    source_type=source_type,
                    config=doc["config"],
                    priority=doc["priority"],
                    enabled=doc["enabled"],
                    reliability=float(doc["reliability"]),
                    created_at=datetime.now(timezone.utc),
                ))
                return doc
        self.sources_col.insert(doc)
        return doc

    async def remove_source(self, source_id):
        if is_postgres_enabled():
            async with session_scope() as session:
                from . import models

                row = await session.get(models.NewsSource, source_id)
                if row is None:
                    return None
                await session.delete(row)
                return {"id": source_id}
        return self.sources_col.remove(source_id)

    async def update_source(self, source_id, patch):
        if is_postgres_enabled():
            async with session_scope() as session:
                from . import models

                row = await session.get(models.NewsSource, source_id)
                if row is None:
                    return None
                if "name" in patch:
                    row.name = patch["name"]
                if "type" in patch:
                    row.source_type = patch["type"]
                if "url" in patch:
                    row.url = patch.get("url")
                if "config" in patch:
                    row.config = patch["config"] or {}
                if "priority" in patch:
                    row.priority = patch["priority"]
                if "enabled" in patch:
                    row.enabled = patch["enabled"]
                await session.commit()
                return _as_model(models.NewsSource, {
                    "id": row.id,
                    "name": row.name,
                    "source_type": row.source_type,
                    "url": row.url,
                    "config": row.config,
                    "priority": row.priority,
                    "enabled": row.enabled,
                    "reliability": row.reliability,
                }).to_dict()
        doc = self.sources_col.find_one({"id": source_id})
        if doc is None:
            return None
        if "name" in patch:
            doc["name"] = patch["name"]
        if "type" in patch:
            doc["type"] = patch["type"]
        if "url" in patch:
            doc["url"] = patch.get("url")
        if "config" in patch:
            doc["config"] = patch["config"] or {}
        if "priority" in patch:
            doc["priority"] = patch["priority"]
        if "enabled" in patch:
            doc["enabled"] = patch["enabled"]
        self.sources_col.update(source_id, doc)
        return doc

    # ---- items ---------------------------------------------------------- #
    async def insert_item(self, item):
        from datetime import datetime, timezone

        from . import models

        doc = {
            "id": item.get("id") or _new_id(),
            "sourceId": item.get("sourceId"),
            "source": item.get("source", "Unknown"),
            "sourceType": item.get("sourceType") or item.get("collectorType") or "unknown",
            "title": item.get("title", ""),
            "summary": item.get("summary"),
            "url": item.get("url"),
            "category": item.get("category"),
            "sentiment": item.get("sentiment"),
            "impact": item.get("impact"),
            "confidence": item.get("confidence"),
            "trustScore": item.get("trustScore"),
            "entities": item.get("entities") or [],
            "keywords": item.get("keywords") or [],
            "analysis": item.get("analysis") or {},
            "raw": item.get("raw") or {},
            "time": item.get("time") or _now_ms(),
            "ingestedAt": item.get("ingestedAt") or _now_ms(),
        }
        if is_postgres_enabled():
            async with session_scope() as session:
                session.add(models.NewsItem(
                    id=doc["id"],
                    source_id=doc.get("sourceId"),
                    source=doc["source"],
                    title=doc["title"],
                    summary=doc.get("summary"),
                    url=doc.get("url"),
                    category=doc.get("category"),
                    sentiment=float(doc["sentiment"]) if doc.get("sentiment") is not None else None,
                    impact=float(doc["impact"]) if doc.get("impact") is not None else None,
                    confidence=float(doc["confidence"]) if doc.get("confidence") is not None else None,
                    trust_score=float(doc.get("trustScore")) if doc.get("trustScore") is not None else None,
                    entities=doc.get("entities") or [],
                    keywords=doc.get("keywords") or [],
                    analysis=doc.get("analysis") or {},
                    raw={**(doc.get("raw") or {}), "sourceType": doc["sourceType"]},
                    time=datetime.fromtimestamp(doc["time"] / 1000, tz=timezone.utc),
                    ingested_at=datetime.fromtimestamp(doc["ingestedAt"] / 1000, tz=timezone.utc),
                ))
                return doc
        self.items_col.insert(doc)
        return doc

    async def list_items(self, limit=50, category=None, source=None, symbol=None, min_impact=None):
        if is_postgres_enabled():
            from sqlalchemy import select

            from . import models

            async with session_scope() as session:
                q = select(models.NewsItem).order_by(models.NewsItem.time.desc()).limit(limit)
                if category:
                    q = q.where(models.NewsItem.category == category)
                if source:
                    q = q.where(models.NewsItem.source == source)
                if min_impact is not None:
                    q = q.where(models.NewsItem.impact >= min_impact)
                rows = await session.execute(q)
                return [_as_model(models.NewsItem, r._mapping).to_dict() for r in rows]
        rows = self.items_col.find({}, {"sort": ["time", "desc"]})
        rows = [
            r if "sourceType" in r else {**r, "sourceType": "unknown"}
            for r in rows
            if isinstance(r, dict)
        ]
        if category:
            rows = [r for r in rows if r.get("category") == category]
        if source:
            rows = [r for r in rows if r.get("source") == source]
        if symbol:
            rows = [r for r in rows if symbol in (r.get("entities") or [])]
        if min_impact is not None:
            rows = [r for r in rows if (r.get("impact") or 0) >= min_impact]
        return rows[:limit]


# --------------------------------------------------------------------------- #
# Custom AI agent repository
# --------------------------------------------------------------------------- #
class CustomAgentRepository:
    """CRUD for custom AI agents with encrypted API keys (0-20% voting weight)."""

    def __init__(self):
        self.col = db.collection("custom_agents")

    async def list(self):
        if is_postgres_enabled():
            from sqlalchemy import select

            from . import models

            async with session_scope() as session:
                rows = await session.execute(select(models.CustomAIAgent))
                return [_as_model(models.CustomAIAgent, r._mapping).to_dict() for r in rows]
        return self.col.find({})

    async def create(self, data):
        from . import models

        weight = float(data.get("voting_weight") or data.get("votingWeight") or 0.0)
        if not (0 <= weight <= 0.20):
            return {"status": "weight-must-be-0-to-20pct"}
        provider_type = data.get("provider_type") or data.get("providerType") or "free_local"
        if provider_type not in (
            "free_local", "paid_openai", "paid_anthropic", "paid_gemini", "paid_deepseek", "custom_http",
            "xai", "dashscope", "dashscope-cn", "zhipu", "minimax", "minimax-cn", "nvidia",
        ):
            return {"status": "provider-must-be-free_local-or-paid_openai-or-paid_anthropic-or-paid_gemini-or-paid_deepseek-or-custom_http-or-xai-or-dashscope-or-dashscope-cn-or-zhipu-or-minimax-or-minimax-cn-or-nvidia"}
        doc = {
            "id": data.get("id") or _new_id(),
            "name": data.get("name") or "Unnamed Agent",
            "provider_type": provider_type,
            "model_name": data.get("model_name") or data.get("modelName") or "default",
            "system_prompt": data.get("system_prompt") or data.get("systemPrompt") or "",
            "voting_weight": weight,
            "api_key_encrypted": encrypt_api_key(data.get("api_key")),
            "base_url": data.get("base_url") or "",
            "enabled": data.get("enabled", True),
            "template": data.get("template"),
            "createdAt": _now_ms(),
        }
        if is_postgres_enabled():
            async with session_scope() as session:
                session.add(models.CustomAIAgent(
                    id=doc["id"],
                    name=doc["name"],
                    provider_type=provider_type,
                    model_name=doc["model_name"],
                    system_prompt=doc["system_prompt"],
                    voting_weight=float(doc["voting_weight"]),
                    api_key_encrypted=doc.get("api_key_encrypted"),
                    base_url=doc.get("base_url"),
                    enabled=doc.get("enabled", True),
                    template=doc.get("template"),
                ))
                return doc
        self.col.insert(doc)
        return doc

    async def update(self, agent_id, patch):
        from datetime import datetime, timezone

        from . import models

        if "voting_weight" in patch or "votingWeight" in patch:
            w = float(patch.get("voting_weight", patch.get("votingWeight", 0)))
            if not (0 <= w <= 0.20):
                return {"status": "weight-must-be-0-to-20pct"}
        if is_postgres_enabled():
            async with session_scope() as session:
                row = await session.get(models.CustomAIAgent, agent_id)
                if row is None:
                    return None
                if "name" in patch:
                    row.name = patch["name"]
                if "model_name" in patch or "modelName" in patch:
                    row.model_name = patch.get("model_name") or patch.get("modelName") or row.model_name
                if "system_prompt" in patch or "systemPrompt" in patch:
                    row.system_prompt = patch.get("system_prompt") or patch.get("systemPrompt") or ""
                if "voting_weight" in patch or "votingWeight" in patch:
                    row.voting_weight = float(patch.get("voting_weight", patch.get("votingWeight", 0)))
                if "api_key" in patch and patch["api_key"]:
                    row.api_key_encrypted = encrypt_api_key(patch["api_key"])
                if "base_url" in patch:
                    row.base_url = patch["base_url"]
                if "enabled" in patch:
                    row.enabled = bool(patch["enabled"])
                if "template" in patch:
                    row.template = patch["template"]
                row.updated_at = datetime.now(timezone.utc)
                return row.to_dict()
        self.col.update(agent_id, {**patch, "updatedAt": _now_ms()})
        return self.col.find_one({"id": agent_id})

    async def remove(self, agent_id):
        if is_postgres_enabled():
            from . import models

            async with session_scope() as session:
                row = await session.get(models.CustomAIAgent, agent_id)
                if row is None:
                    return None
                await session.delete(row)
                return {"id": agent_id}
        return self.col.remove(agent_id)

    async def enabled_agents(self):
        if is_postgres_enabled():
            from sqlalchemy import select

            from . import models

            async with session_scope() as session:
                rows = await session.execute(select(models.CustomAIAgent).where(models.CustomAIAgent.enabled.is_(True)))
                return [_as_model(models.CustomAIAgent, r._mapping).to_dict() for r in rows]
        return [a for a in self.col.find({"enabled": True})]


# --------------------------------------------------------------------------- #
# AI decision repository
# --------------------------------------------------------------------------- #
class DecisionRepository:
    """Persist AI decisions (NUMERIC financial fields via the model)."""

    def __init__(self):
        self.col = db.collection("ai_decisions")

    async def insert(self, decision):
        from datetime import datetime, timezone

        from . import models

        doc = {
            "id": decision.get("id") or _new_id(),
            "symbol": decision.get("symbol", "XAUUSD"),
            "direction": decision.get("direction", "neutral"),
            "confidence": decision.get("confidence"),
            "weights": decision.get("weights") or {},
            "agentScores": decision.get("agentScores") or decision.get("agents") or [],
            "riskApproved": decision.get("riskApproved"),
            "newsIds": decision.get("newsIds") or [],
            "entry": decision.get("entry"),
            "stopLoss": decision.get("stopLoss"),
            "takeProfit": decision.get("takeProfit"),
            "lotSize": decision.get("lotSize"),
            "expectedPips": decision.get("expectedPips"),
            "status": decision.get("status", "no_trade"),
            "recommendation": decision.get("recommendation") or {},
            "xai": decision.get("xai") or {},
            "debate": decision.get("debate") or {},
            "timestamp": decision.get("timestamp") or _now_ms(),
        }
        if is_postgres_enabled():
            async with session_scope() as session:
                session.add(models.AIDecision(
                    id=doc["id"],
                    symbol=doc["symbol"],
                    direction=doc["direction"],
                    confidence=float(doc["confidence"]) if doc.get("confidence") is not None else None,
                    weights=doc["weights"],
                    agent_scores=doc["agentScores"],
                    risk_approved=doc.get("riskApproved"),
                    news_ids=doc.get("newsIds") or [],
                    entry=float(doc["entry"]) if doc.get("entry") is not None else None,
                    stop_loss=float(doc["stopLoss"]) if doc.get("stopLoss") is not None else None,
                    take_profit=float(doc["takeProfit"]) if doc.get("takeProfit") is not None else None,
                    lot_size=float(doc["lotSize"]) if doc.get("lotSize") is not None else None,
                    expected_pips=float(doc["expectedPips"]) if doc.get("expectedPips") is not None else None,
                    status=doc["status"],
                    recommendation=doc["recommendation"],
                    xai=doc["xai"],
                    timestamp=datetime.fromtimestamp(doc["timestamp"] / 1000, tz=timezone.utc),
                ))
                return doc
        self.col.insert(doc)
        return doc

    async def list(self, limit=50, symbol=None):
        if is_postgres_enabled():
            from sqlalchemy import select

            from . import models

            async with session_scope() as session:
                stmt = select(models.AIDecision)
                if symbol:
                    stmt = stmt.where(models.AIDecision.symbol == symbol)
                stmt = stmt.order_by(models.AIDecision.timestamp.desc()).limit(limit)
                rows = await session.execute(stmt)
                return [_as_model(models.AIDecision, r._mapping).to_dict() for r in rows]
        query = {}
        if symbol:
            query["symbol"] = symbol
        rows = self.col.find(query, {"sort": ["timestamp", "desc"]})
        return rows[:limit]

    async def latest(self):
        if is_postgres_enabled():
            from sqlalchemy import select

            from . import models

            async with session_scope() as session:
                rows = await session.execute(
                    select(models.AIDecision).order_by(models.AIDecision.timestamp.desc()).limit(1)
                )
                r = rows.first()
                return _as_model(models.AIDecision, r._mapping).to_dict() if r else None
        rows = self.col.find({}, {"sort": ["timestamp", "desc"]})
        return rows[0] if rows else None


# --------------------------------------------------------------------------- #
# Position repository (MT5 sync)
# --------------------------------------------------------------------------- #
class PositionRepository:
    """Sync MT5 open/closed positions into the active store."""

    def __init__(self):
        self.col = db.collection("positions")

    async def upsert(self, position):
        from datetime import datetime, timezone

        from . import models

        doc = {
            "id": position.get("id") or position.get("mt5Ticket") or _new_id(),
            "symbol": position.get("symbol", "XAUUSD"),
            "side": position.get("side") or position.get("direction") or "buy",
            "lotSize": position.get("lotSize", 0.01),
            "entry": position.get("entry") or position.get("entryPrice"),
            "stopLoss": position.get("stopLoss"),
            "takeProfit": position.get("takeProfit"),
            "currentPrice": position.get("currentPrice") or position.get("price"),
            "profit": position.get("profit"),
            "status": position.get("status", "open"),
            "initialConfidence": position.get("initialConfidence"),
            "newsIds": position.get("newsIds") or [],
            "mt5Ticket": position.get("mt5Ticket") or position.get("ticket"),
            "openedAt": position.get("openedAt") or _now_ms(),
            "closedAt": position.get("closedAt"),
        }
        if is_postgres_enabled():
            async with session_scope() as session:
                row = await session.get(models.Position, doc["id"])
                values = dict(
                    symbol=doc["symbol"],
                    side=doc["side"],
                    lot_size=float(doc["lotSize"]),
                    entry_price=float(doc["entry"]),
                    stop_loss=float(doc["stopLoss"]) if doc.get("stopLoss") is not None else None,
                    take_profit=float(doc["takeProfit"]) if doc.get("takeProfit") is not None else None,
                    current_price=float(doc["currentPrice"]) if doc.get("currentPrice") is not None else None,
                    profit=float(doc["profit"]) if doc.get("profit") is not None else None,
                    status=doc["status"],
                    initial_confidence=float(doc["initialConfidence"]) if doc.get("initialConfidence") is not None else None,
                    news_ids=doc.get("newsIds") or [],
                    mt5_ticket=doc.get("mt5Ticket"),
                    closed_at=datetime.fromtimestamp(doc["closedAt"] / 1000, tz=timezone.utc) if doc.get("closedAt") else None,
                )
                if row is None:
                    session.add(models.Position(id=doc["id"], **values))
                else:
                    for k, v in values.items():
                        setattr(row, k, v)
                return doc
        if self.col.find_one({"id": doc["id"]}):
            self.col.update(doc["id"], doc)
        else:
            self.col.insert(doc)
        return self.col.find_one({"id": doc["id"]})

    async def list_open(self):
        if is_postgres_enabled():
            from sqlalchemy import select

            from . import models

            async with session_scope() as session:
                rows = await session.execute(select(models.Position).where(models.Position.status == "open"))
                return [_as_model(models.Position, r._mapping).to_dict() for r in rows]
        return self.col.find({"status": "open"})

    async def get(self, position_id):
        if is_postgres_enabled():
            from . import models

            async with session_scope() as session:
                row = await session.get(models.Position, position_id)
                return row.to_dict() if row else None
        return self.col.find_one({"id": position_id})


# --------------------------------------------------------------------------- #
# Event embedding repository (pgvector historical pattern search)
# --------------------------------------------------------------------------- #
class EventEmbeddingRepository:
    """Store and query event embeddings for the 15-year historical pattern agent."""

    def __init__(self):
        self.col = db.collection("event_embeddings")

    async def insert(self, event):
        from datetime import datetime, timezone

        from ..modules.ai.memory import embed
        from . import models

        doc_id = event.get("id") or _new_id()
        existing = self.col.find_one({"id": doc_id})
        if existing:
            return existing
        doc = {
            "id": doc_id,
            "eventType": event.get("eventType") or event.get("event_type") or "generic",
            "title": event.get("title", ""),
            "text": event.get("text") or event.get("summary") or "",
            "currency": event.get("currency"),
            "direction": event.get("direction"),
            "moveLowPips": event.get("moveLowPips"),
            "moveMedianPips": event.get("moveMedianPips"),
            "moveHighPips": event.get("moveHighPips"),
            "happenedAt": event.get("happenedAt") or _now_ms(),
            "metadata": event.get("metadata") or {},
        }
        doc["vector"] = embed(doc["text"] or doc["title"])
        if is_postgres_enabled():
            async with session_scope() as session:
                session.add(models.EventEmbedding(
                    id=doc["id"],
                    event_type=doc["eventType"],
                    title=doc["title"],
                    text=doc["text"],
                    currency=doc.get("currency"),
                    direction=doc.get("direction"),
                    move_low_pips=float(doc["moveLowPips"]) if doc.get("moveLowPips") is not None else None,
                    move_median_pips=float(doc["moveMedianPips"]) if doc.get("moveMedianPips") is not None else None,
                    move_high_pips=float(doc["moveHighPips"]) if doc.get("moveHighPips") is not None else None,
                    happened_at=datetime.fromtimestamp(doc["happenedAt"] / 1000, tz=timezone.utc),
                    embedding=doc["vector"],
                    metadata_json=doc["metadata"],
                ))
                return doc
        self.col.insert(doc)
        return doc

    async def update_embedding(self, event_id, vector):
        """Store the pgvector embedding for an event (Postgres only)."""
        if not is_postgres_enabled():
            return None
        from . import models

        async with session_scope() as session:
            row = await session.get(models.EventEmbedding, event_id)
            if row is None:
                return None
            row.embedding = vector
            return event_id

    async def similarity_search(self, vector, k=5, event_type=None):
        """Postgres pgvector similarity search; falls back to JSON cosine ranking."""
        if is_postgres_enabled():
            from sqlalchemy import select

            from . import models

            async with session_scope() as session:
                q = (
                    select(models.EventEmbedding)
                    .order_by(models.EventEmbedding.embedding.cosine_distance(vector))
                    .limit(k)
                )
                if event_type:
                    q = q.where(models.EventEmbedding.event_type == event_type)
                rows = await session.execute(q)
                return [_as_model(models.EventEmbedding, r._mapping).to_dict() for r in rows]
        from ..modules.ai.memory import cosine_similarity

        rows = self.col.find({"eventType": event_type} if event_type else {})
        scored = []
        for r in rows:
            vec = r.get("vector")
            if not vec or len(vec) == 0:
                continue
            scored.append({**r, "score": round(cosine_similarity(vector, vec), 4)})
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:k]


news_repository = NewsRepository()
custom_agent_repository = CustomAgentRepository()
decision_repository = DecisionRepository()
position_repository = PositionRepository()
event_embedding_repository = EventEmbeddingRepository()

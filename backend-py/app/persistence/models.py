"""SQLAlchemy models for the institutional persistence layer.

All financial values are stored as PostgreSQL NUMERIC and handled as Python
``Decimal`` in application code (NO FLOATS for prices, pips, SL, TP, risk).
``EventEmbedding`` uses pgvector for the 15-year historical pattern search.
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pgvector.sqlalchemy import Vector


class Base(AsyncAttrs, DeclarativeBase):
    pass


def _now():
    return datetime.now(timezone.utc)


class NewsSource(Base):
    """Dynamic news source (RSS / Telegram / X / Web / Financial API / Regulatory)."""

    __tablename__ = "news_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="rss")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reliability: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("0.70"))
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.source_type,
            "config": self.config or {},
            "priority": self.priority,
            "enabled": self.enabled,
            "reliability": float(self.reliability) if self.reliability is not None else 0.7,
            "lastCollectedAt": self.last_collected_at.isoformat() if self.last_collected_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class NewsItem(Base):
    """Processed news item produced by the real collectors and the analysis engine."""

    __tablename__ = "news_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sentiment: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    impact: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    trust_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    entities: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def to_dict(self):
        return {
            "id": self.id,
            "sourceId": self.source_id,
            "source": self.source,
            "title": self.title,
            "summary": self.summary,
            "content": self.content,
            "url": self.url,
            "category": self.category,
            "sentiment": float(self.sentiment) if self.sentiment is not None else None,
            "impact": float(self.impact) if self.impact is not None else None,
            "confidence": float(self.confidence) if self.confidence is not None else None,
            "trustScore": float(self.trust_score) if self.trust_score is not None else None,
            "entities": self.entities or [],
            "keywords": self.keywords or [],
            "analysis": self.analysis or {},
            "time": int(self.time.timestamp() * 1000) if self.time else int(self.ingested_at.timestamp() * 1000),
            "ingestedAt": int(self.ingested_at.timestamp() * 1000),
            "sourceType": (self.raw or {}).get("sourceType", "unknown"),
        }


class CustomAIAgent(Base):
    """User-defined AI agent with a bounded voting weight (0-20%) and encrypted key."""

    __tablename__ = "custom_ai_agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False, default="free_local")
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    voting_weight: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("0.05"))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    template: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self, include_key=False):
        return {
            "id": self.id,
            "name": self.name,
            "provider_type": self.provider_type,
            "providerType": self.provider_type,
            "model_name": self.model_name,
            "modelName": self.model_name,
            "system_prompt": self.system_prompt,
            "systemPrompt": self.system_prompt,
            "voting_weight": float(self.voting_weight) if self.voting_weight is not None else 0.0,
            "votingWeight": float(self.voting_weight) if self.voting_weight is not None else 0.0,
            "api_key_encrypted": bool(self.api_key_encrypted),
            "apiKeyEncrypted": bool(self.api_key_encrypted),
            "base_url": self.base_url,
            "enabled": self.enabled,
            "template": self.template,
            "createdAt": int(self.created_at.timestamp() * 1000) if self.created_at else None,
        }


class AIDecision(Base):
    """One AI decision produced by the 5-agent gather + strict 80/20 consensus."""

    __tablename__ = "ai_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    weights: Mapped[dict] = mapped_column(JSON, default=dict)
    agent_scores: Mapped[list] = mapped_column(JSON, default=list)
    risk_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    news_ids: Mapped[list] = mapped_column(JSON, default=list)
    entry: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    lot_size: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    expected_pips: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="no_trade")
    recommendation: Mapped[dict] = mapped_column(JSON, default=dict)
    xai: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "direction": self.direction,
            "confidence": float(self.confidence) if self.confidence is not None else 0.0,
            "weights": self.weights or {},
            "agentScores": self.agent_scores or [],
            "riskApproved": self.risk_approved,
            "newsIds": self.news_ids or [],
            "entry": float(self.entry) if self.entry is not None else None,
            "stopLoss": float(self.stop_loss) if self.stop_loss is not None else None,
            "takeProfit": float(self.take_profit) if self.take_profit is not None else None,
            "lotSize": float(self.lot_size) if self.lot_size is not None else None,
            "expectedPips": float(self.expected_pips) if self.expected_pips is not None else None,
            "status": self.status,
            "recommendation": self.recommendation or {},
            "xai": self.xai or {},
            "timestamp": int(self.timestamp.timestamp() * 1000) if self.timestamp else None,
        }


class Position(Base):
    """Open MT5 position synced into the database (NUMERIC financial fields)."""

    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    lot_size: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0.01"))
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    profit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    initial_confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    news_ids: Mapped[list] = mapped_column(JSON, default=list)
    mt5_ticket: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "lotSize": float(self.lot_size) if self.lot_size is not None else 0.0,
            "entry": float(self.entry_price) if self.entry_price is not None else None,
            "stopLoss": float(self.stop_loss) if self.stop_loss is not None else None,
            "takeProfit": float(self.take_profit) if self.take_profit is not None else None,
            "currentPrice": float(self.current_price) if self.current_price is not None else None,
            "profit": float(self.profit) if self.profit is not None else None,
            "status": self.status,
            "initialConfidence": float(self.initial_confidence) if self.initial_confidence is not None else None,
            "newsIds": self.news_ids or [],
            "mt5Ticket": self.mt5_ticket,
            "openedAt": int(self.opened_at.timestamp() * 1000) if self.opened_at else None,
            "closedAt": int(self.closed_at.timestamp() * 1000) if self.closed_at else None,
        }


class EventEmbedding(Base):
    """pgvector embedding of a historical event for 15-year pattern matching."""

    __tablename__ = "event_embeddings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="")
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(8), nullable=True)
    move_low_pips: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    move_median_pips: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    move_high_pips: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    happened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding: Mapped[list] = mapped_column(Vector(96), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    def to_dict(self):
        return {
            "id": self.id,
            "eventType": self.event_type,
            "title": self.title,
            "text": self.text,
            "currency": self.currency,
            "direction": self.direction,
            "moveLowPips": float(self.move_low_pips) if self.move_low_pips is not None else None,
            "moveMedianPips": float(self.move_median_pips) if self.move_median_pips is not None else None,
            "moveHighPips": float(self.move_high_pips) if self.move_high_pips is not None else None,
            "happenedAt": int(self.happened_at.timestamp() * 1000) if self.happened_at else None,
            "metadata": self.metadata_json or {},
        }

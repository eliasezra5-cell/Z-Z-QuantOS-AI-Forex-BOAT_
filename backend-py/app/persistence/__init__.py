"""PostgreSQL + pgvector persistence layer (additive migration).

New models and repositories introduced alongside the existing JSON file store.
When ``DATABASE_URL`` is configured (and ``POSTGRES_ENABLED``), the repository
layer routes reads/writes to PostgreSQL; otherwise it transparently falls back
to the JSON store so the locked frontend never breaks.
"""
from .db import get_engine as engine, session_factory, is_postgres_enabled, init_models
from .repository import (
    news_repository,
    custom_agent_repository,
    decision_repository,
    position_repository,
    event_embedding_repository,
)

__all__ = [
    "engine",
    "session_factory",
    "is_postgres_enabled",
    "init_models",
    "news_repository",
    "custom_agent_repository",
    "decision_repository",
    "position_repository",
    "event_embedding_repository",
]

"""SQLAlchemy async engine + session management for the persistence layer.

Graceful degradation: if Postgres is not configured, ``get_engine`` returns
None and callers use the JSON-store fallback repositories instead.
"""
from contextlib import asynccontextmanager

from ..config import settings
from ..foundation.logger import logger

_engine = None
_session_factory = None
_enabled = False


def is_postgres_enabled():
    """True when a DATABASE_URL is configured and Postgres is explicitly enabled."""
    return bool(settings.DATABASE_URL and settings.POSTGRES_ENABLED)


def get_engine():
    """Lazily create the async SQLAlchemy engine (created once)."""
    global _engine, _session_factory, _enabled
    if _engine is not None:
        return _engine
    if not is_postgres_enabled():
        return None
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        _engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_pre_ping=True,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        _enabled = True
        logger.info(f"PostgreSQL engine initialized: {settings.DATABASE_URL.split('@')[-1]}")
    except Exception as exc:  # noqa: BLE001 - fall back to JSON store on any wiring error
        logger.warn(f"PostgreSQL unavailable ({exc}); falling back to JSON store")
        _engine = None
        _session_factory = None
        _enabled = False
    return _engine


def session_factory():
    get_engine()
    return _session_factory


@asynccontextmanager
async def session_scope():
    """Async context manager yielding a session; rolls back on exception."""
    factory = session_factory()
    if factory is None:
        raise RuntimeError("PostgreSQL is not configured")
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_models():
    """Create tables (incl. pgvector extension) when Postgres is enabled."""
    eng = get_engine()
    if eng is None:
        logger.info("Persistence layer running on JSON store (Postgres not configured)")
        return False
    from . import models  # noqa: F401 - register models with the metadata

    async with eng.begin() as conn:
        from sqlalchemy import text

        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(models.Base.metadata.create_all)
        # Additive column for the full-article news body. ``IF NOT EXISTS`` makes
        # this idempotent so existing deployments gain the column on boot without
        # a manual migration, while fresh databases get it from ``create_all``.
        await conn.execute(
            text("ALTER TABLE IF EXISTS news_items ADD COLUMN IF NOT EXISTS content TEXT")
        )
    logger.info("PostgreSQL schema ensured (pgvector extension enabled)")
    return True

"""Celery task: autonomous news polling across all configured sources.

Runs on the beat schedule. Polls every enabled source via the realtime
collectors, persists items through the repository, and publishes to the
ingest pipeline + Redis Pub/Sub ``ws_news``. Falls back to a direct (blocking)
call when Celery is unavailable so it can be invoked from the scheduler.
"""
from ..foundation.logger import logger
from ..modules.news.realtime.registry import poll_all_collectors

from .celery_app import get_celery_app


def _poll_news(limit_per_source=10):
    import asyncio

    return asyncio.run(poll_all_collectors(limit_per_source))


def poll_news(limit_per_source=10):
    """Celery task entry point."""
    return _poll_news(limit_per_source)


def poll_news_sync(limit_per_source=10):
    """Blocking wrapper usable without a broker (scheduler / tests)."""
    return _poll_news(limit_per_source)


_app = get_celery_app()
if _app is not None:
    poll_news = _app.task(name="app.tasks.news_collector.poll_news", bind=True)(lambda self, *a, **k: _poll_news(*a, **k))


def init_news_polling():
    logger.info("Celery news polling worker initialized")
    return poll_news_sync

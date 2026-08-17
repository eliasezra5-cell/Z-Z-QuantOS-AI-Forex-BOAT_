"""Autonomous news polling autopilot (additive).

Starts the news collector on the in-process scheduler so every configured
source is polled continuously without requiring a separate ``celery beat``
process. Runs ``app.tasks.news_collector.poll_news_sync`` every
``NEWS_POLL_INTERVAL_SECONDS`` (default 60s). When Celery + Redis are available
the same task is also published on the Celery beat schedule; this autopilot
guarantees autonomous fetching even with no broker running.

The poll cycle: fetch from every enabled source -> dedupe -> persist through
the repository -> publish to ``ws_news`` Redis Pub/Sub and the ``news:ingest``
pipeline (which triggers the 5-agent AI decision pipeline via ``news:processed``).
"""
from ...config import settings
from ...foundation.logger import logger
from ...foundation.scheduler import scheduler
from ...tasks.news_collector import poll_news_sync

JOB_ID = "autonomous-news-poll"
DEFAULT_POLL_SECONDS = 60
DEFAULT_LIMIT_PER_SOURCE = 10


def _run_poll():
    return poll_news_sync(DEFAULT_LIMIT_PER_SOURCE)


def init_news_autopilot():
    """Register (idempotently) the autonomous polling job on the scheduler."""
    if scheduler.jobs.get(JOB_ID):
        return JOB_ID
    seconds = max(10, int(settings.NEWS_POLL_INTERVAL_SECONDS or DEFAULT_POLL_SECONDS))
    scheduler.register({
        "id": JOB_ID,
        "intervalMs": seconds * 1000,
        "handler": _run_poll,
    })
    logger.info(f"News autopilot registered: polling every {seconds}s")
    return JOB_ID

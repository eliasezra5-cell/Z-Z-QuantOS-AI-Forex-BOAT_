"""Daily AI learning tasks (Phase 2, Module 2).

Runs mistake analysis + pattern persistence + experience replay mirror on a
daily schedule. The tasks run synchronously via ``.apply()`` when no broker is
configured; Celery dispatches them on the beat schedule otherwise.
"""
import time

from ..foundation.logger import logger


def run_daily_learning():
    """Persist pattern win-rates, run mistake analysis and mirror pgvector.

    Returns a summary dict used by both the Celery task and the scheduler job.
    """
    from ..modules.ai.learning import learning_engine
    from ..modules.ai.experience_replay import experience_replay

    patterns = learning_engine.persist_pattern_stats()
    mistakes = learning_engine.mistake_analysis()
    replay = experience_replay.record_to_pgvector()
    summary = {
        "task": "learning-daily",
        "patternsPersisted": len(patterns),
        "totalLosses": mistakes["totalLosses"],
        "topMistakeReasons": [b.get("reason") for b in mistakes["byReason"][:3]],
        "pgvectorMirrored": replay,
        "timestamp": int(time.time() * 1000),
    }
    logger.info(f"Daily learning run complete: {summary['patternsPersisted']} patterns, {summary['totalLosses']} losses reviewed")
    return summary


def run_daily_learning_task():
    """Synchronous entry point (called by scheduler job and .apply())."""
    return run_daily_learning()


try:
    from .celery_app import celery_app

    if celery_app is not None:

        @celery_app.task(name="app.tasks.learning_tasks.run_daily_learning")
        def run_daily_learning_celery():
            return run_daily_learning()

except Exception:  # noqa: BLE001 - Celery optional; scheduler fallback covers it
    celery_app = None

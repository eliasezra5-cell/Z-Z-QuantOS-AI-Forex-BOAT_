"""Daily mistake-analysis Celery task (Phase 2, Module 2).

Runs the offline mistake-analysis engine on the daily beat schedule and
persists the aggregated pattern win-rate table. Works synchronously via
``.apply()`` when no broker is configured, exactly like the existing
``app.tasks.learning_tasks`` module.
"""
import time

from ..foundation.logger import logger


def run_daily_mistake_analysis():
    """Analyze losing trades and persist pattern win rates.

    Returns a summary dict used by both the Celery task and scheduler jobs.
    """
    from ..modules.ai.mistake_analysis import mistake_analyzer
    from ..modules.ai.pattern_learning import pattern_learning

    patterns = pattern_learning.persist()
    analysis = mistake_analyzer.analyze()
    summary = {
        "task": "mistake-analysis-daily",
        "patternsPersisted": len(patterns),
        "totalLosses": analysis["totalLosses"],
        "topRootCauses": [b.get("root_cause") for b in analysis["byRootCause"][:3]],
        "timestamp": int(time.time() * 1000),
    }
    logger.info(
        f"Daily mistake analysis complete: {summary['patternsPersisted']} patterns, "
        f"{summary['totalLosses']} losses, top cause {summary['topRootCauses'][:1]}"
    )
    return summary


def run_daily_mistake_analysis_task():
    """Synchronous entry point (called by scheduler job and .apply())."""
    return run_daily_mistake_analysis()


try:
    from .celery_app import celery_app

    if celery_app is not None:

        @celery_app.task(name="app.tasks.mistake_analysis.run_daily_mistake_analysis")
        def run_daily_mistake_analysis_celery():
            return run_daily_mistake_analysis()

except Exception:  # noqa: BLE001 - Celery optional; scheduler fallback covers it
    celery_app = None

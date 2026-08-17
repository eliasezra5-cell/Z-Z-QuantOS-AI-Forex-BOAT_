"""Celery task: run the institutional decision pipeline on demand."""
import asyncio

from ..foundation.logger import logger
from ..modules.ai.decision_pipeline import decision_pipeline

from .celery_app import get_celery_app


def _run_pipeline(symbol="XAUUSD"):
    return asyncio.run(decision_pipeline.analyze(symbol))


def run_decision_pipeline(symbol="XAUUSD"):
    """Celery task entry point."""
    return _run_pipeline(symbol)


def run_decision_pipeline_sync(symbol="XAUUSD"):
    """Blocking wrapper usable without a broker."""
    return _run_pipeline(symbol)


_app = get_celery_app()
if _app is not None:
    run_decision_pipeline = _app.task(name="app.tasks.decision_pipeline.run_decision_pipeline")(
        lambda *a, **k: _run_pipeline(*a, **k)
    )


def init_decision_task():
    logger.info("Celery decision pipeline task initialized")
    return run_decision_pipeline_sync

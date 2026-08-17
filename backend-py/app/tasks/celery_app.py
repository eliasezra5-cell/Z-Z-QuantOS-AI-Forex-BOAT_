"""Celery application + beat schedule for autonomous background work.

Workers run ``app.tasks.celery_app worker``; the news polling worker
(``app.tasks.news_collector.poll_news``) runs on the beat schedule
(``NEWS_POLL_INTERVAL_SECONDS``, default 60s). When Redis is not configured
the Celery app is created but tasks simply cannot be dispatched to a broker —
callers can still run them synchronously via ``.apply()``.
"""
from ..config import settings

broker = settings.CELERY_BROKER_URL or settings.REDIS_URL or "memory://"
backend = settings.CELERY_RESULT_BACKEND or settings.REDIS_URL or None

celery_app = None
try:
    from celery import Celery

    celery_app = Celery(
        "quantos",
        broker=broker,
        backend=backend,
        include=[
            "app.tasks.news_collector",
            "app.tasks.decision_pipeline",
            "app.tasks.learning_tasks",
            "app.tasks.mistake_analysis",
            "app.tasks.daily_report_delivery",
        ],
    )
    celery_app.conf.task_serializer = "json"
    celery_app.conf.result_serializer = "json"
    celery_app.conf.accept_content = ["json"]
    celery_app.conf.timezone = settings.SCHEDULER_TZ or "UTC"
    celery_app.conf.broker_connection_retry_on_startup = True

    try:
        from ..foundation.tracing import setup_celery_tracing

        setup_celery_tracing(celery_app)
    except Exception:  # noqa: BLE001 - tracing optional
        pass

    if settings.CELERY_BEAT_SCHEDULE_ENABLED:
        celery_app.conf.beat_schedule = {
            "poll-real-news": {
                "task": "app.tasks.news_collector.poll_news",
                "schedule": max(10, int(settings.NEWS_POLL_INTERVAL_SECONDS or 60)),
            },
            "run-daily-learning": {
                "task": "app.tasks.learning_tasks.run_daily_learning",
                "schedule": max(60, int(settings.LEARNING_DAILY_INTERVAL_SECONDS or 86400)),
            },
            "run-daily-mistake-analysis": {
                "task": "app.tasks.mistake_analysis.run_daily_mistake_analysis",
                "schedule": max(60, int(settings.LEARNING_DAILY_INTERVAL_SECONDS or 86400)),
            },
            "run-daily-report-delivery": {
                "task": "app.tasks.daily_report_delivery.run_daily_report_delivery",
                "schedule": max(60, int(settings.REPORT_DELIVERY_INTERVAL_SECONDS or 86400)),
            },
        }
except Exception as exc:  # noqa: BLE001 - celery optional at runtime
    celery_app = None


def get_celery_app():
    return celery_app

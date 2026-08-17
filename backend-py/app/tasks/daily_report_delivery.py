"""Daily report delivery task (Feature 4, additive).

Generates the daily report and delivers it over the configured channels
(email, WhatsApp, Telegram). Each channel is independently toggled and fails
safe: when credentials are missing the delivery is recorded as "pending" and
skipped silently — a single broken channel never blocks the others or the
scheduler. The report renderer (``reports/renderers.py``) and the integration
clients (``telegram_bot`` / ``whatsapp_client`` / ``email_client``) are reused
as-is.
"""
import time

from ..foundation.logger import logger
from ..config import settings


def run_daily_report_delivery():
    """Generate + deliver the daily report over every configured channel.

    Returns a summary dict consumed by the Celery task and the scheduler job.
    """
    from ..modules.reports.service import generate_report
    from ..modules.reports.renderers import to_markdown, to_html

    report = generate_report("daily")
    markdown = to_markdown(report)
    html = to_html(report)
    subject = f"{settings.EMAIL_SUBJECT_PREFIX} Daily Report - {_report_date(report)}"

    channels = {}
    channels["email"] = _deliver_safe("email", lambda: _deliver_email(subject, html, markdown))
    channels["whatsapp"] = _deliver_safe("whatsapp", lambda: _deliver_whatsapp(markdown))
    channels["telegram"] = _deliver_safe("telegram", lambda: _deliver_telegram(markdown))

    delivered = [k for k, v in channels.items() if v and v.get("status") == "sent"]
    summary = {
        "task": "daily-report-delivery",
        "reportId": report["id"],
        "generatedAt": report["generatedAt"],
        "channels": channels,
        "delivered": delivered,
        "timestamp": int(time.time() * 1000),
    }
    logger.info(f"Daily report delivered via {delivered or 'no channel'}: {report['id']}")
    return summary


def _report_date(report):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(report.get("generatedAt", time.time() * 1000) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _deliver_safe(channel, fn):
    """Run one channel; a broken channel never blocks the others."""
    try:
        return fn() or _skipped(channel, "no result")
    except Exception as err:  # noqa: BLE001 - record and continue
        logger.error(f"Delivery channel {channel} failed", {"error": str(err)})
        return _skipped(channel, f"error: {err}")


def _deliver_email(subject, html, markdown):
    if not settings.REPORT_DELIVERY_EMAIL_ENABLED:
        return _skipped("email", "REPORT_DELIVERY_EMAIL_ENABLED=false")
    from ..modules.integrations.email_client import email_client

    return email_client.send_email(subject, html_body=html, text_body=markdown)


def _deliver_whatsapp(markdown):
    if not settings.REPORT_DELIVERY_WHATSAPP_ENABLED:
        return _skipped("whatsapp", "REPORT_DELIVERY_WHATSAPP_ENABLED=false")
    from ..modules.integrations.whatsapp_client import whatsapp_alert_client

    return whatsapp_alert_client.send_text(whatsapp_alert_client.admin_number, markdown)


def _deliver_telegram(markdown):
    if not settings.REPORT_DELIVERY_TELEGRAM_ENABLED:
        return _skipped("telegram", "REPORT_DELIVERY_TELEGRAM_ENABLED=false")
    from ..modules.integrations.telegram_bot import telegram_bot

    return telegram_bot.send_message(telegram_bot.chat_id, _telegram_safe(markdown))


def _telegram_safe(text):
    """Escape HTML-significant chars so markdown survives parse_mode=HTML."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _skipped(channel, detail):
    return {"integrationId": channel, "kind": "message", "status": "skipped", "direction": "outbound", "detail": detail}


def run_daily_report_delivery_task():
    """Synchronous entry point (called by scheduler job and .apply())."""
    return run_daily_report_delivery()


JOB_ID = "daily-report-delivery"
DEFAULT_DELIVERY_SECONDS = 86400


def _run_scheduled():
    return run_daily_report_delivery()


def init_daily_report_delivery():
    """Register (idempotently) the daily report delivery job on the scheduler."""
    from ..foundation.scheduler import scheduler

    if scheduler.jobs.get(JOB_ID):
        return JOB_ID
    seconds = max(60, int(getattr(settings, "REPORT_DELIVERY_INTERVAL_SECONDS", None) or DEFAULT_DELIVERY_SECONDS))
    scheduler.register({
        "id": JOB_ID,
        "intervalMs": seconds * 1000,
        "handler": _run_scheduled,
    })
    logger.info(f"Daily report delivery registered: every {seconds}s")
    return JOB_ID


try:
    from .celery_app import celery_app

    if celery_app is not None:

        @celery_app.task(name="app.tasks.daily_report_delivery.run_daily_report_delivery")
        def run_daily_report_delivery_celery():
            return run_daily_report_delivery()

except Exception:  # noqa: BLE001 - Celery optional; scheduler fallback covers it
    celery_app = None

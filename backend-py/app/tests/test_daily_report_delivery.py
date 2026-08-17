"""Tests for daily report delivery (Feature 4, additive).

Covers the email SMTP client fail-safe contract, the independent per-channel
toggles in the delivery task, Telegram HTML-safe rendering, and idempotent
scheduler registration.

Run with: python3 -m pytest app/tests/test_daily_report_delivery.py -q
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_report_delivery_test")
os.environ["POSTGRES_ENABLED"] = "false"
os.environ["DATABASE_URL"] = ""

from app.foundation.json_store import db  # noqa: E402
from app.modules.integrations.email_client import EmailClient  # noqa: E402
from app.tasks import daily_report_delivery as delivery  # noqa: E402
from app.tasks.daily_report_delivery import (  # noqa: E402
    init_daily_report_delivery,
    run_daily_report_delivery,
)

SUBJECT = "QuantOS AI Daily Report"
HTML = "<html><body>hello</body></html>"
TEXT = "# QuantOS AI Report - daily\n- **Balance:** $10,000"


def _reset():
    db.collection("integration_outbox").clear()
    db.collection("positions").clear()
    db.collection("ai_decisions").clear()


# --------------------------------------------------------------------------- #
# Email SMTP client
# --------------------------------------------------------------------------- #
class TestEmailClient:
    def test_unconfigured_records_pending_and_never_raises(self):
        _reset()
        client = EmailClient(host="", from_addr="")
        result = client.send_email(SUBJECT, html_body=HTML, text_body=TEXT)
        assert result["integrationId"] == "email"
        assert result["status"] == "pending"
        assert "SMTP not configured" in result["detail"]
        row = db.collection("integration_outbox").find({"integrationId": "email"})
        assert len(row) == 1

    def test_no_recipient_records_pending(self):
        _reset()
        client = EmailClient(host="smtp.example.com", from_addr="quantos@example.com")
        result = client.send_email(SUBJECT, to="")
        assert result["status"] == "pending"
        assert "no recipient" in result["detail"]

    def test_configured_sends_via_smtplib(self):
        _reset()
        client = EmailClient(host="smtp.example.com", from_addr="quantos@example.com", starttls=True)
        with mock.patch("app.modules.integrations.email_client.smtplib.SMTP") as smtp_cls:
            smtp_cls.return_value.__enter__.return_value = smtp_cls.return_value
            result = client.send_email(SUBJECT, html_body=HTML, text_body=TEXT, to="ops@example.com")
        assert result["status"] == "sent"
        smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=client.timeout_seconds)
        smtp = smtp_cls.return_value
        smtp.starttls.assert_called_once_with()
        smtp.sendmail.assert_called_once()
        args = smtp.sendmail.call_args[0]
        assert args[0] == "quantos@example.com"
        assert args[1] == ["ops@example.com"]

    def test_smtp_failure_records_failed_never_raises(self):
        _reset()
        client = EmailClient(host="smtp.example.com", from_addr="quantos@example.com")
        with mock.patch(
            "app.modules.integrations.email_client.smtplib.SMTP",
            side_effect=ConnectionError("boom"),
        ):
            result = client.send_email(SUBJECT, text_body=TEXT, to="ops@example.com")
        assert result["status"] == "failed"
        assert "boom" in result["detail"]
        assert client.last_error == "boom"

    def test_is_configured(self):
        assert EmailClient(host="", from_addr="").is_configured() is False
        assert EmailClient(host="smtp.example.com", from_addr="a@b.co").is_configured() is True

    def test_self_test_reports_missing_config(self):
        client = EmailClient(host="", from_addr="")
        assert client.self_test()["success"] is False


# --------------------------------------------------------------------------- #
# Delivery task
# --------------------------------------------------------------------------- #
class TestDeliveryTask:
    def test_runs_and_returns_summary_when_unconfigured(self):
        _reset()
        summary = run_daily_report_delivery()
        assert summary["task"] == "daily-report-delivery"
        assert summary["reportId"]
        assert set(summary["channels"]) == {"email", "whatsapp", "telegram"}
        assert summary["delivered"] == []

    def test_channels_gated_independently_by_toggles(self):
        _reset()
        with mock.patch.object(delivery.settings, "REPORT_DELIVERY_EMAIL_ENABLED", False):
            with mock.patch.object(delivery.settings, "REPORT_DELIVERY_WHATSAPP_ENABLED", False):
                with mock.patch.object(delivery.settings, "REPORT_DELIVERY_TELEGRAM_ENABLED", True):
                    summary = run_daily_report_delivery()
        assert summary["channels"]["email"]["status"] == "skipped"
        assert summary["channels"]["whatsapp"]["status"] == "skipped"
        assert summary["channels"]["telegram"]["status"] == "pending"

    def test_whatsapp_delivery_uses_admin_number(self):
        _reset()
        wa = mock.MagicMock()
        wa.admin_number = "+1000000"
        with mock.patch("app.modules.integrations.whatsapp_client.whatsapp_alert_client", wa):
            delivery._deliver_whatsapp(TEXT)
        wa.send_text.assert_called_once()
        args = wa.send_text.call_args[0]
        assert args[0] == "+1000000"
        assert TEXT in args[1]

    def test_telegram_escapes_html_chars(self):
        _reset()
        tb = mock.MagicMock()
        tb.chat_id = "123"
        with mock.patch("app.modules.integrations.telegram_bot.telegram_bot", tb):
            delivery._deliver_telegram("<b>&bold> summary")
        assert tb.send_message.call_args[0][1] == "&lt;b&gt;&amp;bold&gt; summary"

    def test_single_broken_channel_does_not_block_others(self):
        _reset()
        wa = mock.MagicMock()
        wa.admin_number = "+1000000"
        wa.send_text.side_effect = Exception("whatsapp down")
        with mock.patch("app.modules.integrations.whatsapp_client.whatsapp_alert_client", wa):
            summary = run_daily_report_delivery()
        assert summary["channels"]["whatsapp"]["status"] == "skipped"
        assert "whatsapp" not in summary["delivered"]
        assert summary["channels"]["email"]["status"] in ("pending", "sent")


# --------------------------------------------------------------------------- #
# Scheduler registration (autopilot pattern)
# --------------------------------------------------------------------------- #
class TestSchedulerRegistration:
    def test_init_registers_job(self):
        from app.foundation.scheduler import scheduler

        delivery.JOB_ID = "daily-report-delivery-test"
        job_id = init_daily_report_delivery()
        try:
            assert job_id == delivery.JOB_ID
            assert delivery.JOB_ID in scheduler.jobs
            assert scheduler.jobs[delivery.JOB_ID]["intervalMs"] >= 60 * 1000
        finally:
            scheduler.disable(delivery.JOB_ID)
            scheduler.jobs.pop(delivery.JOB_ID, None)

    def test_init_is_idempotent(self):
        from app.foundation.scheduler import scheduler

        delivery.JOB_ID = "daily-report-delivery-test2"
        first = init_daily_report_delivery()
        second = init_daily_report_delivery()
        try:
            assert first == second == delivery.JOB_ID
            assert list(scheduler.jobs).count(delivery.JOB_ID) == 1
        finally:
            scheduler.disable(delivery.JOB_ID)
            scheduler.jobs.pop(delivery.JOB_ID, None)

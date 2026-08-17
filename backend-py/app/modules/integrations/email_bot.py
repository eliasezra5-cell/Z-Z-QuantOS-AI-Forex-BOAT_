"""Email conversation bot (additive).

Adds a third confirmation/chat channel (Gmail / any IMAP mailbox) alongside
Telegram and WhatsApp. Polls the configured IMAP inbox for unread mail from
allowed senders, routes each message through the same assistant as the other
channels ("1"/"2" approve/reject the latest pending suggested trade, any other
text goes through the conversational assistant), and replies over SMTP using
the existing email client.

Configuration (env):
  - IMAP_HOST / IMAP_PORT / IMAP_USER / IMAP_PASSWORD  IMAP inbox access
  - EMAIL_ALLOWED_SENDERS  comma-separated senders allowed to give commands
  - EMAIL_FROM / EMAIL_TO  SMTP reply settings (existing email client)

The bot degrades gracefully: when IMAP credentials are missing it skips the
poll cycle and never raises or blocks the rest of the system.
"""
import email as email_parser
import imaplib
import threading
import time
from email.header import decode_header
from email.utils import parseaddr

from ...foundation.logger import logger

DEFAULT_POLL_SECONDS = 60


def _env(key, default=""):
    import os

    return os.environ.get(key, default)


class EmailConversationBot:
    """Poll the IMAP inbox, route commands, and reply over SMTP."""

    def __init__(self):
        self.host = _env("IMAP_HOST")
        try:
            self.port = int(_env("IMAP_PORT") or 993)
        except (TypeError, ValueError):
            self.port = 993
        self.user = _env("IMAP_USER")
        self.password = _env("IMAP_PASSWORD")
        allowed = _env("EMAIL_ALLOWED_SENDERS")
        self.allowed_senders = [s.strip().lower() for s in allowed.split(",") if s.strip()] if allowed else []
        self.last_error = None

    def is_configured(self):
        return bool(self.host and self.user and self.password)

    def poll_once(self):
        """Process unread mail from allowed senders (returns processed count)."""
        if not self.is_configured():
            return 0
        conn = None
        try:
            conn = imaplib.IMAP4_SSL(self.host, self.port)
            conn.login(self.user, self.password)
            conn.select("INBOX")
            _typ, data = conn.search(None, "UNSEEN")
            ids = (data[0] or b"").split()
            processed = 0
            for num in ids:
                try:
                    _typ, msg_data = conn.fetch(num, "(RFC822)")
                    if not msg_data or not msg_data[0]:
                        continue
                    msg = email_parser.message_from_bytes(msg_data[0][1])
                    if self._handle_msg(msg):
                        processed += 1
                    conn.store(num, "+FLAGS", "\\Seen")
                except Exception as err:  # noqa: BLE001 - per-message failures isolated
                    logger.error("email bot message failed", {"error": str(err)})
            return processed
        except Exception as err:  # noqa: BLE001 - IMAP failures never propagate
            self.last_error = str(err)
            logger.error("email bot poll failed", {"error": str(err)})
            return 0
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:  # noqa: BLE001
                    pass

    def _handle_msg(self, msg):
        sender = parseaddr(msg.get("From", ""))[1].strip().lower()
        if not sender or (self.allowed_senders and sender not in self.allowed_senders):
            return False
        text = self._extract_text(msg)
        if not text:
            return False
        from ..ai.conversation import process_message  # lazy import

        reply = None
        try:
            reply = self._route_command(text, sender)
        except Exception as err:  # noqa: BLE001 - never break the poll loop
            reply = f"Sorry, I couldn't process that: {err}"
        if reply:
            self._reply(sender, reply)
        return True

    def _route_command(self, text, sender=""):
        """Route a message like the other channels: 1/2 approve/reject, else chat.

        Non-command text is also ingested as manual-forward news (persist +
        ws_news publish) so it appears in the News Terminal AI News Feed.
        """
        raw_text = (text or "").strip()
        low = raw_text.lower()
        if low in ("1", "2"):
            from ..execution.auto_controller import auto_trade_controller  # lazy import

            pending = [r for r in auto_trade_controller.suggested_trades(status="pending")]
            if not pending:
                return "No pending AI suggestion to review."
            latest = max(pending, key=lambda r: r.get("createdAt", 0))
            if low == "1":
                updated = auto_trade_controller.approve_suggested(latest["id"])
                action = "approved" if updated else "missing"
            else:
                updated = auto_trade_controller.reject_suggested(latest["id"])
                action = "rejected" if updated else "missing"
            return f"{latest.get('symbol')} {latest.get('side')} ({action})"
        if low.startswith("/approve "):
            return self._approve_by_id(raw_text.split(None, 1)[1])
        if low.startswith("/reject "):
            return self._reject_by_id(raw_text.split(None, 1)[1])
        if raw_text.startswith("/"):
            # Telegram-style slash commands now work via email too. The reply
            # text is produced by the shared bot handler (no Telegram send).
            from .telegram_bot import telegram_bot

            try:
                return telegram_bot.reply_for_command(raw_text)
            except Exception as err:  # noqa: BLE001 - never break the poll loop
                return f"Sorry, I couldn't process that: {err}"
        # Manual-forward news ingestion (best-effort, never breaks the reply).
        try:
            from ..news.email_manual import ingest_email_manual

            ingest_email_manual(sender, raw_text)
        except Exception as err:  # noqa: BLE001 - news ingest must never break chat
            logger.error("email news ingest failed", {"error": str(err), "sender": sender})
        from ..ai.conversation import process_message

        return process_message(raw_text)

    def _approve_by_id(self, suggestion_id):
        from ..execution.auto_controller import auto_trade_controller  # lazy import

        row = auto_trade_controller.col.find_one({"id": suggestion_id})
        if not row:
            return f"No suggested trade with id {suggestion_id}."
        if row.get("status") != "pending":
            return f"Suggestion {suggestion_id} already {row.get('status')}."
        auto_trade_controller.approve_suggested(suggestion_id)
        return f"Approved suggestion {suggestion_id} ({row.get('symbol')})."

    def _reject_by_id(self, suggestion_id):
        from ..execution.auto_controller import auto_trade_controller  # lazy import

        row = auto_trade_controller.col.find_one({"id": suggestion_id})
        if not row:
            return f"No suggested trade with id {suggestion_id}."
        if row.get("status") != "pending":
            return f"Suggestion {suggestion_id} already {row.get('status')}."
        auto_trade_controller.reject_suggested(suggestion_id)
        return f"Rejected suggestion {suggestion_id} ({row.get('symbol')})."

    def _extract_text(self, msg):
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body += payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
        return body.strip()

    def _reply(self, to, text):
        from .email_client import email_client  # lazy import

        try:
            email_client.send_email("QuantOS AI BOAT reply", text_body=text, to=to)
        except Exception as err:  # noqa: BLE001 - reply failures never propagate
            logger.error("email bot reply failed", {"error": str(err), "to": to})


email_conversation_bot = EmailConversationBot()

_bot_loop_started = False


def init_email_bot():
    """Start the background email poll loop (single daemon thread)."""
    global _bot_loop_started
    if _bot_loop_started:
        return email_conversation_bot
    interval = max(15, int(_env("EMAIL_POLL_INTERVAL_SECONDS") or DEFAULT_POLL_SECONDS))

    def _loop():
        while True:
            time.sleep(interval)
            try:
                email_conversation_bot.poll_once()
            except Exception as err:  # noqa: BLE001 - the loop must never die
                logger.error("email bot loop error", {"error": str(err)})

    threading.Thread(target=_loop, daemon=True).start()
    _bot_loop_started = True
    logger.info(f"Email conversation bot started (poll={interval}s, imap={'configured' if email_conversation_bot.is_configured() else 'missing'})")
    return email_conversation_bot

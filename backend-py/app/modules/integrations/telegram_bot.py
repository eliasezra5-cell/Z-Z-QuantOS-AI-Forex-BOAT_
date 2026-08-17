"""Real Telegram Bot API integration (additive Module 3.2).

Replaces the simulated Telegram adapter in ``integrations/service.py`` with a
real client that talks to the Telegram Bot API over HTTPS. Commands:

  - ``/status``      -> current trading mode, capital protection, AI status
  - ``/trades``      -> open positions + recent closed trades
  - ``/approve <id>``-> mark a pending suggested trade as approved (still goes
                       through the risk engine gate when actually executed)
  - ``/reject <id>`` -> mark a pending suggested trade as rejected
  - ``/ask``         -> force an AI reply to an explicit question
  - ``/prefs``       -> list user-trained preferences
  - ``/forget``      -> delete a single preference
  - ``1`` / ``2``    -> approve / reject the most recent pending suggestion
                       (same quick-reply flow as WhatsApp and email)

The client degrades gracefully: when ``TELEGRAM_BOT_TOKEN`` is unset, all
sends are recorded to the ``integration_outbox`` collection as "pending"
(exactly like the existing simulated adapter) so the rest of the system keeps
working. Real network calls only happen when a token is configured.
"""
import time
import urllib.parse

import httpx

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...config import settings

API_BASE = "https://api.telegram.org/bot{token}/{method}"
DEFAULT_TIMEOUT_SECONDS = 10

BOT_COMMANDS = ("/status", "/trades", "/approve", "/reject", "/ask", "/prefs", "/forget")


class TelegramBotError(Exception):
    """Raised when a real Telegram API call fails."""


class TelegramBotClient:
    """Thin real client over the Telegram Bot API (sendMessage + getMe)."""

    id = "telegram"
    name = "Telegram (real Bot API)"

    def __init__(self, token=None, chat_id=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
        self.token = (token or _env("TELEGRAM_BOT_TOKEN")).strip()
        self.chat_id = chat_id or _env("TELEGRAM_CHAT_ID")
        self.timeout_seconds = timeout_seconds
        self.last_error = None

    def _url(self, method):
        return API_BASE.format(token=self.token, method=method)

    def _request(self, method, payload, timeout_seconds=None):
        if not self.token:
            return {"ok": False, "description": "TELEGRAM_BOT_TOKEN not configured", "error_code": 400}
        try:
            res = httpx.post(
                self._url(method),
                json=payload,
                timeout=timeout_seconds or self.timeout_seconds,
            )
            data = res.json()
        except Exception as err:  # noqa: BLE001 - network errors surface as structured failures
            self.last_error = str(err)
            raise TelegramBotError(f"telegram-api-error: {err}") from err
        if not data.get("ok"):
            self.last_error = data.get("description")
            raise TelegramBotError(f"telegram-api-rejected: {data.get('description')}")
        return data.get("result")

    # ------------------------------------------------------------------ #
    # Public surface
    # ------------------------------------------------------------------ #
    def self_test(self):
        """Verify the token by calling getMe against the real API."""
        if not self.token:
            return {"success": False, "detail": "TELEGRAM_BOT_TOKEN missing"}
        try:
            me = self._request("getMe", {}, timeout_seconds=6)
        except TelegramBotError as err:
            return {"success": False, "detail": str(err)}
        return {"success": True, "detail": f"connected as @{me.get('username')}"}

    def send_message(self, chat_id, text, silent=None):
        """Send a text message to a chat (real API call when token present)."""
        chat_id = chat_id or self.chat_id
        if not chat_id:
            return self._record("pending", "no chat_id configured")
        if not self.token:
            return self._record("pending", "no TELEGRAM_BOT_TOKEN configured")
        try:
            result = self._request("sendMessage", {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_notification": bool(silent),
            })
        except TelegramBotError:
            return self._record("failed", self.last_error)
        return self._record("sent", result)

    def _record(self, status, detail):
        return db.collection("integration_outbox").insert({
            "integrationId": "telegram",
            "kind": "message",
            "status": status,
            "direction": "outbound",
            "chatId": str(self.chat_id or ""),
            "detail": detail,
            "createdAt": int(time.time() * 1000),
        })

    # ------------------------------------------------------------------ #
    # Bot commands
    # ------------------------------------------------------------------ #
    def parse_command(self, text):
        """Parse an incoming message into {command, params}."""
        parts = str(text or "").strip().split()
        if not parts:
            return {"command": "unknown", "params": []}
        command = parts[0].lower()
        if command not in BOT_COMMANDS:
            return {"command": "unknown", "params": parts[1:]}
        return {"command": command, "params": parts[1:]}

    def handle_command(self, text, chat_id=None):
        """Execute a parsed command and return a human-readable reply.

        Recognized commands (``/status``, ``/trades``, ``/approve``, ``/ask``,
        ``/prefs``, ``/forget``) keep their dedicated behaviour. Any other
        message is treated as a chat message and routed through the
        conversational assistant (preference training -> intent execution ->
        free-form AI reply).
        """
        return self.send_message(chat_id, self.reply_for_command(text, chat_id))

    def reply_for_command(self, text, chat_id=None):
        """Execute a parsed command and return the reply text only (no send).

        Shares the exact command dispatch logic with :meth:`handle_command`
        but returns the human-readable reply string instead of sending it
        through the Telegram API. WhatsApp and Email use this so every
        Telegram slash command works identically on those channels.
        """
        parsed = self.parse_command(text)
        command = parsed["command"]
        params = parsed["params"]
        if command == "unknown":
            return self._handle_chat_message(text, chat_id)
        return {
            "/status": self._cmd_status,
            "/trades": self._cmd_trades,
            "/approve": self._cmd_approve,
            "/reject": self._cmd_reject,
            "/ask": self._cmd_ask,
            "/prefs": self._cmd_prefs,
            "/forget": self._cmd_forget,
        }.get(command, self._cmd_unknown)(params)

    def _handle_chat_message(self, text, chat_id):
        low = str(text or "").strip().lower()
        if low in ("1", "2"):
            return self._approve_reject_latest(low == "1")
        # Manual-forward news ingestion: any non-command text sent to the bot is
        # also pushed through the news pipeline (persist + ws_news publish) so it
        # appears in the News Terminal AI News Feed. Never breaks chat handling.
        try:
            self._ingest_manual(text, chat_id)
        except Exception as exc:  # noqa: BLE001 - news ingest must never break chat
            logger.warn(f"telegram manual news ingest failed", {"error": str(exc)})
        from ..ai.conversation import process_message  # lazy import

        try:
            return process_message(text)
        except Exception as exc:  # noqa: BLE001 - chat handling must never crash the bot
            logger.error("telegram chat handling failed", {"error": str(exc)})
            return "Sorry, something went wrong while processing that. Try /status for the current state."

    def _approve_reject_latest(self, approve):
        """Approve ('1') or reject ('2') the most recent pending suggestion.

        Mirrors the WhatsApp/email quick-reply behaviour so the same "1"/"2"
        flow works from any channel.
        """
        from ..execution.auto_controller import auto_trade_controller  # lazy import

        pending = [r for r in auto_trade_controller.suggested_trades(status="pending")]
        if not pending:
            return "No pending AI suggestion to review."
        latest = max(pending, key=lambda r: r.get("createdAt", 0))
        if approve:
            updated = auto_trade_controller.approve_suggested(latest["id"])
            action = "approved" if updated else "missing"
        else:
            updated = auto_trade_controller.reject_suggested(latest["id"])
            action = "rejected" if updated else "missing"
        return f"{latest.get('symbol')} {latest.get('side')} ({action})"

    def _ingest_manual(self, text, chat_id):
        from ..news.telegram_manual import ingest_telegram_manual

        return ingest_telegram_manual(chat_id, text)

    def _cmd_status(self, params):
        from ..execution.modes import trading_modes  # lazy import
        from ..risk.strict_risk_policy import strict_risk_policy
        from ..portfolio.service import portfolio_service

        mode = trading_modes.get_mode()
        cap = strict_risk_policy.status()
        portfolio = portfolio_service.get()
        return (
            "<b>QuantOS AI BOAT</b>\n"
            f"Trading mode: <code>{mode}</code>\n"
            f"Shield: <code>{cap['shield_level']}</code>\n"
            f"Emergency stop: <code>{cap['emergency_stop']}</code>\n"
            f"Equity: {portfolio.get('equity', 0)} | Daily loss: {portfolio.get('dailyLoss', 0)}\n"
            f"Open positions: {len(_open_positions())}"
        )

    def _cmd_trades(self, params):
        open_positions = _open_positions()
        if not open_positions:
            return "No open positions."
        lines = [f"{p['symbol']} {p['side']} vol={p['volume']} profit={p.get('profit', 0)}" for p in open_positions]
        return "<b>Open positions</b>\n" + "\n".join(lines)

    def _cmd_approve(self, params):
        """Approve a pending suggested trade by id.

        Approval goes through the real auto-trade controller
        (``approve_suggested``): it marks the trade ``accepted`` and emits
        ``suggested:trade-approved`` so the execution trigger can route it to
        the order engine. The actual order still goes through the risk engine
        pre-trade gate — nothing here bypasses it.
        """
        if not params:
            return "Usage: /approve &lt;suggestedTradeId&gt;"
        suggestion_id = params[0]
        from ..execution.auto_controller import auto_trade_controller  # lazy import

        row = auto_trade_controller.col.find_one({"id": suggestion_id})
        if not row:
            return f"No suggested trade with id <code>{suggestion_id}</code>."
        if row.get("status") != "pending":
            state = "accepted" if row.get("status") == "accepted" else row.get("status")
            return f"Suggestion <code>{suggestion_id}</code> already {state}."
        result = auto_trade_controller.approve_suggested(suggestion_id)
        if result is None:
            return f"No suggested trade with id <code>{suggestion_id}</code>."
        if isinstance(result, dict) and result.get("status") == "not-pending":
            return f"Suggestion <code>{suggestion_id}</code> already approved."
        return f"Approved suggestion <code>{suggestion_id}</code> ({row.get('symbol')}). Execution still gated by risk engine."

    def _cmd_reject(self, params):
        """Reject a pending suggested trade by id (no order is ever placed)."""
        if not params:
            return "Usage: /reject &lt;suggestedTradeId&gt;"
        suggestion_id = params[0]
        from ..execution.auto_controller import auto_trade_controller  # lazy import

        row = auto_trade_controller.col.find_one({"id": suggestion_id})
        if not row:
            return f"No suggested trade with id <code>{suggestion_id}</code>."
        if row.get("status") != "pending":
            state = "accepted" if row.get("status") == "accepted" else row.get("status")
            return f"Suggestion <code>{suggestion_id}</code> already {state}."
        auto_trade_controller.reject_suggested(suggestion_id)
        return f"Rejected suggestion <code>{suggestion_id}</code> ({row.get('symbol')})."

    def _cmd_ask(self, params):
        """Force an AI reply to an explicit question (bypasses news handling)."""
        question = " ".join(params).strip()
        if not question:
            return "Usage: /ask &lt;your question&gt;"
        from ..ai.conversation import chat_reply  # lazy import

        return chat_reply(question)

    def _cmd_prefs(self, params):
        """List the user-trained preferences stored in AI memory."""
        from ..ai.conversation import list_preferences  # lazy import

        prefs = list_preferences()
        if not prefs:
            return "No saved preferences yet. Tell me things like 'remember that never trade GBPUSD'."
        lines = [f"{p.get('id')}: {p.get('value')}" for p in prefs]
        return "<b>Saved preferences</b>\n" + "\n".join(lines)

    def _cmd_forget(self, params):
        """Delete a single user preference by id."""
        if not params:
            return "Usage: /forget &lt;preferenceId&gt;"
        from ..ai.conversation import forget_preference  # lazy import

        if forget_preference(params[0]):
            return f"Forgot preference <code>{params[0]}</code>."
        return f"No preference with id <code>{params[0]}</code>."

    def _cmd_unknown(self, params):
        return "Unknown command. Available: /status, /trades, /approve <id>, /reject <id>, /ask <question>, /prefs, /forget <id>. Or just tell me what to do in plain English."


def _env(key):
    import os
    return os.environ.get(key, "")


def _open_positions():
    from ..trading.engine import trading_engine  # lazy import
    return trading_engine.get_open_positions()


telegram_bot = TelegramBotClient()

# Default confidence band; can be tuned at runtime via the conversational
# assistant (``set auto execute threshold`` / ``set suggest threshold``), which
# persists through ``ai/confidence_gates.py``. The live band is read from the
# gates in ``_on_suggested_trade_created``; these constants keep the same
# defaults and remain the public defaults for callers/tests.
SUGGESTED_TRADE_MIN_CONFIDENCE = 0.70
SUGGESTED_TRADE_MAX_CONFIDENCE = 0.90

_listener_installed = False


def _format_suggestion_message(suggested):
    """Build the approval-request message for a suggested trade."""
    symbol = str(suggested.get("symbol") or "?")
    side = str(suggested.get("side") or "?").upper()
    confidence = suggested.get("confidence") or 0
    try:
        pct = int(round(float(confidence) * 100))
    except (TypeError, ValueError):
        pct = 0
    lines = [f"AI Suggests: {side} {symbol}", f"Confidence: {pct}%"]
    entry = suggested.get("entry") if suggested.get("entry") is not None else suggested.get("entryPrice")
    sl = suggested.get("stopLoss") if suggested.get("stopLoss") is not None else suggested.get("sl")
    tp = suggested.get("takeProfit") if suggested.get("takeProfit") is not None else suggested.get("tp")
    if entry is not None:
        lines.append(f"Entry: {entry}")
    if sl is not None:
        lines.append(f"SL: {sl}")
    if tp is not None:
        lines.append(f"TP: {tp}")
    suggestion_id = suggested.get("id")
    if suggestion_id:
        lines.append(f"Approve: /approve {suggestion_id}")
    return "\n".join(lines)


def _send_suggestion_alert_threaded(suggested, chat_id=None):
    """Send the alert off-thread so the event emitter never blocks on HTTP."""
    import threading

    def _worker():
        try:
            telegram_bot.send_message(chat_id, _format_suggestion_message(suggested))
        except Exception as err:  # noqa: BLE001 - alert failures never propagate
            logger.error("telegram suggestion alert failed", {"error": str(err)})

    threading.Thread(target=_worker, daemon=True).start()


def _on_suggested_trade_created(event):
    """Fire a Telegram alert for AI-suggested trades in the 70-89% band.

    Mirrors the WhatsApp suggestion alert: trades at/above 90% are
    auto-executed and below 70% are discarded; only the 70-89% band needs
    human approval, so only that band triggers an alert. When Telegram is not
    configured the listener does nothing — it never crashes or blocks the
    event bus.
    """
    suggested = (event.get("payload") or {}).get("suggested") or {}
    confidence = suggested.get("confidence")
    try:
        score = float(confidence)
    except (TypeError, ValueError):
        return
    from ..ai.confidence_gates import get_gates  # lazy import

    gates = get_gates()
    if not (gates["suggest"] <= score < gates["auto_execute"]):
        return
    from .connections_manager import connections_manager

    config = connections_manager.get_config("telegram")
    if not config.get("is_active") and not config.get("api_token"):
        return
    chat_id = config.get("chat_id") or telegram_bot.chat_id
    _send_suggestion_alert_threaded(suggested, chat_id)


def init_telegram_bot():
    global _listener_installed
    token = _env("TELEGRAM_BOT_TOKEN")
    if token:
        telegram_bot.token = token.strip()
    chat_id = _env("TELEGRAM_CHAT_ID")
    if chat_id:
        telegram_bot.chat_id = chat_id
    if not _listener_installed:
        event_bus.on("suggested:trade-created", _on_suggested_trade_created)
        _listener_installed = True
        logger.info("Telegram suggestion alert listener installed")
    logger.info(f"Telegram Bot integration initialized (token={'configured' if telegram_bot.token else 'missing'})")
    return telegram_bot

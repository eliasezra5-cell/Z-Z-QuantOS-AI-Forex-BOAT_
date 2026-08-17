"""Conversational AI assistant for the QuantOS bot (Telegram + WhatsApp).

Additive module that gives the bot a natural conversation layer on top of the
existing provider failover chain:

  - ``chat_reply``          natural chat reply with live trading context
  - ``process_message``     full routing: preference training -> intent
                            execution -> free-form chat
  - ``execute_intent``      keyword/regex instruction execution via the
                            existing risk / execution / trading / safety
                            engines — covers the admin panel controls (risk
                            limits, trading modes, profiles, confidence gates,
                            kill switches, fail-closed, schedules, manual
                            orders, position close/reverse, MT5 freeze,
                            hard blockers, brain pauses, news collectors)
  - ``remember_preference`` long-term user preference training persisted in the
                            ``ai_memory`` JSON collection (type user_preference)
  - ``preference_context``  preference summary injected into decision context
  - ``preference_blocks``   hard preference constraints ("never trade X")
  - ``graceful_fallback_reply`` status summary when no real provider is up

AI provider clients are imported lazily so this module stays safe to load even
before the AI layer is initialised.
"""
import re
import threading
import time

from ...foundation.json_store import db
from ...foundation.logger import logger

PREFERENCE_KEY = "user_preference"

PREFERENCE_PATTERNS = [
    re.compile(r"\bremember that\s+(.+)", re.IGNORECASE),
    re.compile(r"\bmy preference is\s+(.+)", re.IGNORECASE),
    re.compile(r"\bfrom now on\s+(.+)", re.IGNORECASE),
    re.compile(r"\balways\s+(.+)", re.IGNORECASE),
    re.compile(r"\bnever\s+(.+)", re.IGNORECASE),
    re.compile(r"\bprefer\s+(.+)", re.IGNORECASE),
]

_INTENTS = [
    # ---- Risk limits ----
    ("set_risk", re.compile(r"\bset\s+risk\s+to\s+(\d+(?:\.\d+)?)\s*%?", re.IGNORECASE)),
    ("set_daily_loss", re.compile(r"\bset\s+(?:daily\s+)?loss\s+to\s+(\d+(?:\.\d+)?)", re.IGNORECASE)),
    ("set_max_positions", re.compile(r"\bset\s+(?:max\s+)?open\s+positions\s+to\s+(\d+)", re.IGNORECASE)),
    ("set_exposure", re.compile(r"\bset\s+(?:max\s+)?exposure\s+to\s+(\d+(?:\.\d+)?)\s*%?", re.IGNORECASE)),
    # ---- Trading modes ----
    ("clear_emergency_stop", re.compile(r"\bclear\s+(?:the\s+)?emergency\s+stop\b", re.IGNORECASE)),
    ("emergency_stop", re.compile(r"\bemergency\s+stop\s*(?:now)?\b", re.IGNORECASE)),
    ("analysis_only", re.compile(r"\bswitch\s+to\s+analysis\s*[- ]?only\b", re.IGNORECASE)),
    ("semi_auto", re.compile(r"\bswitch\s+to\s+semi\s*[- ]?auto\b", re.IGNORECASE)),
    ("auto_full", re.compile(r"\bswitch\s+to\s+(?:full\s+)?auto(?:mation)?\b", re.IGNORECASE)),
    # ---- Positions / analysis ----
    ("close_all", re.compile(r"\bclose\s+all\s+(?:open\s+)?positions\b", re.IGNORECASE)),
    ("run_analysis", re.compile(r"\b(?:run\s+)?analysis\s+on\s+([a-z0-9_]{2,12})\b", re.IGNORECASE)),
    # ---- Risk profile & confidence gates ----
    ("set_profile", re.compile(r"\b(?:set\s+(?:the\s+)?(?:risk\s+)?profile\s+to|switch\s+to)\s+(conservative|aggressive|scalping|swing)(?:\s+profile)?\b", re.IGNORECASE)),
    ("set_auto_threshold", re.compile(r"\bset\s+(?:the\s+)?(?:auto\s*[- ]?execute|auto)\s+threshold\s+to\s+(\d+(?:\.\d+)?)\s*%?\b", re.IGNORECASE)),
    ("set_suggest_threshold", re.compile(r"\bset\s+(?:the\s+)?(?:suggest|suggestion|semi[- ]auto)\s+threshold\s+to\s+(\d+(?:\.\d+)?)\s*%?\b", re.IGNORECASE)),
    # ---- Kill switches / fail-closed / emergency reset ----
    ("clear_all_kill_switches", re.compile(r"\bclear\s+all\s+kill\s+switches\b", re.IGNORECASE)),
    ("kill_switch", re.compile(r"\b(trigger|clear)\s+(?:the\s+)?kill\s+switch\s+(?:for\s+)?([a-z0-9_]+)\b", re.IGNORECASE)),
    ("fail_closed", re.compile(r"\b(trigger|raise|clear)\s+(?:the\s+)?fail\s*[- ]closed\s+(?:trigger\s+)?([a-z0-9\-]+)\b", re.IGNORECASE)),
    # ---- Schedules ----
    ("set_schedule", re.compile(r"\b(?:set\s+trading\s+hours|add\s+(?:a\s+)?(?:trading\s+)?schedule)\s+(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\b", re.IGNORECASE)),
    ("clear_schedules", re.compile(r"\bclear\s+all\s+(?:trading\s+)?schedules\b", re.IGNORECASE)),
    # ---- Manual order + position management ----
    ("place_order", re.compile(r"\bplace\s+(?:an?\s+)?(buy|sell)\s+order(?:\s+for\s+)?\s*([a-z0-9_]{2,12})", re.IGNORECASE)),
    ("close_symbol", re.compile(r"\bclose\s+(?:the\s+)?([a-z0-9_]{2,12})\s+(?:position|trade)\b", re.IGNORECASE)),
    ("reverse_symbol", re.compile(r"\breverse\s+(?:the\s+)?([a-z0-9_]{2,12})\s+(?:position|trade)\b", re.IGNORECASE)),
    # ---- Safety / MT5 / blockers ----
    ("freeze_symbol", re.compile(r"\bfreeze\s+([a-z0-9_]{2,12})\b", re.IGNORECASE)),
    ("unfreeze_symbol", re.compile(r"\bunfreeze\s+([a-z0-9_]{2,12})\b", re.IGNORECASE)),
    ("raise_blocker", re.compile(r"\b(?:raise|set|trigger)\s+(?:a\s+)?hard\s+blocker\s+([a-z0-9\-_]+)\b", re.IGNORECASE)),
    ("clear_blocker", re.compile(r"\bclear\s+(?:a\s+)?hard\s+blocker\s+([a-z0-9\-_]+)\b", re.IGNORECASE)),
    ("clear_pause", re.compile(r"\bclear\s+(?:the\s+)?pause\s+(?:on\s+)?([a-z0-9_]+)\b", re.IGNORECASE)),
    ("brain_pause", re.compile(r"\bpause\s+(?:kill\s+)?condition\s+([a-z0-9_]+)(?:\s+for\s+(\d+)\s*min(?:utes)?)?\b", re.IGNORECASE)),
    ("brain_pause", re.compile(r"\bpause\s+([a-z0-9]+(?:_[a-z0-9]+)+)(?:\s+for\s+(\d+)\s*min(?:utes)?)?\b", re.IGNORECASE)),
    # ---- News / data ----
    ("run_collectors", re.compile(r"\brun\s+(?:all\s+)?(?:news\s+)?collectors\b", re.IGNORECASE)),
]

CHAT_TIMEOUT_SECONDS = 90


def _prefs_col():
    return db.collection("ai_memory")


def user_preferences():
    """List persisted user preference entries (latest first)."""
    rows = _prefs_col().find({"key": PREFERENCE_KEY}, {"sort": ["rememberedAt", "desc"]})
    return [r for r in rows if r.get("value")]


def preference_context():
    """Flatten saved preferences into a short text line for prompt injection."""
    values = [str(r.get("value", "")).strip() for r in user_preferences()]
    return "; ".join(v for v in values if v)


def remember_preference(text):
    """Store a user preference when the message matches a training pattern.

    Returns the stored row (dict) or None when no pattern matched.
    """
    for pattern in PREFERENCE_PATTERNS:
        match = pattern.search(text or "")
        if match:
            value = match.group(1).strip().rstrip(".")
            if not value:
                return None
            row = _prefs_col().insert({
                "key": PREFERENCE_KEY,
                "value": value,
                "ttlMs": 0,
                "rememberedAt": int(time.time() * 1000),
            })
            return row
    return None


def list_preferences():
    return user_preferences()


def forget_preference(entry_id):
    return bool(_prefs_col().remove(entry_id))


def preference_blocks(symbol):
    """Return hard constraint reasons from trained preferences.

    Currently enforces ``never trade <symbol>`` style rules so the bot can
    learn to stay away from instruments the user forbids.
    """
    reasons = []
    symbol = (symbol or "").upper()
    for pref in user_preferences():
        value = str(pref.get("value", "")).lower()
        match = re.search(r"\bnever\s+trade\s+([a-z0-9_]+)", value)
        if match and match.group(1).upper() == symbol:
            reasons.append(f"user-preference: never trade {symbol}")
    return reasons


def _has_real_provider():
    from .clients import ai_provider_manager

    manager = ai_provider_manager
    if manager is None:
        return False
    for managed in manager.managed:
        if getattr(getattr(managed, "client", None), "id", None) != "local-fallback":
            return True
    return False


def _live_context():
    ctx = {
        "mode": "DISABLED",
        "profile": "conservative",
        "open_positions": 0,
        "max_risk": "?",
        "max_daily_loss": "?",
        "max_open_positions": "?",
        "preferences": "",
    }
    try:
        from ..execution.modes import trading_modes

        ctx["mode"] = trading_modes.get_mode()
        ctx["profile"] = trading_modes.get_profile().get("id", "conservative")
    except Exception:  # noqa: BLE001 - context is best-effort
        pass
    try:
        from ..trading.engine import trading_engine

        ctx["open_positions"] = len(trading_engine.get_open_positions())
    except Exception:  # noqa: BLE001
        pass
    try:
        from ..risk.engine import risk_engine

        for setting in risk_engine.get_settings():
            if setting.get("id") == "max_risk_per_trade":
                ctx["max_risk"] = setting.get("value")
            elif setting.get("id") == "max_daily_loss":
                ctx["max_daily_loss"] = setting.get("value")
            elif setting.get("id") == "max_open_positions":
                ctx["max_open_positions"] = setting.get("value")
    except Exception:  # noqa: BLE001
        pass
    ctx["preferences"] = preference_context()
    return ctx


def _build_chat_messages(text, ctx):
    system = (
        "You are the QuantOS AI BOAT assistant, a friendly professional "
        "quantitative trading bot. Reply in the same language the user writes "
        "in and keep replies concise and helpful.\n"
        "Live system context:\n"
        f"- trading mode: {ctx['mode']}\n"
        f"- profile: {ctx['profile']}\n"
        f"- open positions: {ctx['open_positions']}\n"
        f"- risk: max {ctx['max_risk']}% per trade, max daily loss "
        f"{ctx['max_daily_loss']}%, max open positions {ctx['max_open_positions']}\n"
        f"- user preferences: {ctx['preferences'] or 'none yet'}\n"
        "Answer the user naturally. When they ask for an actionable change, "
        "explain what you can do but never claim an order or change was "
        "executed unless it actually was."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": str(text)},
    ]


def _text_parser(result_text, provider_id):
    return {"text": str(result_text or "").strip(), "model": provider_id}


def graceful_fallback_reply():
    """Friendly status reply used when no real AI provider is available."""
    ctx = _live_context()
    return (
        "I can't reach an AI provider right now, but here is the live status:\n"
        f"- Trading mode: {ctx['mode']}\n"
        f"- Profile: {ctx['profile']}\n"
        f"- Open positions: {ctx['open_positions']}\n"
        f"- Risk: max {ctx['max_risk']}% per trade, daily loss {ctx['max_daily_loss']}%\n"
        "Check the dashboard for full details. Commands: /status, /trades, "
        "/approve <id>, /reject <id>, /ask <question>, /prefs, /forget <id>."
    )


def chat_reply(text):
    """Free-form conversational reply through the AI provider chain."""
    from .clients import LLMError, ai_provider_manager

    if not _has_real_provider():
        return graceful_fallback_reply()
    messages = _build_chat_messages(text, _live_context())
    try:
        result = ai_provider_manager.complete_custom(
            messages,
            parser=_text_parser,
            temperature=0.6,
            max_tokens=600,
        )
    except LLMError:
        return graceful_fallback_reply()
    if not result or str(result.get("model", "")).endswith("local-fallback"):
        return graceful_fallback_reply()
    reply = str(result.get("text") or "").strip()
    return reply or graceful_fallback_reply()


def _run_async_safely(coro):
    holder = {}

    def _worker():
        try:
            import asyncio

            holder["result"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001 - surfaced as no-result
            holder["error"] = str(exc)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=CHAT_TIMEOUT_SECONDS)
    return holder.get("result")


def _format_analysis_summary(decision):
    symbol = decision.get("symbol") or "?"
    direction = str(decision.get("direction") or "neutral").upper()
    confidence = decision.get("confidence") or 0
    status = decision.get("status") or "UNKNOWN"
    try:
        pct = int(round(float(confidence) * 100))
    except (TypeError, ValueError):
        pct = 0
    return f"Analysis done: {symbol} {direction} {pct}% confidence — status {status}."


def execute_intent(text):
    """Recognize and execute actionable instructions.

    Returns a ``(action, reply)`` tuple or None when no intent matched.
    """
    for action, pattern in _INTENTS:
        match = pattern.search(text or "")
        if not match:
            continue
        if action == "set_risk":
            from ..risk.engine import risk_engine

            risk_engine.get_settings()
            value = float(match.group(1))
            risk_engine.update_setting("max_risk_per_trade", value)
            return action, f"Done — max risk per trade set to {value}%."
        if action == "set_daily_loss":
            from ..risk.engine import risk_engine

            risk_engine.get_settings()
            value = float(match.group(1))
            risk_engine.update_setting("max_daily_loss", value)
            return action, f"Done — max daily loss set to {value}%."
        if action == "set_max_positions":
            from ..risk.engine import risk_engine

            risk_engine.get_settings()
            value = int(match.group(1))
            risk_engine.update_setting("max_open_positions", value)
            return action, f"Done — max open positions set to {value}."
        if action == "set_exposure":
            from ..risk.engine import risk_engine

            risk_engine.get_settings()
            value = float(match.group(1))
            risk_engine.update_setting("max_total_exposure", value)
            return action, f"Done — max total exposure set to {value}%."
        if action == "clear_emergency_stop":
            from ..risk.capital_protection import capital_protection

            capital_protection.deactivate_emergency_stop("admin")
            status = capital_protection.get_status()
            return action, f"Emergency stop cleared. Shield: {status.get('shield_level')}."
        if action == "emergency_stop":
            from ..execution.modes import trading_modes

            result = trading_modes.set_mode("EMERGENCY_STOP", "admin", "emergency stop via chat")
            return action, f"Emergency stop engaged ({result.get('status')}). All trading halted."
        if action == "analysis_only":
            from ..execution.modes import trading_modes

            result = trading_modes.set_mode("ANALYSIS_ONLY", "admin", "analysis only via chat")
            return action, f"Switched to ANALYSIS_ONLY ({result.get('status')}). No orders will be placed."
        if action == "semi_auto":
            from ..execution.modes import trading_modes

            result = trading_modes.set_mode("SEMI_AUTO", "admin", "semi auto via chat")
            return action, f"Switched to SEMI_AUTO ({result.get('status')}). AI suggestions will ask for approval."
        if action == "auto_full":
            from ..execution.modes import trading_modes

            result = trading_modes.set_mode("AUTO_FULL", "admin", "auto full via chat")
            return action, f"Switched to AUTO_FULL ({result.get('status')})."
        if action == "close_all":
            from ..trading.engine import trading_engine

            positions = trading_engine.get_open_positions()
            closed = 0
            for position in positions:
                try:
                    trading_engine.close_position(position.get("id"), "chat: close all positions")
                    closed += 1
                except Exception:  # noqa: BLE001 - one failure must not block the rest
                    pass
            return action, f"Closed {closed} of {len(positions)} open positions."
        if action == "run_analysis":
            from .decision_pipeline import analyze_symbol_pipeline

            symbol = match.group(1).upper()
            decision = _run_async_safely(analyze_symbol_pipeline(symbol))
            if isinstance(decision, dict) and decision.get("symbol"):
                return action, _format_analysis_summary(decision)
            return action, f"Analysis on {symbol} could not be completed right now."
        if action == "set_profile":
            from ..execution.modes import trading_modes

            profile_id = match.group(1).lower()
            result = trading_modes.set_profile(profile_id)
            return action, f"Profile set to {profile_id} ({result.get('status')})."
        if action == "set_auto_threshold":
            from .confidence_gates import set_gate

            result = set_gate("auto_execute", float(match.group(1)) / 100.0)
            if result.get("status") != "ok":
                return action, f"Could not set auto-execute threshold ({result.get('status')})."
            return action, f"Done — auto-execute threshold set to {int(round(result['auto_execute'] * 100))}%."
        if action == "set_suggest_threshold":
            from .confidence_gates import set_gate

            result = set_gate("suggest", float(match.group(1)) / 100.0)
            if result.get("status") != "ok":
                return action, f"Could not set suggest threshold ({result.get('status')})."
            return action, f"Done — suggest threshold set to {int(round(result['suggest'] * 100))}%."
        if action == "clear_all_kill_switches":
            from ..execution.modes import trading_modes
            from ..risk.capital_protection import capital_protection

            modes_res = trading_modes.clear_kill_switches("admin")
            capital_protection.deactivate_emergency_stop("admin")
            for trigger in list(capital_protection.get_status().get("fail_closed") or []):
                capital_protection.clear_fail_closed(trigger)
            capital_protection.clear_daily_lock("admin")
            return action, f"Cleared {len(modes_res.get('cleared', []))} kill switch(es). Mode now {modes_res.get('mode')}."
        if action == "kill_switch":
            from ..execution.modes import trading_modes

            verb = match.group(1).lower()
            switch = match.group(2)
            active = verb != "clear"
            trading_modes.trigger_kill_switch(switch, active, "via chat")
            return action, f"Kill switch {switch} {'triggered' if active else 'cleared'}."
        if action == "fail_closed":
            from ..risk.capital_protection import capital_protection

            verb = match.group(1).lower()
            trigger = match.group(2)
            if verb == "clear":
                capital_protection.clear_fail_closed(trigger)
                return action, f"Fail-closed trigger {trigger} cleared."
            capital_protection.raise_fail_closed(trigger, "via chat")
            return action, f"Fail-closed trigger {trigger} raised."
        if action == "set_schedule":
            from ..execution.modes import trading_modes

            start = int(match.group(1))
            end = int(match.group(2))
            if not (0 <= start < 24) or not (1 <= end <= 24) or end <= start:
                return action, "Invalid hours — use e.g. 'set trading hours 8-20' (0-23, start before end)."
            schedule = trading_modes.add_schedule({"start": start, "end": end, "days": [], "enabled": True, "comment": "chat"})
            return action, f"Schedule added: {start}:00-{end}:00 UTC (all days)."
        if action == "clear_schedules":
            from ..execution.modes import trading_modes

            count = 0
            for schedule in list(trading_modes.schedules):
                trading_modes.remove_schedule(schedule.get("id"))
                count += 1
            return action, f"Cleared {count} schedule(s). Trading is now unrestricted."
        if action == "place_order":
            from ..trading.engine import trading_engine

            side = match.group(1).lower()
            symbol = match.group(2).upper()
            tail = text[match.end():]
            volume = 0.1
            sl = tp = None
            vol_m = re.search(r"\b(?:lot|lots|volume|vol|size)\s+([\d.]+)", tail, re.IGNORECASE)
            if vol_m:
                volume = float(vol_m.group(1))
            else:
                num_m = re.match(r"\s*([\d.]+)", tail)
                if num_m:
                    volume = float(num_m.group(1))
            sl_m = re.search(r"\bsl\s+([\d.]+)", tail, re.IGNORECASE)
            if sl_m:
                sl = float(sl_m.group(1))
            tp_m = re.search(r"\btp\s+([\d.]+)", tail, re.IGNORECASE)
            if tp_m:
                tp = float(tp_m.group(1))
            order = {"symbol": symbol, "side": side, "type": "market", "volume": volume, "source": "chat"}
            if sl is not None:
                order["stopLoss"] = sl
            if tp is not None:
                order["takeProfit"] = tp
            result = trading_engine.place_order(order)
            if result.get("status") == "rejected":
                violations = result.get("violations") or ["safety gate"]
                return action, f"Order rejected: {violations[0]}"
            return action, f"Order placed: {side.upper()} {symbol} vol={volume} (status {result.get('status')})."
        if action == "close_symbol":
            from ..trading.engine import trading_engine

            symbol = match.group(1).upper()
            positions = trading_engine.get_open_positions()
            matched = [p for p in positions if str(p.get("symbol", "")).upper() == symbol]
            if not matched:
                return action, f"No open {symbol} position."
            closed = 0
            for position in matched:
                try:
                    trading_engine.close_position(position.get("id") or position.get("positionId"), "chat: close position")
                    closed += 1
                except Exception:  # noqa: BLE001 - one failure must not block the rest
                    pass
            return action, f"Closed {closed} of {len(matched)} {symbol} position(s)."
        if action == "reverse_symbol":
            from ..trading.engine import trading_engine

            symbol = match.group(1).upper()
            positions = trading_engine.get_open_positions()
            matched = [p for p in positions if str(p.get("symbol", "")).upper() == symbol]
            if not matched:
                return action, f"No open {symbol} position to reverse."
            reversed_count = 0
            for position in matched:
                try:
                    trading_engine.reverse_position(position.get("id") or position.get("positionId"))
                    reversed_count += 1
                except Exception:  # noqa: BLE001 - one failure must not block the rest
                    pass
            return action, f"Reversed {reversed_count} of {len(matched)} {symbol} position(s)."
        if action == "freeze_symbol":
            from ..execution.mt5_safety import mt5_safety

            symbol = match.group(1).upper()
            mt5_safety.freeze_symbol(symbol, "via chat")
            return action, f"Froze {symbol} — execution blocked for this symbol."
        if action == "unfreeze_symbol":
            from ..execution.mt5_safety import mt5_safety

            symbol = match.group(1).upper()
            mt5_safety.unfreeze_symbol(symbol)
            return action, f"Unfroze {symbol}."
        if action == "raise_blocker":
            from ..validation.engine import validation_engine

            blocker = match.group(1)
            validation_engine.raise_hard_blocker(blocker, "via chat")
            return action, f"Hard blocker {blocker} raised — new trades blocked system-wide."
        if action == "clear_blocker":
            from ..validation.engine import validation_engine

            blocker = match.group(1)
            validation_engine.clear_hard_blocker(blocker)
            return action, f"Hard blocker {blocker} cleared."
        if action == "brain_pause":
            from ..execution.brain_monitor import _now_ms, kill_switch_monitor
            from ..execution.modes import KILL_SWITCHES

            condition = match.group(1)
            minutes = int(match.group(2)) if (match.lastindex and match.group(2)) else 30
            if condition not in KILL_SWITCHES:
                return action, f"Unknown condition '{condition}'. Valid: {', '.join(KILL_SWITCHES)}"
            until = _now_ms() + minutes * 60 * 1000
            kill_switch_monitor.pauses[condition] = until
            return action, f"Paused {condition} for {minutes} minute(s)."
        if action == "clear_pause":
            from ..execution.brain_monitor import kill_switch_monitor

            condition = match.group(1)
            if condition in kill_switch_monitor.pauses:
                del kill_switch_monitor.pauses[condition]
                return action, f"Pause on {condition} cleared."
            return action, f"No active pause on {condition}."
        if action == "run_collectors":
            from ..news.realtime.registry import poll_all_collectors

            result = _run_async_safely(poll_all_collectors(10))
            if result is None:
                return action, "News collectors could not run right now."
            return action, f"News collectors run complete: {result}"
    return None


def process_message(text):
    """Route an incoming chat message and return the reply text.

    Order: preference training -> intent execution -> free-form AI chat.
    """
    text = (text or "").strip()
    if not text:
        return "Send me a message or use a command — /status, /trades, /approve <id>, /reject <id>, /ask <question>, /prefs."
    pref = remember_preference(text)
    if pref:
        return f"Got it — I'll remember: {pref.get('value')}."
    intent = execute_intent(text)
    if intent:
        return intent[1]
    return chat_reply(text)

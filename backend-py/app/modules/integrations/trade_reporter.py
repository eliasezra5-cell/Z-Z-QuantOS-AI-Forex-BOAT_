"""Cross-platform trade execution reporter (additive).

Sends a detailed, human-readable execution report to ALL configured channels
(Telegram, WhatsApp, Email) whenever a trade is actually filled — whether it
came from the auto-execute path (``institutional:order-placed``) or from an
approved suggested trade (``suggested:trade-executed``). The report includes
the trade details (symbol, side, volume, entry, SL, TP, confidence) AND the
WHY: the per-agent breakdown (news, fundamental, technical, macro, historical,
sentiment, risk) plus the news headlines behind the decision, so the trader can
understand why the trade was taken.

The reporter never crashes the event bus: every channel send is best-effort and
each failure is logged, never raised.
"""
import threading
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db

AGENT_LABELS = {
    "news": "News",
    "historical": "Historical",
    "macro": "Macro",
    "technical": "Technical",
    "risk": "Risk",
    "sentiment": "Sentiment",
    "fundamentals": "Fundamentals",
    "social": "Social Sentiment",
}


def _agent_lines(decision):
    """Per-agent directional reasoning lines from the source decision."""
    lines = []
    for score in decision.get("agentScores") or []:
        agent_id = str(score.get("agent_id") or "?")
        label = AGENT_LABELS.get(agent_id, agent_id)
        direction = str(score.get("direction") or "neutral").upper()
        confidence = score.get("confidence")
        try:
            pct = int(round(float(confidence) * 100))
        except (TypeError, ValueError):
            pct = None
        reasoning = str(score.get("reasoning") or "").strip()
        abstention = str(score.get("abstention") or "").upper()
        if abstention in ("DATA_INSUFFICIENT", "ABSTAIN", "NO_CONSENSUS"):
            lines.append(f"{label}: ABSTAIN ({abstention})")
            continue
        conf_part = f" @ {pct}%" if pct is not None else ""
        if direction in ("BUY", "SELL"):
            lines.append(f"{label}: {direction}{conf_part} — {reasoning}" if reasoning else f"{label}: {direction}{conf_part}")
        elif reasoning:
            lines.append(f"{label}: {reasoning[:300]}")
    return lines


def _news_headlines(decision):
    """Headline lines for the news items referenced by the decision."""
    lines = []
    for news_id in (decision.get("newsIds") or [])[:5]:
        try:
            item = db.collection("news_items").find_one({"id": news_id})
        except Exception:  # noqa: BLE001 - lookup failures are best-effort
            item = None
        if not item:
            continue
        title = str(item.get("title") or item.get("headline") or "").strip()
        if title:
            impact = item.get("impact")
            impact_str = f" [impact {impact}]" if impact is not None else ""
            lines.append(f"- {title}{impact_str}")
    return lines


def _debate_lines(decision):
    """Bull vs Bear research debate transcript lines."""
    debate = decision.get("debate") or {}
    transcript = debate.get("transcript") or []
    lines = []
    for turn in transcript:
        speaker = str(turn.get("speaker") or "?")
        if speaker == "research_manager":
            continue
        argument = str(turn.get("argument") or "").strip()
        counters = [str(c) for c in (turn.get("counters") or []) if str(c).strip()]
        confidence = turn.get("confidence")
        try:
            conf_str = f" @ {round(float(confidence) * 100)}%" if confidence is not None else ""
        except (TypeError, ValueError):
            conf_str = ""
        label = "Bull" if speaker == "bull" else ("Bear" if speaker == "bear" else speaker.capitalize())
        if not argument:
            state = str(turn.get("state") or "N/A")
            lines.append(f"{label}: no case ({state})")
            continue
        lines.append(f"{label}{conf_str}: {argument[:300]}")
        for counter in counters[:3]:
            lines.append(f"  rebuttal: {counter[:200]}")
    if debate.get("rationale") and not lines:
        lines.append(str(debate["rationale"])[:300])
    return lines


def build_execution_report(decision, trade=None):
    """Build the human-readable execution report text.

    ``trade`` (optional) carries actual fill details (volume, entry, SL, TP)
    for the approval path; otherwise fields come from the decision.
    """
    symbol = str(trade.get("symbol") or decision.get("symbol") or "?")
    side = str(trade.get("side") or decision.get("direction") or "?").upper()
    volume = trade.get("volume") or trade.get("lotSize") or decision.get("lotSize")
    entry = trade.get("entry") if trade.get("entry") is not None else decision.get("entry")
    sl = trade.get("stopLoss") if trade.get("stopLoss") is not None else decision.get("stopLoss")
    tp = trade.get("takeProfit") if trade.get("takeProfit") is not None else decision.get("takeProfit")
    confidence = decision.get("confidence")
    if isinstance(confidence, dict):
        confidence = confidence.get("score")
    try:
        conf_str = f"{round(float(confidence) * 100)}%" if confidence is not None else "—"
    except (TypeError, ValueError):
        conf_str = "—"

    lines = [
        f"TRADE EXECUTED: {side} {symbol}",
        f"Confidence: {conf_str}",
    ]
    if volume is not None:
        lines.append(f"Volume: {volume}")
    if entry is not None:
        lines.append(f"Entry: {entry}")
    if sl is not None:
        lines.append(f"Stop Loss: {sl}")
    if tp is not None:
        lines.append(f"Take Profit: {tp}")
    lines.append(f"Time: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")

    agent_lines = _agent_lines(decision)
    if agent_lines:
        lines.append("")
        lines.append("WHY THIS TRADE (agent breakdown):")
        lines.extend(agent_lines)

    news_lines = _news_headlines(decision)
    if news_lines:
        lines.append("")
        lines.append("News behind this decision:")
        lines.extend(news_lines)

    debate_lines = _debate_lines(decision)
    if debate_lines:
        lines.append("")
        lines.append("Bull vs Bear debate:")
        lines.extend(debate_lines)

    return "\n".join(lines)


def _send_to_all_channels(subject, text):
    """Send a report to Telegram, WhatsApp and Email (best-effort)."""
    from .telegram_bot import telegram_bot  # lazy import
    from .whatsapp_client import whatsapp_alert_client  # lazy import
    from .email_client import email_client  # lazy import

    try:
        telegram_bot.send_message(None, text)
    except Exception as err:  # noqa: BLE001 - one channel must never block the rest
        logger.error("trade report telegram failed", {"error": str(err)})
    try:
        whatsapp_alert_client.send_text(None, text)
    except Exception as err:  # noqa: BLE001
        logger.error("trade report whatsapp failed", {"error": str(err)})
    try:
        email_client.send_email(subject, text_body=text, to=None)
    except Exception as err:  # noqa: BLE001
        logger.error("trade report email failed", {"error": str(err)})


def _on_order_placed(event):
    """Auto-execute path: ``institutional:order-placed`` carries the decision."""
    payload = event.get("payload") or {}
    decision = payload.get("decision") or {}
    order = payload.get("order") or {}
    if not decision:
        return
    trade = {
        "symbol": order.get("symbol") or decision.get("symbol"),
        "side": order.get("side") or decision.get("direction"),
        "volume": order.get("volume"),
        "entry": decision.get("entry"),
        "stopLoss": decision.get("stopLoss"),
        "takeProfit": decision.get("takeProfit"),
    }
    try:
        report = build_execution_report(decision, trade)
    except Exception as err:  # noqa: BLE001 - reporting must never break the bus
        logger.error("trade report build failed", {"error": str(err)})
        return
    threading.Thread(
        target=_send_to_all_channels,
        args=(f"Trade Executed: {decision.get('symbol')}", report),
        daemon=True,
    ).start()


def _on_suggestion_executed(event):
    """Approval path: ``suggested:trade-executed`` carries trade_id + result."""
    payload = event.get("payload") or {}
    trade_id = payload.get("trade_id")
    result = payload.get("result") or {}
    if not trade_id:
        return
    try:
        row = auto_trade_controller_col().find_one({"id": trade_id})
    except Exception:  # noqa: BLE001
        row = None
    if not row:
        return
    decision = _load_decision(row.get("decision_id"))
    trade = {
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "volume": row.get("lotSize") or (result.get("order") or {}).get("volume"),
        "entry": row.get("entry") if row.get("entry") is not None else row.get("entryPrice"),
        "stopLoss": row.get("stopLoss") if row.get("stopLoss") is not None else row.get("sl"),
        "takeProfit": row.get("takeProfit") if row.get("takeProfit") is not None else row.get("tp"),
    }
    try:
        report = build_execution_report(decision or {}, trade)
    except Exception as err:  # noqa: BLE001
        logger.error("trade report build failed", {"error": str(err)})
        return
    threading.Thread(
        target=_send_to_all_channels,
        args=(f"Trade Executed: {row.get('symbol')}", report),
        daemon=True,
    ).start()


def auto_trade_controller_col():
    from ..execution.auto_controller import auto_trade_controller  # lazy import

    return auto_trade_controller.col


def _load_decision(decision_id):
    if not decision_id:
        return {}
    try:
        return db.collection("ai_decisions").find_one({"id": decision_id}) or {}
    except Exception:  # noqa: BLE001 - best-effort lookup
        return {}


_listener_installed = False


def init_trade_reporter():
    global _listener_installed
    if not _listener_installed:
        event_bus.on("institutional:order-placed", _on_order_placed)
        event_bus.on("suggested:trade-executed", _on_suggestion_executed)
        _listener_installed = True
        logger.info("Cross-platform trade execution reporter installed")
    return {"status": "ok"}

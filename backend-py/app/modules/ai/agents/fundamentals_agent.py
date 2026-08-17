"""Fundamentals Analysis Agent (Feature 2, additive, custom pool).

Deterministic macro-fundamentals proxy over the existing Economic Calendar
(``modules/economic/engine``). For each symbol it maps the relevant event
window (past 24h .. next 72h) and high-impact events (impact >= 2), then
scores the net directional signal from each event's ``ai.direction`` /
``ai.confidence``, sign-adjusted by whether the event's currency is the pair's
base (helps) or quote (prices the asset, so moves inversely).

When a symbol has no relevant fundamental data at all, the agent returns an
explicit ``DATA_INSUFFICIENT`` abstention (clean, no fabricated score).
No LLM dependency — always deterministic and testable.
"""
import time

from ....foundation.logger import logger
from ..agents.base import AgentResult, clamp01
from ...economic.engine import get_economic_events

AGENT_ID = "custom-fundamentals"
AGENT_NAME = "FundamentalsAnalysisAgent"
AGENT_WEIGHT = 0.10
NEUTRAL_BAND = 0.10


def _symbol_currencies(symbol):
    """Return (base, quote) for a symbol. XAUUSD -> ('XAU', 'USD'); AAPL -> ('', 'USD')."""
    symbol = (symbol or "").upper().strip()
    if len(symbol) == 6:
        base, quote = symbol[:3], symbol[3:]
        if base.isalpha() and quote.isalpha():
            return base, quote
    return "", "USD"


def _event_signal(event):
    """Extract (sign, magnitude) from one economic event, or None if not usable."""
    ai = event.get("ai") or {}
    direction = str(ai.get("direction") or "neutral").lower()
    sign = None
    if direction.startswith("bullish"):
        sign = 1.0
    elif direction.startswith("bearish"):
        sign = -1.0
    if sign is None:
        return None
    try:
        confidence = clamp01(float(ai.get("confidence") or 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    impact = int(event.get("impact") or 1)
    weight = max(1.0, min(3.0, impact)) / 3.0
    return sign, weight * confidence


def compute_fundamentals(symbol, events=None):
    """Deterministic net fundamentals signal for a symbol.

    Returns a dict with direction/confidence/reasoning/used/events, or
    ``{"abstain": "DATA_INSUFFICIENT"}`` when no relevant events exist.
    """
    symbol = (symbol or "XAUUSD").upper()
    base, quote = _symbol_currencies(symbol)
    if events is None:
        try:
            events = get_economic_events({"limit": 200})
        except Exception as exc:  # noqa: BLE001 - proxy must never crash
            logger.warn(f"Fundamentals agent: economic calendar fetch failed: {exc}")
            events = []
    now = int(time.time() * 1000)
    lookback = 7 * 24 * 3600000
    relevant = []
    for ev in events:
        try:
            ev_time = int(ev.get("time") or 0)
        except (TypeError, ValueError):
            continue
        if not (now - lookback <= ev_time <= now + 72 * 3600000):
            continue
        if int(ev.get("impact") or 0) < 2:
            continue
        currency = str(ev.get("currency") or "").upper()
        affected = ev.get("ai") or {}
        affected_instruments = affected.get("affectedInstruments") or []
        if symbol in affected_instruments or currency in (base, quote):
            relevant.append(ev)
    if not relevant:
        return {"abstain": "DATA_INSUFFICIENT"}

    net = 0.0
    used = 0
    for ev in relevant:
        signal = _event_signal(ev)
        if signal is None:
            continue
        direction_sign, magnitude = signal
        currency = str(ev.get("currency") or "").upper()
        if currency == base:
            sign = 1.0  # base-currency strength lifts the pair
        else:
            sign = -1.0  # quote-currency strength prices the asset inversely
        net += sign * direction_sign * magnitude
        used += 1

    direction = "neutral"
    if net > NEUTRAL_BAND:
        direction = "buy"
    elif net < -NEUTRAL_BAND:
        direction = "sell"
    confidence = clamp01(min(0.9, abs(net)))
    return {
        "direction": direction,
        "confidence": round(confidence, 3),
        "net": round(net, 4),
        "used": used,
        "events": relevant,
        "base": base,
        "quote": quote,
    }


class FundamentalsAnalysisAgent:
    id = AGENT_ID
    name = AGENT_NAME
    weight = AGENT_WEIGHT

    async def run(self, context=None):
        context = context or {}
        symbol = context.get("symbol") or "XAUUSD"
        try:
            result = compute_fundamentals(symbol)
        except Exception as exc:  # noqa: BLE001 - agent must never crash the pipeline
            logger.warn(f"Fundamentals agent failed: {exc}")
            return AgentResult(self.id, self.name, self.weight, direction="neutral", confidence=0.0,
                               abstention="DATA_INSUFFICIENT",
                               reasoning="Fundamentals computation failed", data={})
        if result.get("abstain") == "DATA_INSUFFICIENT":
            return AgentResult(self.id, self.name, self.weight, direction="neutral", confidence=0.0,
                               abstention="DATA_INSUFFICIENT",
                               reasoning=f"No fundamentals data available for {symbol} in the event window",
                               data={"eventCount": 0, "base": result.get("base"), "quote": result.get("quote")})
        direction = result["direction"]
        event_names = [e.get("name") for e in result["events"]][:5]
        return AgentResult(
            self.id, self.name, self.weight,
            direction=direction,
            confidence=result["confidence"],
            reasoning=(f"Fundamentals {direction} (net {result['net']}, {result['used']} events) "
                       f"from: {', '.join(event_names)}"),
            abstention="TRADE",
            data={
                "net": result["net"],
                "eventCount": len(result["events"]),
                "events": event_names,
                "base": result["base"],
                "quote": result["quote"],
            },
        )

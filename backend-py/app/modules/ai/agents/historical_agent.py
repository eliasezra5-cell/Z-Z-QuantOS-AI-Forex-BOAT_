"""Historical Pattern Agent (weight 0.20, directional).

Embeds the current news context, queries pgvector (``event_embeddings``) for
the most similar events across the 15-year corpus, and derives a directional
vote from the historical direction + move distribution (``historical_match``,
``move_low/median/high`` pips). When no embedding backend is available it
degrades to the in-memory similarity search so the pipeline still runs.
"""
from decimal import Decimal

from ....foundation.logger import logger
from ....persistence import event_embedding_repository
from ..memory import embed
from .base import AgentResult, clamp01

DIRECTION_MAP = {"buy": "buy", "sell": "sell", "long": "buy", "short": "sell",
                 "bullish": "buy", "bearish": "sell", "neutral": "neutral"}


class HistoricalPatternAgent:
    id = "historical"
    name = "HistoricalPatternAgent"
    weight = 0.20

    async def run(self, context=None):
        context = context or {}
        news = context.get("news") or []
        query_text = " ".join(str(n.get("title") or "") for n in news[:5]) or context.get("symbol", "XAUUSD")
        vector = embed(query_text)
        matches = []
        try:
            matches = await event_embedding_repository.similarity_search(vector, k=8)
        except Exception as exc:  # noqa: BLE001 - degraded search must not crash the agent
            logger.warn(f"Historical pgvector search failed: {exc}")
        if not matches:
            return AgentResult(self.id, self.name, self.weight, abstention="DATA_INSUFFICIENT",
                               reasoning="No similar historical events found",
                               data={"matches": 0, "query": query_text[:200]})

        # Weighted directional vote across the nearest matches.
        buy_w = sell_w = 0.0
        move_pips = []
        for m in matches:
            direction = DIRECTION_MAP.get(str(m.get("direction") or "").lower())
            if direction not in ("buy", "sell"):
                continue
            score = 1.0 / (1.0 + len(move_pips))  # nearest matches count more
            if direction == "buy":
                buy_w += score
            else:
                sell_w += score
            for key in ("moveMedianPips", "moveLowPips", "moveHighPips"):
                val = m.get(key)
                if val is not None:
                    move_pips.append(float(val))
        total = buy_w + sell_w
        if total == 0:
            return AgentResult(self.id, self.name, self.weight, abstention="DATA_INSUFFICIENT",
                               reasoning="Historical matches carry no directional signal",
                               data={"matches": len(matches)})
        direction = "buy" if buy_w >= sell_w else "sell"
        strength = max(buy_w, sell_w) / total
        confidence = clamp01(strength * 0.8)
        median_pips = _median(move_pips) if move_pips else 0.0
        return AgentResult(
            self.id, self.name, self.weight,
            direction=direction,
            confidence=confidence,
            reasoning=f"{len(matches)} similar historical events; median move {median_pips:.1f} pips {direction}",
            abstention="TRADE",
            data={
                "historicalMatch": round(strength, 3),
                "moveLowPips": round(min(move_pips), 1) if move_pips else None,
                "moveMedianPips": round(median_pips, 1),
                "moveHighPips": round(max(move_pips), 1) if move_pips else None,
                "matches": len(matches),
                "matchIds": [m.get("id") for m in matches[:5]],
            },
        )


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n % 2 == 1:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2

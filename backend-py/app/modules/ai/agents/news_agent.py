"""News Analysis Agent (weight 0.40, directional).

Autonomously fetches live (non-decayed) news, builds a strict-JSON prompt for
the LLM, and requires EXACTLY ``{direction, impact_score, confidence, reason,
expected_pips}``. Invalid JSON or any missing field => ``NO_TRADE`` abstention
(mandatory). The local fallback provider always yields valid JSON so the agent
never hard-fails on provider outage, but low data quality lowers confidence.
"""
import json
import re

from ....foundation.logger import logger
from ..clients import ai_provider_manager, LLMError
from ..memory import embed
from ...news.decay import news_decay_engine
from ...news.engine import get_news
from .base import AgentResult, clamp01

SYSTEM_PROMPT_NEWS = (
    "You are the News Analysis Agent of an institutional gold (XAUUSD) trading system. "
    "News determines 80% of the directional decision. Analyze ONLY the provided news "
    "headlines and return STRICT JSON with exactly these fields:\n"
    '{"direction": "buy"|"sell"|"neutral", "impact_score": 0.0..1.0, '
    '"confidence": 0.0..1.0, "reason": "short explanation", "expected_pips": number}\n'
    "No extra keys. No text outside the JSON object. "
    "If the news is neutral or contradictory, use direction 'neutral'."
)

# Invalid JSON or missing field => mandatory NO_TRADE (per master prompt).
_REQUIRED_FIELDS = ("direction", "impact_score", "confidence", "reason", "expected_pips")

# Schema-aware fallback when only the deterministic local-fallback provider is
# available (no user LLM key). Direction stays neutral (never a fabricated
# directional call from raw headline keyword counts); confidence comes from the
# headline heuristic; neutral defaults cover the remaining fields so the strict
# news schema is always satisfied instead of raising and degrading the 40% voice.
_NEWS_FALLBACK_SHAPE = {
    "direction": "neutral",
    "impact_score": 0.5,
    "confidence": None,
    "reason": None,
    "expected_pips": 0.0,
}


def _strict_parse(text, provider_id):
    text = (text or "").strip()
    if not text:
        raise LLMError(f"{provider_id}: empty completion")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise LLMError(f"{provider_id}: no JSON object returned")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"{provider_id}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError(f"{provider_id}: JSON is not an object")
    missing = [k for k in _REQUIRED_FIELDS if k not in data]
    if missing:
        raise LLMError(f"{provider_id}: missing required fields {missing}")
    direction = str(data["direction"]).lower()
    if direction not in ("buy", "sell", "neutral"):
        raise LLMError(f"{provider_id}: invalid direction '{data['direction']}'")
    return {
        "direction": direction,
        "impact_score": clamp01(data["impact_score"]),
        "confidence": clamp01(data["confidence"]),
        "reason": str(data["reason"]),
        "expected_pips": float(data["expected_pips"]),
    }


class NewsAnalysisAgent:
    id = "news"
    name = "NewsAnalysisAgent"
    weight = 0.40

    async def run(self, context=None):
        context = context or {}
        live = news_decay_engine.filter_live(get_news({"limit": 50}))
        news = live[:10]
        if not news:
            return AgentResult(self.id, self.name, self.weight, direction="neutral", confidence=0.0,
                               abstention="DATA_INSUFFICIENT",
                               reasoning="No live news available for analysis", data={"newsCount": 0})
        headlines = "\n".join(f"- [{n.get('source')}] {n.get('title')}" for n in news)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_NEWS},
            {"role": "user", "content": f"News headlines (gold context, current time UTC):\n{headlines}\nReturn strict JSON."},
        ]
        manager = ai_provider_manager
        if manager is None:
            return AgentResult(self.id, self.name, self.weight, abstention="PROVIDER_DEGRADED",
                               reasoning="LLM provider clients not initialized", data={"newsCount": len(news)})
        try:
            parsed = manager.complete_custom(messages, parser=_strict_parse, fallback_shape=_NEWS_FALLBACK_SHAPE,
                                             temperature=0.1, max_tokens=500)
        except LLMError as exc:
            logger.warn(f"News agent LLM failed: {exc}")
            return AgentResult(self.id, self.name, self.weight, abstention="PROVIDER_DEGRADED",
                               reasoning=f"LLM failure: {exc}", data={"newsCount": len(news)})
        # Weight confidence by the quality/recency of the news corpus.
        avg_trust = sum(float(n.get("trustScore") or 0.5) for n in news) / len(news)
        avg_confidence = sum(float(n.get("confidence") or 0.5) for n in news) / len(news)
        quality = clamp01(0.5 * avg_trust + 0.5 * avg_confidence)
        conf = clamp01(parsed["confidence"] * quality)
        direction = parsed["direction"] if parsed["direction"] != "neutral" else "neutral"
        return AgentResult(
            self.id, self.name, self.weight,
            direction=direction,
            confidence=conf,
            reasoning=parsed["reason"],
            abstention="TRADE",
            data={
                "impactScore": parsed["impact_score"],
                "expectedPips": parsed["expected_pips"],
                "newsCount": len(news),
                "corpusQuality": round(quality, 3),
                "newsIds": [n.get("id") for n in news],
                "provider": parsed.get("model"),
            },
        )

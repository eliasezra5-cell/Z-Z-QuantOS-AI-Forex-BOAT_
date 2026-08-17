"""Social Sentiment Agent (Feature 2, additive, custom pool).

Aggregates real sentiment data from two sources:
  1. social sentiment collector output (StockTwits-compatible, via
     ``news/social_collectors.collect_social_sentiment``), and
  2. live (non-decayed) news items carrying an inferred ``sentiment`` field.

The aggregate score is computed deterministically (data-driven) and then
optionally enriched by the LLM into a narrative label + source breakdown.
The LLM is enrichment only — if it fails the agent still returns a TRADE result
from the data, so a social-source outage never blocks the pipeline. A symbol
with no social or news data at all returns a clean ``DATA_INSUFFICIENT``.
"""
import json
import re

from ....foundation.logger import logger
from ..clients import ai_provider_manager, LLMError
from ..agents.base import AgentResult, clamp01
from ...news.decay import news_decay_engine
from ...news.engine import get_news
from ...news.social_collectors import collect_social_sentiment

AGENT_ID = "custom-sentiment"
AGENT_NAME = "SentimentAnalysisAgent"
AGENT_WEIGHT = 0.10
DIRECTION_THRESHOLD = 0.15

SYSTEM_PROMPT_SENTIMENT = (
    "You are the Social Sentiment Agent of an institutional trading system. "
    "Given aggregated sentiment data, return STRICT JSON with exactly these fields:\n"
    '{"sentimentScore": -1.0..1.0, "label": "strongly_bullish"|"bullish"|"neutral"|"bearish"|"strongly_bearish", '
    '"confidence": 0.0..1.0, "sourceBreakdown": {"news": {"count": number, "avgSentiment": number}, '
    '"social": {"count": number, "avgSentiment": number}}}\n'
    "No extra keys. No text outside the JSON object."
)

_REQUIRED_FIELDS = ("sentimentScore", "label", "confidence", "sourceBreakdown")


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
    return data


def _aggregate(news, social):
    """Data-driven aggregate score, label and breakdown. Never raises."""
    news_avg = 0.0
    social_avg = 0.0
    if news:
        weighted = sum(float(n.get("sentiment") or 0.0) * float(n.get("confidence") or 0.5) for n in news)
        news_avg = weighted / len(news)
    if social:
        social_avg = sum(float(s.get("sentiment") or 0.0) for s in social) / len(social)
    news_count = len(news)
    social_count = len(social)
    if news_count + social_count == 0:
        return None
    total = news_count + social_count
    score = (news_avg * news_count + social_avg * social_count) / total
    score = max(-1.0, min(1.0, score))
    if score >= 0.6:
        label = "strongly_bullish"
    elif score >= DIRECTION_THRESHOLD:
        label = "bullish"
    elif score <= -0.6:
        label = "strongly_bearish"
    elif score <= -DIRECTION_THRESHOLD:
        label = "bearish"
    else:
        label = "neutral"
    breakdown = {
        "news": {"count": news_count, "avgSentiment": round(news_avg, 3)},
        "social": {"count": social_count, "avgSentiment": round(social_avg, 3)},
    }
    return {"score": score, "label": label, "breakdown": breakdown}


class SentimentAnalysisAgent:
    id = AGENT_ID
    name = AGENT_NAME
    weight = AGENT_WEIGHT

    async def run(self, context=None):
        context = context or {}
        symbol = context.get("symbol") or "XAUUSD"
        social = collect_social_sentiment(symbol, limit=20)
        live = news_decay_engine.filter_live(get_news({"limit": 50}))
        news = live[:10]
        aggregate = _aggregate(news, social)
        if aggregate is None:
            return AgentResult(self.id, self.name, self.weight, direction="neutral", confidence=0.0,
                               abstention="DATA_INSUFFICIENT",
                               reasoning="No social or news sentiment data available",
                               data={"sentimentScore": 0.0, "label": "neutral", "confidence": 0.0,
                                     "sourceBreakdown": {"news": {"count": 0, "avgSentiment": 0.0},
                                                         "social": {"count": 0, "avgSentiment": 0.0}}})
        score = aggregate["score"]
        label = aggregate["label"]
        breakdown = aggregate["breakdown"]

        # Optional LLM enrichment; deterministic result is always the fallback.
        try:
            if ai_provider_manager is not None:
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT_SENTIMENT},
                    {"role": "user", "content": (
                        f"Symbol: {symbol}. Aggregated sentiment data:\n"
                        f"{json.dumps({'score': round(score, 3), 'label': label, 'sourceBreakdown': breakdown})}\n"
                        "Return strict JSON.")},
                ]
                enriched = ai_provider_manager.complete_custom(
                    messages, parser=_strict_parse, temperature=0.1, max_tokens=400)
                s = float(enriched.get("sentimentScore", score))
                score = max(-1.0, min(1.0, s)) if s != 0 else score
                if enriched.get("label"):
                    label = str(enriched["label"])
                breakdown = enriched.get("sourceBreakdown") or breakdown
        except (LLMError, TypeError, ValueError) as exc:
            logger.warn(f"Sentiment agent LLM enrichment failed, using data fallback: {exc}")

        if score > DIRECTION_THRESHOLD:
            direction = "buy"
        elif score < -DIRECTION_THRESHOLD:
            direction = "sell"
        else:
            direction = "neutral"
        confidence = clamp01(min(0.9, abs(score) + 0.15))
        return AgentResult(
            self.id, self.name, self.weight,
            direction=direction,
            confidence=confidence,
            reasoning=f"Sentiment {label} (score {round(score, 3)}) from "
                      f"{breakdown.get('news', {}).get('count', 0)} news + "
                      f"{breakdown.get('social', {}).get('count', 0)} social items",
            abstention="TRADE",
            data={
                "sentimentScore": round(score, 3),
                "label": label,
                "confidence": round(confidence, 3),
                "sourceBreakdown": breakdown,
            },
        )

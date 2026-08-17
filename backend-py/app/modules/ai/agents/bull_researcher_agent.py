"""Bull Researcher Agent (Feature 1 — debate stage).

Builds the strongest evidence-based long case from the existing core analyst
reads (news / historical / macro / technical / risk) and rebuts the points a
bear researcher is likely to raise. Follows the exact agent pattern of
``news_agent.py``: strict-JSON completion through ``ai_provider_manager``,
``DATA_INSUFFICIENT`` when no core context exists, ``PROVIDER_DEGRADED`` on
LLM failure. The produced ``{stance, argument, confidence, counters}`` is
consumed by ``ResearchManager.resolve`` — this agent does not vote directly in
the strict 80/20 consensus.
"""
import json
import re

from ....foundation.logger import logger
from ..clients import ai_provider_manager, LLMError
from .base import AgentResult, clamp01

SYSTEM_PROMPT_BULL = (
    "You are the BULL researcher in a professional buy-side vs sell-side debate "
    "for an institutional gold (XAUUSD) trading system. Build the STRONGEST "
    "evidence-based case FOR the long side using ONLY the provided analyst reads. "
    "Anticipate the specific points a bear researcher will raise and rebut them. "
    "Return STRICT JSON with exactly these fields:\n"
    '{"stance": "bull", "argument": "concise but forceful thesis", '
    '"confidence": 0.0..1.0, "counters": ["rebuttal point", "..."]}\n'
    "No extra keys. No text outside the JSON object."
)

_REQUIRED_FIELDS = ("stance", "argument", "confidence", "counters")


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
    stance = str(data["stance"]).lower()
    if stance != "bull":
        raise LLMError(f"{provider_id}: invalid stance '{data['stance']}'")
    counters = data.get("counters") or []
    if not isinstance(counters, list):
        counters = [str(counters)]
    return {
        "stance": stance,
        "argument": str(data["argument"]),
        "confidence": clamp01(data["confidence"]),
        "counters": [str(c) for c in counters][:5],
    }


def _format_core_results(core_results):
    lines = []
    for r in core_results or []:
        lines.append(
            f"- {r.get('name')} (weight {r.get('weight')}): direction={r.get('direction')} "
            f"confidence={r.get('confidence')} abstention={r.get('abstention')} "
            f"reasoning=\"{r.get('reasoning') or ''}\""
        )
    return "\n".join(lines)


class BullResearcherAgent:
    id = "bull"
    name = "BullResearcherAgent"
    weight = 0.10

    async def run(self, context=None):
        context = context or {}
        core_results = context.get("core_results") or []
        symbol = context.get("symbol", "XAUUSD")
        if not core_results:
            return AgentResult(self.id, self.name, self.weight, abstention="DATA_INSUFFICIENT",
                               reasoning="No core analyst reads available for the bull case",
                               data={"stance": "bull", "argument": "", "confidence": 0.0, "counters": []})
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_BULL},
            {"role": "user", "content": (
                f"Symbol: {symbol}\nCore analyst reads:\n{_format_core_results(core_results)}\n"
                "Return strict JSON."
            )},
        ]
        manager = ai_provider_manager
        if manager is None:
            return AgentResult(self.id, self.name, self.weight, abstention="PROVIDER_DEGRADED",
                               reasoning="LLM provider clients not initialized",
                               data={"stance": "bull", "argument": "", "confidence": 0.0, "counters": []})
        try:
            parsed = manager.complete_custom(messages, parser=_strict_parse, temperature=0.4, max_tokens=700)
        except LLMError as exc:
            logger.warn(f"Bull researcher LLM failed: {exc}")
            return AgentResult(self.id, self.name, self.weight, abstention="PROVIDER_DEGRADED",
                               reasoning=f"LLM failure: {exc}",
                               data={"stance": "bull", "argument": "", "confidence": 0.0, "counters": []})
        return AgentResult(
            self.id, self.name, self.weight,
            direction="buy",
            confidence=clamp01(parsed["confidence"]),
            reasoning=parsed["argument"],
            abstention="TRADE",
            data={
                "stance": "bull",
                "argument": parsed["argument"],
                "confidence": parsed["confidence"],
                "counters": parsed["counters"],
                "provider": parsed.get("model"),
            },
        )

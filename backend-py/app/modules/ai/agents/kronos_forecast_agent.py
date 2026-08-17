"""Kronos Forecast Agent (additive, capped custom pool).

Votes a directional read from the Kronos foundation-model candlestick forecast
(NeoQuasar/Kronos-mini) as ONE capped custom agent (``custom-kronos-forecast``,
weight 0.08 — never above 0.10). The core 80/20 formula, the technical
execution gate and the risk veto are untouched; news remains the top-weight
family. The model is lazy-loaded via modules/forecasting and the agent
abstains cleanly (``DATA_INSUFFICIENT``) whenever the model or forecast is
unavailable, so a missing torch/model can never crash the pipeline.
"""
from ....foundation.logger import logger
from ...forecasting import kronos_engine
from ..agents.base import AgentResult, clamp01

AGENT_ID = "custom-kronos-forecast"
AGENT_NAME = "KronosForecastAgent"
AGENT_WEIGHT = 0.08


class KronosForecastAgent:
    id = AGENT_ID
    name = AGENT_NAME
    weight = AGENT_WEIGHT

    async def run(self, context=None):
        context = context or {}
        symbol = context.get("symbol") or "XAUUSD"
        try:
            result = kronos_engine.forecast(symbol, horizon=kronos_engine.DEFAULT_HORIZON)
        except Exception as exc:  # noqa: BLE001 - must never break the pipeline
            logger.warn(f"kronos agent: forecast failed ({exc})")
            return AgentResult(
                self.id, self.name, self.weight, direction="neutral", confidence=0.0,
                abstention="DATA_INSUFFICIENT",
                reasoning="Kronos forecast unavailable (model failed)",
                data={"available": False, "error": str(exc)},
            )

        if result.get("status") != "ok":
            return AgentResult(
                self.id, self.name, self.weight, direction="neutral", confidence=0.0,
                abstention="DATA_INSUFFICIENT",
                reasoning=f"Kronos forecast unavailable: {result.get('error')}",
                data={"available": False, "error": result.get("error")},
            )

        direction = result.get("direction") or "neutral"
        if direction == "neutral":
            return AgentResult(
                self.id, self.name, self.weight, direction="neutral", confidence=0.0,
                abstention="CONFLICTING_SIGNALS",
                reasoning=(
                    f"Kronos forecast change {result.get('expectedChangePct')}% "
                    f"over {result.get('horizon')} candles is inside the neutral band"
                ),
                data={"available": True, **result},
            )

        confidence = clamp01(result.get("confidence", 0.0))
        return AgentResult(
            self.id, self.name, self.weight,
            direction=direction,
            confidence=confidence,
            abstention="TRADE",
            reasoning=(
                f"Kronos {direction} forecast: {result.get('expectedChangePct')}% "
                f"over {result.get('horizon')} candles (model {result.get('model')})"
            ),
            data={"available": True, **result},
        )

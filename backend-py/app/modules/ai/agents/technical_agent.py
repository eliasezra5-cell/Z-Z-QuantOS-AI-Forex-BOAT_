"""Technical Execution Agent (weight 0.20, EXECUTION ONLY — Phase 4 upgrade).

Analyzes gold (XAUUSD) across M1/M5/M15/H1 with the Advanced SMC Mathematics
pipeline (fractal BOS/CHoCH, Order Blocks + mitigation, FVG fill tracking,
MTF alignment score), then derives entry / SL / TP from structural levels:

  - SL : Order Block or Liquidity Sweep wick + ATR * 0.5 buffer (never fixed).
  - TP : TP1 at the next Liquidity Pool, TP2 at the next unmitigated OB.
  - R/R gate : structural risk/reward below 1:2 rejects the setup.

It NEVER votes on direction (the pipeline maps consensus direction afterwards);
its 20% weight is applied to execution quality only. Output contract with the
consensus engine (``agent_id`` / ``weight`` / ``direction`` / ``confidence`` /
``abstention`` / ``data.execution``) is preserved.
"""
from decimal import Decimal

from ....foundation.logger import logger
from ...marketdata.engine import generate_candles, get_quote
from ...technical.smc_math import analyze_mtf
from ...technical.dynamic_sltp import optimize_sltp
from .base import AgentResult, clamp01

CONFIRMED_STATES = {"confirmed", "partially_confirmed", "wait_for_retest"}
MTF_TIMEFRAMES = ("H1", "M15", "M5", "M1")
MTF_MIN_SCORE = 40  # minimum mtf_alignment_score (0-100) to allow execution
MIN_RISK_REWARD = 2.0  # 1:2 structural R/R gate


class TechnicalExecutionAgent:
    id = "technical"
    name = "TechnicalExecutionAgent"
    weight = 0.20

    async def run(self, context=None):
        context = context or {}
        symbol = context.get("symbol", "XAUUSD")
        try:
            candles_by_tf = {tf: generate_candles(symbol, tf, 300) for tf in MTF_TIMEFRAMES}
            quote = get_quote(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"Technical agent data fetch failed: {exc}")
            return AgentResult(self.id, self.name, self.weight, abstention="DATA_INSUFFICIENT",
                               reasoning=f"Technical data unavailable: {exc}", data={})
        if any(len(candles_by_tf.get(tf) or []) < 40 for tf in MTF_TIMEFRAMES):
            return AgentResult(self.id, self.name, self.weight, abstention="DATA_INSUFFICIENT",
                               reasoning="Not enough candles for multi-timeframe SMC analysis",
                               data={"candles": {tf: len(candles_by_tf.get(tf) or []) for tf in MTF_TIMEFRAMES}})

        mtf = analyze_mtf(candles_by_tf)
        alignment = mtf["mtf"]
        h1 = mtf["timeframes"].get("H1") or {}
        h1_atr = h1.get("atr") or Decimal("0")
        price = Decimal(str(quote.get("bid") or candles_by_tf["H1"][-1]["close"]))

        side = "buy" if alignment["bias"] == "bullish" else ("sell" if alignment["bias"] == "bearish" else None)
        sltp = None
        if side:
            sltp = optimize_sltp(side, price, h1, h1_atr, candles=candles_by_tf["H1"], min_rr=MIN_RISK_REWARD)

        execution_ok = bool(
            side
            and alignment["score"] >= MTF_MIN_SCORE
            and sltp is not None
            and sltp["approved"]
        )

        # Technical NEVER decides direction: it only confirms execution quality.
        direction = "neutral"
        confidence = clamp01(0.85 if execution_ok else 0.30)

        h1_summary = h1.get("summary") or {}
        h1_structure = h1.get("structure") or {}
        if not side:
            sltp_reason = "neutral MTF bias (no aligned direction for structure levels)"
        elif sltp is None:
            sltp_reason = "no structural SL/TP anchors found"
        else:
            sltp_reason = sltp.get("reason", "")
        reasoning = (
            f"MTF alignment {alignment['score']}/100 ({alignment['bias']}); H1 SMC {h1_summary.get('trend')}; "
            f"SL/TP {sltp_reason}; execution {'confirmed' if execution_ok else 'rejected'}"
        )

        data = {
            "execution": "confirmed" if execution_ok else "rejected",
            "state": "confirmed" if execution_ok else "rejected",
            "entry": price,
            "stopLoss": (sltp.get("stopLoss") if sltp else None),
            "takeProfit": (sltp.get("takeProfit")[0] if sltp and sltp.get("takeProfit") else None),
            "takeProfits": (sltp.get("takeProfit") if sltp else []),
            "mtfAlignmentScore": alignment["score"],
            "mtfBias": alignment["bias"],
            "mtf": {tf: info.get("bias") for tf, info in alignment.get("perTimeframe", {}).items()},
            "smc": {
                "trend": h1_summary.get("trend"),
                "orderBlocks": h1_summary.get("orderBlockCount", 0),
                "unmitigatedOrderBlocks": h1_summary.get("unmitigatedOrderBlockCount", 0),
                "fvgs": h1_summary.get("fvgCount", 0),
                "bos": bool(h1_structure.get("bos")),
                "choch": bool(h1_structure.get("choch")),
            },
            "sltp": {
                "stopSource": (sltp.get("stopSource") if sltp else None),
                "stopAnchor": (sltp.get("stopAnchor") if sltp else None),
                "buffer": (sltp.get("buffer") if sltp else None),
                "riskReward": (sltp.get("riskReward") if sltp else None),
                "minRiskReward": MIN_RISK_REWARD,
                "reason": sltp_reason,
            },
        }
        return AgentResult(
            self.id, self.name, self.weight,
            direction=direction,  # execution agent has no directional vote
            confidence=confidence,
            reasoning=reasoning,
            abstention="TRADE" if execution_ok else "REJECTED",
            data=data,
        )

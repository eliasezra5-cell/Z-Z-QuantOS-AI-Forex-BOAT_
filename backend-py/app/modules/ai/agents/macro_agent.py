"""Macro Analysis Agent (weight 0.20, directional).

Autonomously fetches REAL macro data (DXY, VIX, Oil, bond yields) and derives
``macro_alignment`` + ``confidence`` plus a risk_on/crisis regime. Unavailable
data reduces confidence and may force an abstention when nothing is available.
"""
from ....modules.macro.realtime import fetch_macro_snapshot
from .base import AgentResult, clamp01


class MacroAnalysisAgent:
    id = "macro"
    name = "MacroAnalysisAgent"
    weight = 0.20

    async def run(self, context=None):
        context = context or {}
        snapshot = fetch_macro_snapshot()
        available = int(snapshot.get("dataAvailable") or 0)
        if available == 0:
            return AgentResult(self.id, self.name, self.weight, abstention="DATA_INSUFFICIENT",
                               reasoning="No macro data available (all sources unreachable)",
                               data={"dataAvailable": 0})

        vix = snapshot.get("vix")
        us10y = snapshot.get("us10y")
        us2y = snapshot.get("us2y")
        dxy = snapshot.get("dxy")

        # Regime detection: crisis when VIX elevated (>= 25) or 10Y - 2Y inverted (< 0).
        yield_curve = (us10y - us2y) if (us10y is not None and us2y is not None) else None
        regime = "normal"
        if vix is not None and vix >= 25:
            regime = "crisis"
        elif yield_curve is not None and yield_curve < 0:
            regime = "crisis"

        risk_on = not (regime == "crisis")
        # Directional alignment: risk-off (crisis) favors gold (safe haven) => buy;
        # a weak dollar (low DXY) also favors gold.
        signals = 0
        total = 0
        if regime == "crisis":
            signals += 1  # risk-off supports gold
            total += 1
        if dxy is not None:
            total += 1
            if dxy < 103.0:
                signals += 1  # weak dollar supports gold
            else:
                signals -= 1
        direction = "neutral"
        if signals > 0:
            direction = "buy"
        elif signals < 0:
            direction = "sell"
        alignment = (signals / total) if total else 0.0
        confidence = clamp01(abs(alignment) * (0.4 + 0.4 * min(available, 4) / 4.0))
        return AgentResult(
            self.id, self.name, self.weight,
            direction=direction,
            confidence=confidence,
            reasoning=f"Regime {regime} (risk-{'on' if risk_on else 'off'}), VIX={vix}, DXY={dxy}, 10Y-2Y={yield_curve if yield_curve is not None else 'n/a'}",
            abstention="TRADE",
            data={
                "macroAlignment": round(alignment, 3),
                "regime": regime,
                "riskOn": risk_on,
                "vix": vix,
                "dxy": dxy,
                "us10y": us10y,
                "us2y": us2y,
                "dataAvailable": available,
            },
        )

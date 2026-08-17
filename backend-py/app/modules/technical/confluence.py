"""Confluence score per timeframe (additive Feature 2).

``compute_confluence`` layers on top of ``aggregate_analysis`` and answers one
question the existing multi-timeframe endpoint leaves implicit: how strongly do
the independent technical factors converge on the SAME direction for each
timeframe, scaled to 0-100.

Each timeframe's confluence blends two independent measures:
  - signal strength (0-1): how many of the RSI/EMA/MACD/price-action/pattern/SMC
    layers point the same way on that timeframe;
  - cross-timeframe agreement (0-1): the share of OTHER timeframes that agree
    with this timeframe's direction.

Both must agree for a high score, so a strong M1 signal that fights the D1 trend
scores low while a signal confirmed across the hierarchy scores high.
"""
from .multi_timeframe import TIMEFRAMES, aggregate_analysis

_STRENGTH_WEIGHT = 0.55
_AGREEMENT_WEIGHT = 0.45


def _compute_agreement(direction, other_directions):
    if direction not in ("buy", "sell"):
        return 0.0
    if not other_directions:
        return 0.0
    agreeing = sum(1 for d in other_directions if d == direction)
    return agreeing / len(other_directions)


def compute_confluence(candles_by_tf, symbol=None):
    """Return per-timeframe confluence scores (0-100) plus a composite.

    ``candles_by_tf`` maps timeframe -> candles (same shape as the existing
    ``/technical/multitimeframe`` endpoint). Never raises: timeframes without
    enough data are simply skipped.
    """
    analysis = aggregate_analysis(candles_by_tf)
    layers = analysis["layers"]
    alignment = analysis["alignment"]

    directions = {
        tf: layers[tf]["signal"]["direction"]
        for tf in TIMEFRAMES
        if layers.get(tf) and layers[tf].get("signal")
    }

    per_timeframe = []
    for tf in TIMEFRAMES:
        layer = layers.get(tf)
        if not layer or not layer.get("signal"):
            continue
        signal = layer["signal"]
        direction = signal["direction"]
        strength = float(signal.get("strength") or 0.0)
        agreement = _compute_agreement(
            direction,
            [d for other, d in directions.items() if other != tf],
        )
        confluence = round(100 * (_STRENGTH_WEIGHT * min(max(strength, 0.0), 1.0) + _AGREEMENT_WEIGHT * agreement))
        confluence = min(100, max(0, confluence))
        per_timeframe.append({
            "timeframe": tf,
            "direction": direction,
            "score": signal.get("score"),
            "strength": round(strength, 3),
            "agreement": round(agreement, 3),
            "components": len(signal.get("reasons") or []),
            "confluence": confluence,
        })

    if per_timeframe:
        composite = round(sum(p["confluence"] for p in per_timeframe) / len(per_timeframe))
    else:
        composite = 0

    return {
        "symbol": symbol or analysis.get("symbol"),
        "timeframes": per_timeframe,
        "composite": composite,
        "bias": alignment["overallBias"],
        "bullCount": alignment["bullCount"],
        "bearCount": alignment["bearCount"],
        "timeframesAnalyzed": len(per_timeframe),
    }

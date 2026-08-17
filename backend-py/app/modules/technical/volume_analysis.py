"""Volume Analysis Indicators (Batch 08, additive).

Adds the missing volume-based indicators to ``technical/indicators.py``:

  - Volume Profile: price-level volume distribution + POC (point of control),
    value area high/low and high/low volume nodes.
  - CVD (Cumulative Volume Delta): running sum of buying vs selling volume.
  - Delta: per-bar (buy volume - sell volume).

These are standalone additive functions; ``calculate_all_indicators`` and all
existing indicators are left untouched. Callers may merge the results via
``enrich_with_volume_analysis``.
"""
from ...foundation.logger import logger


def _is_null(v):
    return v is None or (isinstance(v, float) and (v != v))


def _vol(candle):
    v = candle.get("volume") or candle.get("vol") or candle.get("tickVolume")
    return float(v) if v is not None else 0.0


def delta(candles):
    """Per-bar buy-minus-sell volume.

    When candle carries explicit buyVolume/sellVolume use it; otherwise infer
    by close position inside the bar range (volume weighted by close location).
    """
    out = []
    for c in candles:
        bv = c.get("buyVolume")
        sv = c.get("sellVolume")
        if bv is not None and sv is not None:
            out.append(float(bv) - float(sv))
            continue
        high = c.get("high", 0.0)
        low = c.get("low", 0.0)
        close = c.get("close", 0.0)
        vol = _vol(c)
        rng = high - low
        if rng and vol:
            location = (close - low) / rng
            out.append(round((location * 2 - 1) * vol, 4))
        else:
            out.append(0.0)
    return out


def cumulative_volume_delta(candles):
    """Running sum of per-bar delta (CVD)."""
    d = delta(candles)
    cvd = []
    acc = 0.0
    for x in d:
        acc += x
        cvd.append(round(acc, 4))
    return {"delta": d, "cvd": cvd}


def volume_profile(candles, bins=24):
    """Volume Profile distribution across price levels.

    Returns POC, value area high/low (70% of volume), HVN/LVN nodes and the
    per-level distribution.
    """
    if not candles:
        return {"poc": None, "valueAreaHigh": None, "valueAreaLow": None, "highVolumeNodes": [], "lowVolumeNodes": [], "levels": []}
    prices = [c["close"] for c in candles if not _is_null(c.get("close"))]
    lo, hi = min(prices), max(prices)
    if hi == lo:
        hi = lo + 1e-9
    step = (hi - lo) / max(1, bins)
    buckets = {round(lo + i * step, 6): 0.0 for i in range(bins)}
    for c in candles:
        vol = _vol(c)
        if vol <= 0:
            continue
        idx = min(int((c["close"] - lo) / step), bins - 1)
        key = round(lo + idx * step, 6)
        buckets[key] = round(buckets.get(key, 0.0) + vol, 4)

    levels = [{"price": k, "volume": v} for k, v in sorted(buckets.items())]
    total = sum(lv["volume"] for lv in levels) or 1e-9
    poc = max(levels, key=lambda lv: lv["volume"]) if levels else None

    # Value area = narrowest range containing >=70% of volume around the POC.
    value_area_high = value_area_low = None
    if poc:
        idx = levels.index(poc)
        lo_idx = hi_idx = idx
        acc = poc["volume"]
        target = total * 0.70
        while acc < target and (lo_idx > 0 or hi_idx < len(levels) - 1):
            lv = levels[lo_idx - 1]["volume"] if lo_idx > 0 else -1
            rv = levels[hi_idx + 1]["volume"] if hi_idx < len(levels) - 1 else -1
            if lv >= rv and lo_idx > 0:
                lo_idx -= 1
                acc += lv
            elif hi_idx < len(levels) - 1:
                hi_idx += 1
                acc += rv
            else:
                break
        value_area_high = levels[hi_idx]["price"]
        value_area_low = levels[lo_idx]["price"]

    mean_vol = total / len(levels)
    hvn = [lv["price"] for lv in levels if lv["volume"] > mean_vol * 2]
    lvn = [lv["price"] for lv in levels if lv["volume"] < mean_vol * 0.25]

    return {
        "poc": poc["price"] if poc else None,
        "valueAreaHigh": value_area_high,
        "valueAreaLow": value_area_low,
        "highVolumeNodes": hvn,
        "lowVolumeNodes": lvn,
        "levels": levels,
    }


def volume_analysis(candles, bins=24):
    """Bundle: delta, CVD and volume profile in one snapshot."""
    cvd = cumulative_volume_delta(candles)
    profile = volume_profile(candles, bins)
    return {
        "delta": cvd["delta"][-1] if cvd["delta"] else 0.0,
        "cvd": cvd["cvd"][-1] if cvd["cvd"] else 0.0,
        "deltaSeries": cvd["delta"],
        "cvdSeries": cvd["cvd"],
        "profile": profile,
    }


def enrich_with_volume_analysis(indicators, candles):
    """Additively attach volume analysis to an existing indicators dict."""
    indicators["volumeAnalysis"] = volume_analysis(candles)
    return indicators


def init_volume_analysis():
    logger.info("Volume analysis indicators (Volume Profile, CVD, Delta) initialized")
    return volume_analysis

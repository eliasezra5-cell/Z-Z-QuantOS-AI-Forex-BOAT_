"""Advanced SMC Mathematics (Phase 4, Module 1 — additive).

Strict, deterministic implementations of Smart Money Concepts using
``Decimal`` for all price math:

  1. Market Structure  — BOS (Break of Structure) & CHoCH (Change of Character)
     derived from fractal swing points (scipy.signal.argrelextrema candidates,
     then strict-Decimal refinement). Closed candles only, never repaints.
  2. Order Blocks      — Bullish/Bearish OB with impulse-gated detection and
     mitigation tracking (price returning into the zone marks it mitigated).
  3. Fair Value Gaps   — 3-candle imbalance detection, fill tracking
     (partial/full fill ratio) and a deterministic 0-100 quality score.
  4. MTF Alignment     — M1/M5/M15/H1 directional alignment -> a single
     ``mtf_alignment_score`` in 0-100%.

pandas/numpy/scipy are used for windowed fractal candidate detection, rolling
ATR and vectorized range math only; every price decision is computed in
Decimal.
"""
from decimal import Decimal, ROUND_HALF_UP

import numpy as np

from ...foundation.logger import logger

FRACTAL_WINDOW = 3
MIN_CANDLES = 40
OB_IMPULSE_ATR = Decimal("1.0")  # move must exceed 1.0 * ATR to count as an impulse
MTF_WEIGHTS = {"H1": Decimal("40"), "M15": Decimal("25"), "M5": Decimal("20"), "M1": Decimal("15")}


# --------------------------------------------------------------------------- #
# Decimal helpers
# --------------------------------------------------------------------------- #
def _D(value, default=Decimal("0")):
    try:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal(str(default))


def _q(value, places=8):
    return _D(value).quantize(Decimal("1." + "0" * places), rounding=ROUND_HALF_UP)


def _dec_candles(candles):
    out = []
    for c in candles or []:
        out.append(
            {
                "time": c.get("time"),
                "open": _D(c.get("open")),
                "high": _D(c.get("high")),
                "low": _D(c.get("low")),
                "close": _D(c.get("close")),
                "volume": c.get("volume"),
                "raw": c,
            }
        )
    return out


# --------------------------------------------------------------------------- #
# ATR (rolling, via pandas/numpy) — feeds OB impulse gates & FVG quality
# --------------------------------------------------------------------------- #
def compute_atr(candles, period=14):
    """Return the EWM ATR of the last `period` candles as a Decimal."""
    candles = _dec_candles(candles)
    if not candles or len(candles) < 2:
        return Decimal("0")
    highs = np.array([float(c["high"]) for c in candles], dtype=float)
    lows = np.array([float(c["low"]) for c in candles], dtype=float)
    closes = np.array([float(c["close"]) for c in candles], dtype=float)
    prev_close = np.roll(closes, 1)
    prev_close[0] = closes[0]
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))
    try:
        import pandas as pd

        atr = float(pd.Series(tr).ewm(alpha=1.0 / max(period, 1), adjust=False).mean().iloc[-1])
    except Exception:  # noqa: BLE001 - pandas is optional; numpy fallback
        atr = float(np.mean(tr[-max(period, 1):]))
    return _D(atr)


# --------------------------------------------------------------------------- #
# 1. Market structure: fractal swings + strict BOS/CHoCH
# --------------------------------------------------------------------------- #
def detect_swing_points(candles, window=FRACTAL_WINDOW):
    """Return strict fractal swing points (closed candles only).

    Uses scipy.signal.argrelextrema to obtain candidate local extrema, then
    re-validates every candidate with strict Decimal comparisons so a swing is
    only confirmed when it is strictly higher/lower than every candle within
    ``window`` bars on each side.
    """
    if not candles or len(candles) < 2 * window + 1:
        return []
    candles = _dec_candles(candles)
    highs = np.array([float(c["high"]) for c in candles], dtype=float)
    lows = np.array([float(c["low"]) for c in candles], dtype=float)
    try:
        from scipy.signal import argrelextrema

        hi_candidates = argrelextrema(highs, np.greater_equal, order=window)[0]
        lo_candidates = argrelextrema(lows, np.less_equal, order=window)[0]
    except Exception:  # noqa: BLE001 - scipy optional; manual scan fallback
        hi_candidates = np.arange(window, len(candles) - window)
        lo_candidates = np.arange(window, len(candles) - window)

    swings = []
    n = len(candles)
    for idx in hi_candidates:
        idx = int(idx)
        if idx - window < 0 or idx + window >= n:
            continue  # not a closed fractal yet (anti-repaint)
        price = candles[idx]["high"]
        strict = all(price > candles[j]["high"] for j in range(idx - window, idx + window + 1) if j != idx)
        if strict:
            swings.append({"index": idx, "type": "swingHigh", "price": price, "time": candles[idx].get("time")})
    for idx in lo_candidates:
        idx = int(idx)
        if idx - window < 0 or idx + window >= n:
            continue
        price = candles[idx]["low"]
        strict = all(price < candles[j]["low"] for j in range(idx - window, idx + window + 1) if j != idx)
        if strict:
            swings.append({"index": idx, "type": "swingLow", "price": price, "time": candles[idx].get("time")})
    swings.sort(key=lambda s: s["index"])
    return swings


def detect_bos_choch(candles, swings, atr=None):
    """Strict BOS/CHoCH from the swing sequence.

    A new swing beyond the running opposite-side level continues the trend
    (BOS) when it matches the current trend, and signals a reversal (CHoCH)
    when it breaks against it. Runs on closed fractals only.
    """
    n = len(candles)
    trend = "neutral"
    last_high = None
    last_low = None
    last_bos = None
    last_choch = None
    sequence = []

    for s in swings:
        if s["index"] + FRACTAL_WINDOW >= n:
            continue  # only act on already-closed structure
        if s["type"] == "swingHigh":
            if last_high is not None and s["price"] > last_high:
                if trend in ("bullish", "neutral"):
                    last_bos = {
                        "type": "BOS", "direction": "up", "index": s["index"],
                        "price": s["price"], "breakLevel": last_high,
                    }
                    trend = "bullish"
                else:
                    last_choch = {
                        "type": "CHoCH", "direction": "up", "index": s["index"],
                        "price": s["price"], "breakLevel": last_high,
                    }
                    trend = "bullish"
                sequence.append({"index": s["index"], "kind": last_bos["type"] if last_bos else "CHoCH", "direction": "up"})
            last_high = s["price"]
        else:  # swingLow
            if last_low is not None and s["price"] < last_low:
                if trend in ("bearish", "neutral"):
                    last_bos = {
                        "type": "BOS", "direction": "down", "index": s["index"],
                        "price": s["price"], "breakLevel": last_low,
                    }
                    trend = "bearish"
                else:
                    last_choch = {
                        "type": "CHoCH", "direction": "down", "index": s["index"],
                        "price": s["price"], "breakLevel": last_low,
                    }
                    trend = "bearish"
                sequence.append({"index": s["index"], "kind": last_choch["type"] if last_choch else "BOS", "direction": "down"})
            last_low = s["price"]

    return {
        "trend": trend,
        "bos": last_bos,
        "choch": last_choch,
        "lastSwingHigh": last_high,
        "lastSwingLow": last_low,
        "sequence": sequence[-6:],
    }


# --------------------------------------------------------------------------- #
# 2. Order Blocks + mitigation
# --------------------------------------------------------------------------- #
def detect_order_blocks(candles, atr=None):
    """Detect impulse-gated bullish/bearish Order Blocks.

    Bullish OB: last bearish candle before a down->up impulse where the next
    candle's close exceeds the prior candle's high. Bearish OB mirrors it.
    Zone follows the body of the initiating candle. Every OB carries
    ``mitigated`` state updated by ``track_ob_mitigation``.
    """
    atr = _D(atr) if atr is not None else compute_atr(candles)
    candles = _dec_candles(candles)
    obs = []
    n = len(candles)
    for i in range(1, n - 1):
        prev, cur, nxt = candles[i - 1], candles[i], candles[i + 1]
        # Bullish OB: bearish candle followed by an impulsive bullish break
        if cur["close"] < cur["open"] and nxt["close"] > cur["high"]:
            impulse = nxt["close"] - cur["high"]
            if atr > 0 and impulse < OB_IMPULSE_ATR * atr:
                continue
            zone_low = min(cur["low"], prev["low"])
            zone_high = min(prev["open"], prev["close"]) if cur["close"] < cur["open"] else cur["open"]
            if zone_high > zone_low:
                obs.append(
                    {
                        "type": "bullish",
                        "zone": [zone_low, zone_high],
                        "price": cur["low"],
                        "size": cur["high"] - cur["low"],
                        "index": i,
                        "impulse": impulse,
                        "mitigated": False,
                        "mitigationRatio": Decimal("0"),
                        "mitigatedAt": None,
                    }
                )
        # Bearish OB: bullish candle followed by an impulsive bearish break
        if cur["close"] > cur["open"] and nxt["close"] < cur["low"]:
            impulse = cur["low"] - nxt["close"]
            if atr > 0 and impulse < OB_IMPULSE_ATR * atr:
                continue
            zone_low = max(cur["open"], cur["close"]) if cur["close"] > cur["open"] else cur["open"]
            zone_high = max(cur["high"], prev["high"])
            if zone_high > zone_low:
                obs.append(
                    {
                        "type": "bearish",
                        "zone": [zone_low, zone_high],
                        "price": cur["high"],
                        "size": cur["high"] - cur["low"],
                        "index": i,
                        "impulse": impulse,
                        "mitigated": False,
                        "mitigationRatio": Decimal("0"),
                        "mitigatedAt": None,
                    }
                )
    return obs


def track_ob_mitigation(candles, obs):
    """Mark each OB as mitigated when a later candle trades back into its zone."""
    candles = _dec_candles(candles)
    out = []
    n = len(candles)
    for ob in obs:
        entry = dict(ob)
        zone = entry.get("zone")
        if not zone or len(zone) != 2 or zone[1] <= zone[0]:
            out.append(entry)
            continue
        z_low, z_high = min(zone), max(zone)
        zone_size = z_high - z_low
        best_ratio = Decimal("0")
        mitigated_at = None
        for i in range(ob["index"] + 1, n):
            c = candles[i]
            overlap_low = max(c["low"], z_low)
            overlap_high = min(c["high"], z_high)
            if overlap_high > overlap_low and zone_size > 0:
                ratio = _D((overlap_high - overlap_low) / zone_size)
                if ratio > best_ratio:
                    best_ratio = ratio
                    mitigated_at = i
                if overlap_high >= z_high and overlap_low <= z_low:
                    best_ratio = Decimal("1")
                    mitigated_at = i
                    break
        entry["mitigated"] = best_ratio > Decimal("0")
        entry["mitigationRatio"] = _q(best_ratio)
        entry["mitigatedAt"] = mitigated_at
        out.append(entry)
    return out


# --------------------------------------------------------------------------- #
# 3. Fair Value Gaps (3-candle imbalance) + fill tracking + quality
# --------------------------------------------------------------------------- #
def detect_fvgs(candles, atr=None):
    """Detect 3-candle imbalance FVGs.

    Bullish FVG at candle i: low[i+1] > high[i-1]. Bearish FVG mirrors it.
    Zones are [high[i-1], low[i+1]] / [low[i-1], high[i+1]].
    """
    atr = _D(atr) if atr is not None else compute_atr(candles)
    candles = _dec_candles(candles)
    fvgs = []
    n = len(candles)
    for i in range(1, n - 1):
        prev, nxt = candles[i - 1], candles[i + 1]
        gap_up = nxt["low"] - prev["high"]
        if gap_up > 0 and (atr <= 0 or gap_up >= Decimal("0.05") * atr):
            fvgs.append(
                {
                    "type": "bullish",
                    "zone": [prev["high"], nxt["low"]],
                    "price": (prev["high"] + nxt["low"]) / Decimal("2"),
                    "size": gap_up,
                    "index": i,
                }
            )
        gap_down = prev["low"] - nxt["high"]
        if gap_down > 0 and (atr <= 0 or gap_down >= Decimal("0.05") * atr):
            fvgs.append(
                {
                    "type": "bearish",
                    "zone": [nxt["high"], prev["low"]],
                    "price": (nxt["high"] + prev["low"]) / Decimal("2"),
                    "size": gap_down,
                    "index": i,
                }
            )
    return fvgs


def track_fvg_fill(candles, fvgs):
    """Fill tracking: how much of each FVG zone price later traded through."""
    candles = _dec_candles(candles)
    out = []
    n = len(candles)
    for fvg in fvgs:
        entry = dict(fvg)
        zone = entry.get("zone") or []
        if len(zone) != 2 or zone[1] <= zone[0]:
            entry.update({"filled": False, "fillRatio": Decimal("0"), "fillIndex": None, "filledAt": None})
            out.append(entry)
            continue
        z_low, z_high = min(zone), max(zone)
        zone_size = z_high - z_low
        best_ratio = Decimal("0")
        fill_index = None
        filled = False
        for i in range(entry["index"] + 1, n):
            c = candles[i]
            overlap_low = max(c["low"], z_low)
            overlap_high = min(c["high"], z_high)
            if overlap_high > overlap_low and zone_size > 0:
                ratio = _D((overlap_high - overlap_low) / zone_size)
                if ratio > best_ratio:
                    best_ratio = ratio
                    fill_index = i
                if overlap_high >= z_high and overlap_low <= z_low:
                    best_ratio = Decimal("1")
                    fill_index = i
                    filled = True
                    break
        entry.update(
            {
                "filled": filled,
                "fillRatio": _q(best_ratio),
                "fillIndex": fill_index,
                "filledAt": candles[fill_index].get("time") if fill_index is not None else None,
            }
        )
        out.append(entry)
    return out


def fvg_quality_score(fvg, atr=None, trend=None, total_candles=None):
    """Deterministic 0-100 FVG quality.

    Smaller gap relative to ATR scores higher (tight imbalances are favored),
    recent formations score higher, and gaps aligned with the prevailing
    structure trend receive a bonus.
    """
    size = _D(fvg.get("size"))
    atr = _D(atr) if atr is not None else Decimal("0")
    if atr <= 0:
        atr = Decimal("1")
    rel = size / atr if atr > 0 else Decimal("1")

    size_component = max(Decimal("0"), min(Decimal("100"), Decimal("100") - Decimal("55") * rel))

    total = total_candles or _D(fvg.get("totalCandles"))
    idx = _D(fvg.get("index"))
    if total and total > 0:
        recency = max(Decimal("0"), min(Decimal("1"), (total - idx) / total))
    else:
        recency = Decimal("0.5")

    quality = Decimal("0.6") * size_component + Decimal("0.4") * recency * Decimal("100")

    if trend in ("bullish", "bearish"):
        aligned = (fvg.get("type") == "bullish" and trend == "bullish") or (fvg.get("type") == "bearish" and trend == "bearish")
        if aligned:
            quality += Decimal("5")

    return int(max(Decimal("0"), min(Decimal("100"), quality)).to_integral_value(rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- #
# 4. Multi-timeframe alignment (M1/M5/M15/H1) -> 0-100 score
# --------------------------------------------------------------------------- #
def _tf_bias(candles):
    """Compute a single-TF directional bias from advanced SMC structure."""
    if not candles or len(candles) < MIN_CANDLES:
        return {"bias": "neutral", "trend": "neutral", "reason": "insufficient"}
    dec = _dec_candles(candles)
    swings = detect_swing_points(dec)
    structure = detect_bos_choch(dec, swings)
    trend = structure["trend"]
    price = dec[-1]["close"]
    highs = [_q(s["price"]) for s in swings if s["type"] == "swingHigh"]
    lows = [_q(s["price"]) for s in swings if s["type"] == "swingLow"]
    bias = "neutral"
    if trend == "bullish":
        bias = "bullish"
    elif trend == "bearish":
        bias = "bearish"
    else:
        hh = max(highs + [price]) if highs else price
        ll = min(lows + [price]) if lows else price
        if hh > ll:
            ratio = (price - ll) / (hh - ll)
            if ratio > Decimal("0.5"):
                bias = "bearish"  # premium -> sell bias
            elif ratio < Decimal("0.5"):
                bias = "bullish"  # discount -> buy bias
    return {"bias": bias, "trend": trend, "reason": "structure"}


def compute_mtf_alignment(candles_by_tf):
    """Compute the MTF alignment score (0-100) across M1/M5/M15/H1.

    Higher timeframes carry more weight. The score equals the percentage of
    total weight aligned with the weighted majority direction; a fully aligned
    set of timeframes scores 100, a fully conflicting set scores 0.
    """
    per_tf = {}
    scores = {"bullish": Decimal("0"), "bearish": Decimal("0")}
    weight_used = Decimal("0")
    for tf, weight in MTF_WEIGHTS.items():
        candles = candles_by_tf.get(tf) if isinstance(candles_by_tf, dict) else None
        info = _tf_bias(candles) if candles else {"bias": "neutral", "trend": "neutral", "reason": "no_data"}
        per_tf[tf] = {"weight": int(weight), **info}
        if info["bias"] in ("bullish", "bearish"):
            scores[info["bias"]] += weight
            weight_used += weight

    if weight_used <= 0:
        return {"score": 0, "bias": "neutral", "perTimeframe": per_tf, "weightUsed": 0}

    if scores["bullish"] > scores["bearish"]:
        bias = "bullish"
    elif scores["bearish"] > scores["bullish"]:
        bias = "bearish"
    else:
        bias = "neutral"

    aligned_weight = scores.get(bias, Decimal("0")) if bias != "neutral" else Decimal("0")
    score = int((aligned_weight / weight_used * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))
    return {"score": score, "bias": bias, "perTimeframe": per_tf, "weightUsed": int(weight_used)}


# --------------------------------------------------------------------------- #
# Combined single-timeframe advanced SMC analysis
# --------------------------------------------------------------------------- #
def analyze_advanced_smc(candles, timeframe="H1", total_candles=None):
    """Run the full advanced SMC pipeline on one timeframe.

    Returns structure, order blocks (with mitigation), FVGs (fill + quality),
    premium/discount and a compact summary. Pure function; does not read any
    external state, so it is backtestable.
    """
    if not candles or len(candles) < MIN_CANDLES:
        return {
            "timeframe": timeframe,
            "structure": {"trend": "neutral", "bos": None, "choch": None},
            "orderBlocks": [],
            "fvgs": [],
            "premiumDiscount": None,
            "summary": {"trend": "neutral", "orderBlockCount": 0, "fvgCount": 0},
            "insufficientData": True,
        }
    dec = _dec_candles(candles)
    atr = compute_atr(dec)
    swings = detect_swing_points(dec)
    structure = detect_bos_choch(dec, swings, atr)
    obs = detect_order_blocks(dec, atr)
    obs = track_ob_mitigation(dec, obs)
    fvgs = detect_fvgs(dec, atr)
    total = total_candles or len(dec)
    for f in fvgs:
        f["totalCandles"] = total
        f["atr"] = _q(atr)
        f["quality"] = fvg_quality_score(f, atr, structure["trend"], total)
    fvgs = track_fvg_fill(dec, fvgs)

    price = dec[-1]["close"]
    highs = [_q(s["price"]) for s in swings if s["type"] == "swingHigh"]
    lows = [_q(s["price"]) for s in swings if s["type"] == "swingLow"]
    hh = max(highs + [price]) if highs else price
    ll = min(lows + [price]) if lows else price
    premium_discount = None
    if hh > ll:
        ratio = _q((price - ll) / (hh - ll), 4)
        position = "premium" if ratio > Decimal("0.5") else ("discount" if ratio < Decimal("0.5") else "equilibrium")
        premium_discount = {"position": position, "ratio": ratio, "high": hh, "low": ll, "midpoint": _q((hh + ll) / 2)}

    unmitigated_obs = [ob for ob in obs if not ob["mitigated"]]
    return {
        "timeframe": timeframe,
        "atr": _q(atr),
        "price": price,
        "swings": swings[-10:],
        "structure": structure,
        "orderBlocks": obs[-6:],
        "unmitigatedOrderBlocks": unmitigated_obs[-4:],
        "fvgs": fvgs[-6:],
        "premiumDiscount": premium_discount,
        "summary": {
            "trend": structure["trend"],
            "bos": bool(structure["bos"]),
            "choch": bool(structure["choch"]),
            "orderBlockCount": len(obs),
            "unmitigatedOrderBlockCount": len(unmitigated_obs),
            "fvgCount": len(fvgs),
            "unfilledFvgCount": sum(1 for f in fvgs if not f["filled"]),
        },
        "insufficientData": False,
    }


def analyze_mtf(candles_by_tf):
    """Analyze every available timeframe and compute the MTF alignment score."""
    per_tf = {}
    for tf, candles in (candles_by_tf or {}).items():
        per_tf[tf] = analyze_advanced_smc(candles, tf)
    alignment = compute_mtf_alignment(candles_by_tf)
    return {"timeframes": per_tf, "mtf": alignment}


def init_advanced_smc():
    logger.info("Advanced SMC mathematics initialized (BOS/CHoCH, OB, FVG, MTF alignment)")
    return analyze_mtf

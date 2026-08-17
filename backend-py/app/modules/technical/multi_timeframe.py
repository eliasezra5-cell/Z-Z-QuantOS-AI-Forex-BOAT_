"""Multi-timeframe aggregation mirroring the Node technical/multiTimeframe.js."""
from .indicators import calculate_all_indicators
from .price_action import analyze_price_action
from .candlesticks import detect_patterns
from .smc import analyze_smc

TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"]


def aggregate_analysis(candles_by_tf):
    layers = {}
    for tf in TIMEFRAMES:
        candles = candles_by_tf.get(tf)
        if not candles or len(candles) < 30:
            layers[tf] = None
            continue
        indicators = calculate_all_indicators(candles)
        pa = analyze_price_action(candles)
        patterns = detect_patterns(candles)
        smc = analyze_smc(candles, tf)
        layers[tf] = {
            "timeframe": tf,
            "candles": candles[-2:],
            "price": candles[-1]["close"],
            "indicators": indicators,
            "priceAction": pa,
            "candlesticks": patterns,
            "smc": smc,
            "signal": _combine_signal(indicators, pa, patterns, smc),
        }

    alignment = _compute_alignment(layers)
    h1 = layers.get("H1") or layers.get("H4") or layers.get("M15")
    return {"layers": layers, "alignment": alignment, "bias": alignment["overallBias"], "summary": _build_summary(layers, alignment)}


def _combine_signal(indicators, pa, patterns, smc):
    score = 0.0
    reasons = []
    if indicators["rsi14"] is not None:
        if indicators["rsi14"] > 70:
            score -= 1
            reasons.append("RSI overbought")
        elif indicators["rsi14"] < 30:
            score += 1
            reasons.append("RSI oversold")
    if indicators["ema20"] is not None and indicators["ema50"] is not None:
        if indicators["ema20"] > indicators["ema50"]:
            score += 1
            reasons.append("EMA bullish")
        else:
            score -= 1
            reasons.append("EMA bearish")
    macd_line = indicators["macd"].get("line")
    if macd_line and indicators["macd"].get("signal"):
        last = macd_line[-1]
        sig = indicators["macd"]["signal"][-1]
        if last is not None and sig is not None:
            if last > sig:
                score += 1
                reasons.append("MACD bullish")
            else:
                score -= 1
                reasons.append("MACD bearish")
    if pa["trend"] == "bullish":
        score += 2
        reasons.append("Price action bullish")
    if pa["trend"] == "bearish":
        score -= 2
        reasons.append("Price action bearish")
    bull_p = sum(1 for p in patterns if p["type"] == "bullish")
    bear_p = sum(1 for p in patterns if p["type"] == "bearish")
    if bull_p > bear_p:
        score += 1
        reasons.append(f"{bull_p} bullish patterns")
    if bear_p > bull_p:
        score -= 1
        reasons.append(f"{bear_p} bearish patterns")
    smc_trend = smc.get("summary", {}).get("trend")
    if smc_trend == "bullish":
        score += 1.5
        reasons.append("SMC bullish")
    if smc_trend == "bearish":
        score -= 1.5
        reasons.append("SMC bearish")
    direction = "buy" if score > 1.5 else ("sell" if score < -1.5 else "neutral")
    return {"score": score, "direction": direction, "strength": min(abs(score) / 6, 1), "reasons": reasons[:5]}


def _compute_alignment(layers):
    order = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"]
    seen = [tf for tf in order if layers.get(tf) and layers[tf].get("signal")]
    bull = 0
    bear = 0
    breakdown = []
    for tf in seen:
        direction = layers[tf]["signal"]["direction"]
        breakdown.append({"timeframe": tf, "direction": direction, "score": layers[tf]["signal"]["score"]})
        if direction == "buy":
            bull += 1
        elif direction == "sell":
            bear += 1
    overall_bias = "neutral"
    if bull >= 3 and bull > bear:
        overall_bias = "bullish"
    elif bear >= 3 and bear > bull:
        overall_bias = "bearish"
    return {"alignedTimeframes": seen, "bullCount": bull, "bearCount": bear, "overallBias": overall_bias, "breakdown": breakdown}


def _build_summary(layers, alignment):
    h1 = layers.get("H1") or layers.get("M15")
    price = h1["price"] if h1 else None
    count = len(alignment["alignedTimeframes"])
    ratio = (max(alignment["bullCount"], alignment["bearCount"]) / count) if count else 0
    return {"price": price, "timeframesAnalyzed": count, "bias": alignment["overallBias"], "alignmentRatio": ratio}

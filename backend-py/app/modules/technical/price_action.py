"""Price action analysis mirroring the Node technical/priceAction.js."""
import math

from .indicators import bollinger


def analyze_price_action(candles):
    if len(candles) < 30:
        return {"swings": [], "structure": [], "trend": "neutral", "levels": [], "confluenceLevels": [], "bosChoch": {"bos": [], "choch": []}, "retests": []}
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]

    swings = []
    window = 3
    for i in range(window, len(candles) - window):
        is_high = True
        is_low = True
        for j in range(i - window, i + window + 1):
            if j == i:
                continue
            if highs[j] >= highs[i]:
                is_high = False
            if lows[j] <= lows[i]:
                is_low = False
        if is_high:
            swings.append({"index": i, "type": "high", "price": highs[i], "time": candles[i]["time"]})
        if is_low:
            swings.append({"index": i, "type": "low", "price": lows[i], "time": candles[i]["time"]})
    swings.sort(key=lambda s: s["index"])

    highs_arr = [s["price"] for s in swings if s["type"] == "high"]
    lows_arr = [s["price"] for s in swings if s["type"] == "low"]

    recent_highs = highs_arr[-6:]
    recent_lows = lows_arr[-6:]
    higher_highs = len(recent_highs) >= 2 and recent_highs[-1] > recent_highs[-2]
    higher_lows = len(recent_lows) >= 2 and recent_lows[-1] > recent_lows[-2]
    lower_highs = len(recent_highs) >= 2 and recent_highs[-1] < recent_highs[-2]
    lower_lows = len(recent_lows) >= 2 and recent_lows[-1] < recent_lows[-2]

    trend = "neutral"
    if higher_highs and higher_lows:
        trend = "bullish"
    elif lower_highs and lower_lows:
        trend = "bearish"
    elif higher_highs and not higher_lows:
        trend = "bullish-look"
    elif lower_lows and not lower_highs:
        trend = "bearish-look"

    last = closes[-1]
    ema20 = sum(closes[-20:]) / 20
    ema50 = sum(closes[-50:]) / 50

    structure = []
    latest_type = None
    recent_swings = swings[-8:]
    for i, s in enumerate(recent_swings):
        label = None
        if i >= 1:
            prev = recent_swings[i - 1]
            if s["type"] == "high" and prev["type"] == "high":
                label = "HH" if s["price"] > prev["price"] else "LH"
            if s["type"] == "low" and prev["type"] == "low":
                label = "HL" if s["price"] > prev["price"] else "LL"
        structure.append({**s, "label": label})
        if label:
            latest_type = label

    levels = _build_levels(swings, last)
    confluence = _confluence_levels(candles, last)
    breakout = _detect_breakout(candles, swings, levels)
    summary = _summarize(trend, latest_type, last, ema20, ema50)

    return {
        "trend": trend,
        "trendConfirmed": ema20 > ema50,
        "score": summary["score"],
        "structure": structure,
        "latestStructure": latest_type,
        "swings": swings[-12:],
        "levels": levels,
        "confluenceLevels": confluence,
        "breakout": breakout,
        "bosChoch": identify_bos_choch(candles, structure),
        "retests": detect_retest(candles, levels),
        "summary": summary,
    }


def _build_levels(swings, price):
    zones = []
    for s in swings:
        zone = {"price": s["price"], "type": s["type"], "strength": 1, "distance": abs(s["price"] - price) / price * 100}
        existing = next((z for z in zones if abs(z["price"] - s["price"]) / price < 0.002), None)
        if existing:
            existing["strength"] += 1
        else:
            zones.append(zone)
    zones.sort(key=lambda z: z["distance"])
    return zones[:6]


def _nice_step(price):
    """Round-number step size that scales with the instrument's price magnitude."""
    mag = 10 ** int(math.floor(math.log10(price))) if price > 0 else 1
    for factor in (5, 2, 1):
        if price / (mag * factor) >= 1:
            return mag * factor
    return mag


def _confluence_levels(candles, price):
    """Support/resistance confluence from volume profile, round numbers, Bollinger bands and classic pivots."""
    from .volume_analysis import volume_profile

    zones = []
    closes = [c["close"] for c in candles]

    profile = volume_profile(candles)
    for name, p in (
        ("poc", profile.get("poc")),
        ("valueAreaHigh", profile.get("valueAreaHigh")),
        ("valueAreaLow", profile.get("valueAreaLow")),
    ):
        if p is not None:
            zones.append({"price": round(p, 8), "source": "volumeProfile", "key": name, "strength": 1})

    step = _nice_step(price)
    base = round(price / step) * step
    for offset in (-1, 0, 1):
        r = base + offset * step
        if r != price:
            zones.append({"price": round(r, 8), "source": "roundNumber", "key": "round", "strength": 1})

    bb = bollinger(closes)
    for name in ("upper", "lower"):
        v = bb[name][-1]
        if v is not None:
            zones.append({"price": round(v, 8), "source": "bollinger", "key": name, "strength": 1})

    if len(candles) >= 3:
        h = max(c["high"] for c in candles[-3:])
        l = min(c["low"] for c in candles[-3:])
        c = closes[-1]
        pivot = (h + l + c) / 3
        for name, v in (("pivot", pivot), ("r1", 2 * pivot - l), ("s1", 2 * pivot - h)):
            zones.append({"price": round(v, 8), "source": "pivot", "key": name, "strength": 1})

    seen = {}
    for z in zones:
        key = next((k for k in seen if abs(seen[k]["price"] - z["price"]) / price < 0.002), None)
        if key is None:
            seen[z["price"]] = {**z, "distance": abs(z["price"] - price) / price * 100}
        else:
            seen[key]["strength"] += 1
    result = sorted(seen.values(), key=lambda z: z["distance"])
    return result[:8]


def _detect_breakout(candles, swings, levels):
    last = candles[-1]
    prev = candles[-2]
    resistance = max(c["high"] for c in candles[-20:])
    support = min(c["low"] for c in candles[-20:])
    breakout_type = None
    if last["close"] > resistance and prev["close"] <= resistance:
        breakout_type = "resistance-breakout"
    elif last["close"] < support and prev["close"] >= support:
        breakout_type = "support-breakdown"
    return {"type": breakout_type, "price": last["close"], "resistance": resistance, "support": support, "active": breakout_type is not None}


def _summarize(trend, structure, price, ema20, ema50):
    if trend == "bullish":
        score = 1
    elif trend.startswith("bull"):
        score = 0.6
    elif trend == "bearish":
        score = -1
    elif trend.startswith("bear"):
        score = -0.6
    else:
        score = 0
    bias = "long" if score > 0.3 else ("short" if score < -0.3 else "flat")
    return {
        "price": price,
        "ema20": round(ema20 * 100) / 100,
        "ema50": round(ema50 * 100) / 100,
        "score": score,
        "bias": bias,
        "lastStructure": structure,
    }


def identify_bos_choch(candles, structure):
    """Identify recent break of structure (BOS) and change of character (CHoCH) events."""
    bos = []
    choch = []
    labeled = [s for s in structure if s.get("label") is not None]
    recent = labeled[-6:]
    for s in recent:
        label = s["label"]
        if label == "HH":
            bos.append({"index": s["index"], "price": s["price"], "direction": "up", "type": "BOS"})
        elif label == "LL":
            bos.append({"index": s["index"], "price": s["price"], "direction": "down", "type": "BOS"})
        elif label == "HL":
            choch.append({"index": s["index"], "price": s["price"], "direction": "up", "type": "CHoCH"})
        elif label == "LH":
            choch.append({"index": s["index"], "price": s["price"], "direction": "down", "type": "CHoCH"})
    return {"bos": bos, "choch": choch}


def detect_retest(candles, levels):
    """For each level, detect whether price broke it and then returned to retest it."""
    results = []
    if not candles:
        return results
    n = len(candles)
    for level in levels:
        price = level.get("price", 0)
        tol = price * 0.0008 if price else 0
        broke_index = None
        for i in range(n - 1, 0, -1):
            prev_close = candles[i - 1]["close"]
            cur_close = candles[i]["close"]
            if (prev_close <= price < cur_close) or (prev_close >= price > cur_close):
                broke_index = i
                break
        if broke_index is None:
            touched = any(c["low"] <= price + tol and c["high"] >= price - tol for c in candles[-3:])
            results.append({"price": price, "broke": False, "retested": False, "status": "rejected" if touched else "break_no_retest"})
            continue
        retested = False
        for i in range(broke_index + 1, n):
            c = candles[i]
            if c["low"] <= price + tol and c["high"] >= price - tol:
                retested = True
                break
        status = "retest" if retested else "break_no_retest"
        results.append({"price": price, "broke": True, "retested": retested, "status": status})
    return results


def detect_rejection(candles, level_price):
    """Check the last 3 candles for a long-wick rejection at a level."""
    if len(candles) < 3:
        return {"rejected": False, "side": None, "strength": 0.0}
    rejected = False
    side = None
    strength = 0.0
    for c in candles[-3:]:
        rng = c["high"] - c["low"]
        if rng <= 0:
            continue
        upper_wick = c["high"] - max(c["open"], c["close"])
        lower_wick = min(c["open"], c["close"]) - c["low"]
        tol = rng * 0.1
        if abs(c["high"] - level_price) <= tol and upper_wick > 0.6 * rng:
            rejected = True
            ratio = upper_wick / rng
            if ratio > strength:
                strength = ratio
                side = "bearish"
        if abs(c["low"] - level_price) <= tol and lower_wick > 0.6 * rng:
            rejected = True
            ratio = lower_wick / rng
            if ratio > strength:
                strength = ratio
                side = "bullish"
    return {"rejected": rejected, "side": side, "strength": round(strength, 2)}

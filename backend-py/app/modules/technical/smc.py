"""Smart Money Concepts analysis mirroring the Node technical/smc.js."""
import time
from datetime import datetime, timezone
from enum import Enum


class Confirmation(str, Enum):
    """Deterministic SMC entry-confirmation states (backtestable, non-repainting)."""
    CONFIRMED = "confirmed"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    WAIT_FOR_RETEST = "wait_for_retest"
    REJECTED = "rejected"
    NO_VALID_ENTRY = "no_valid_entry"


def _candle_time(candles, index):
    """Return the raw time field of the candle at `index` (kept as-is, matching candle["time"])."""
    if index is None or index < 0 or index >= len(candles):
        return None
    return candles[index].get("time")


def smc_metadata(candles, trend, structure, last_bos, last_choch):
    """Deterministic metadata: warm-up guard, closed-candle freshness, repaint guard and TF-conflict flag."""
    n = len(candles)
    min_warm_up = 40
    warm_up_met = n >= min_warm_up

    now = time.time()
    last_close_ms = None
    for c in reversed(candles):
        t = c.get("time")
        if t:
            last_close_ms = t if t > 10**12 else t * 1000
            break
    last_candle_age_sec = max(0, now * 1000 - last_close_ms) / 1000 if last_close_ms else None

    pa_trend = trend
    smc_trend = None
    if last_bos:
        smc_trend = "bullish" if last_bos["direction"] == "up" else "bearish"
    if last_choch:
        smc_trend = "reversal-up" if last_choch["direction"] == "up" else "reversal-down"

    conflict = False
    if smc_trend and pa_trend:
        base_smc = smc_trend.removeprefix("reversal-")
        base_pa = pa_trend.split("-")[0]
        conflict = (base_smc == "bullish" and base_pa in ("bearish", "neutral")) or (
            base_smc == "bearish" and base_pa in ("bullish", "neutral")
        )

    return {
        "warmUp": {"required": min_warm_up, "available": n, "met": warm_up_met},
        "repaintGuard": {"closedCandlesOnly": True, "usesOnlyClosedCandles": True, "active": warm_up_met},
        "freshness": {"lastCandleAgeSeconds": round(last_candle_age_sec, 2) if last_candle_age_sec is not None else None},
        "timeframeConflict": {"detected": conflict, "priceActionTrend": pa_trend, "smcTrend": smc_trend},
        "backtestable": True,
        "generatedAt": now,
    }


def analyze_smc(candles, timeframe="H1"):
    if len(candles) < 40:
        return {
            "liquidity": [],
            "orderBlocks": [],
            "fvgs": [],
            "structure": [],
            "premiumDiscount": None,
            "summary": {},
            "equalLevels": [],
            "sweeps": [],
            "killZones": kill_zones(),
            "metadata": smc_metadata(candles, "neutral", [], None, None),
            "confirmation": confirm_setup(
                {"candles": candles, "premiumDiscount": None, "orderBlocks": [], "fvgs": [], "sweeps": [], "equalLevels": [], "bos": None, "choch": None, "structure": []}
            ),
        }
    n = len(candles)
    closes = [c["close"] for c in candles]
    lows = [c["low"] for c in candles]
    highs = [c["high"] for c in candles]
    last = candles[n - 1]
    price = last["close"]

    structure = []
    window = 3
    last_high = None
    last_low = None
    for i in range(window, n - window):
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
            last_high = highs[i]
            structure.append({"index": i, "type": "swingHigh", "price": highs[i], "formationTimestamp": _candle_time(candles, i)})
        if is_low:
            last_low = lows[i]
            structure.append({"index": i, "type": "swingLow", "price": lows[i], "formationTimestamp": _candle_time(candles, i)})
    structure.sort(key=lambda s: s["index"])

    last_bos = None
    last_choch = None
    trend = "neutral"
    prev_swing_type = None
    for s in structure:
        if s["type"] == "swingLow":
            if prev_swing_type == "swingHigh" and last_high is not None:
                broke = s["index"] < n and any(l < (last_high - price * 0.005) for l in lows[s["index"] - 5: s["index"] + 1])
                if broke:
                    last_bos = {"index": s["index"], "price": s["price"], "type": "BOS", "direction": "down"}
            prev_swing_type = "swingLow"
        if s["type"] == "swingHigh":
            if prev_swing_type == "swingLow" and last_low is not None:
                broke = s["index"] < n and any(h > (last_low + price * 0.005) for h in highs[s["index"] - 5: s["index"] + 1])
                if broke:
                    last_bos = {"index": s["index"], "price": s["price"], "type": "BOS", "direction": "up"}
            prev_swing_type = "swingHigh"

    last_index = len(structure) - 1
    if last_index >= 2:
        s1 = structure[last_index - 1]
        s2 = structure[last_index]
        if s1["type"] == "swingHigh" and s2["type"] == "swingLow" and s2["price"] < s1["price"]:
            last_choch = {"index": s2["index"], "price": s2["price"], "type": "CHoCH", "direction": "down"}
        if s1["type"] == "swingLow" and s2["type"] == "swingHigh" and s2["price"] > s1["price"]:
            last_choch = {"index": s2["index"], "price": s2["price"], "type": "CHoCH", "direction": "up"}

    order_blocks = _detect_order_blocks(candles)
    fvgs = _detect_fvgs(candles)
    liquidity = _detect_liquidity(candles, structure, price)
    premium_discount = _detect_premium_discount(candles, structure, price)

    equal_levels = detect_equal_levels(candles, structure)
    sweeps = detect_sweeps(candles, equal_levels, price)
    atr = _estimate_atr(candles)
    fvg_scored = []
    for f in fvgs:
        entry = dict(f)
        entry["atr"] = atr
        entry["totalCandles"] = n
        entry["quality"] = fvg_quality_score(entry)
        fvg_scored.append(entry)
    fvg_out = track_fvg_fill(candles, fvg_scored[-4:], price)
    confirmation = confirm_setup(
        {
            "candles": candles,
            "premiumDiscount": premium_discount,
            "orderBlocks": order_blocks[-4:],
            "fvgs": fvg_out,
            "sweeps": sweeps,
            "equalLevels": equal_levels,
            "bos": last_bos,
            "choch": last_choch,
            "structure": structure,
        }
    )

    if last_bos and last_bos["direction"] == "up":
        trend = "bullish"
    if last_bos and last_bos["direction"] == "down":
        trend = "bearish"
    if last_choch and last_choch["direction"] == "up" and trend == "bearish":
        trend = "reversal-up"
    if last_choch and last_choch["direction"] == "down" and trend == "bullish":
        trend = "reversal-down"

    liquidity_target = liquidity[-1] if liquidity else None
    return {
        "liquidity": liquidity[-6:],
        "orderBlocks": order_blocks[-4:],
        "fvgs": fvg_out,
        "fairValueGaps": fvg_out,
        "structure": structure[-10:],
        "bos": last_bos,
        "choch": last_choch,
        "premiumDiscount": premium_discount,
        "session": _get_session(timeframe),
        "killZone": _is_kill_zone(timeframe),
        "mitigation": _detect_mitigation(candles, order_blocks),
        "equalLevels": equal_levels,
        "sweeps": sweeps,
        "killZones": kill_zones(),
        "confirmation": confirmation,
        "metadata": smc_metadata(candles, trend, structure, last_bos, last_choch),
        "summary": {"trend": trend, "price": price, "liquidityTarget": liquidity_target, "institutionalBias": trend},
    }


def _detect_liquidity(candles, structure, price):
    liquidity = []
    recent_structure = structure[-10:]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    for s in recent_structure:
        if s["type"] == "swingHigh":
            pool = sum(1 for c in candles[s["index"] - 2: s["index"] + 3] if c["high"] >= s["price"] - price * 0.002)
            liquidity.append({"type": "buy-side", "price": s["price"], "strength": min(pool * 2, 10), "distance": abs(price - s["price"]) / price * 100})
        if s["type"] == "swingLow":
            pool = sum(1 for c in candles[s["index"] - 2: s["index"] + 3] if c["low"] <= s["price"] + price * 0.002)
            liquidity.append({"type": "sell-side", "price": s["price"], "strength": min(pool * 2, 10), "distance": abs(price - s["price"]) / price * 100})
    liquidity.sort(key=lambda l: l["distance"])
    above = [l for l in liquidity if l["type"] == "buy-side" and l["price"] > price]
    below = [l for l in liquidity if l["type"] == "sell-side" and l["price"] < price]
    return below[:2] + liquidity[:2] + above[:2]


def _detect_order_blocks(candles):
    obs = []
    for i in range(1, len(candles) - 1):
        prev = candles[i - 1]
        cur = candles[i]
        nxt = candles[i + 1]
        if nxt["close"] > cur["high"] and prev["close"] < prev["open"]:
            obs.append({"type": "bullish", "zone": [cur["low"], min(prev["open"], prev["close"])], "price": cur["low"], "size": cur["high"] - cur["low"], "index": i})
        if nxt["close"] < cur["low"] and prev["close"] > prev["open"]:
            obs.append({"type": "bearish", "zone": [cur["high"], max(prev["open"], prev["close"])], "price": cur["high"], "size": cur["high"] - cur["low"], "index": i})
    return [ob for ob in obs if ob["size"] > 0 and ob["size"] / candles[ob["index"]]["close"] < 0.02]


def _detect_fvgs(candles):
    fvgs = []
    for i in range(1, len(candles) - 1):
        prev = candles[i - 1]
        nxt = candles[i + 1]
        gap = nxt["low"] - prev["high"]
        if gap > 0 and gap / prev["close"] > 0.0005:
            fvgs.append({"type": "bullish", "zone": [prev["high"], nxt["low"]], "price": (prev["high"] + nxt["low"]) / 2, "size": gap, "index": i})
        gap_down = prev["low"] - nxt["high"]
        if gap_down > 0 and gap_down / prev["close"] > 0.0005:
            fvgs.append({"type": "bearish", "zone": [nxt["high"], prev["low"]], "price": (nxt["high"] + prev["low"]) / 2, "size": gap_down, "index": i})
    return [f for f in fvgs if f["size"] / candles[f["index"]]["close"] > 0.0005]


def _detect_premium_discount(candles, structure, price):
    recent = structure[-6:]
    high_vals = [s["price"] for s in recent if s["type"] == "swingHigh"]
    low_vals = [s["price"] for s in recent if s["type"] == "swingLow"]
    hh = max(high_vals + [price])
    ll = min(low_vals + [price])
    if hh == ll:
        return {"position": "discount", "ratio": 0.5, "high": hh, "low": ll}
    ratio = (price - ll) / (hh - ll)
    return {
        "position": "premium" if ratio > 0.5 else ("discount" if ratio < 0.5 else "equilibrium"),
        "ratio": round(ratio * 100) / 100,
        "high": hh,
        "low": ll,
        "midpoint": (hh + ll) / 2,
    }


def _detect_mitigation(candles, order_blocks):
    last = candles[-1]
    price = last["close"]
    touched = [dict(ob, mitigated=True) for ob in order_blocks if ob["zone"][0] <= price <= ob["zone"][1]]
    return touched[-3:]


def _get_session(timeframe):
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60.0
    if 0 <= hour < 8:
        return "asia"
    if 8 <= hour < 13:
        return "london"
    if 13 <= hour < 21:
        return "newyork"
    return "out-of-session"


def kill_zones():
    """Return the 4 named kill zones with active status for the current UTC hour."""
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60.0
    zones = {
        "asian": {"start": 0, "end": 8, "active": 0 <= hour < 8},
        "london_open": {"start": 8, "end": 10, "active": 8 <= hour < 10},
        "london_close": {"start": 15, "end": 17, "active": 15 <= hour < 17},
        "newyork": {"start": 13, "end": 16, "active": 13 <= hour < 16},
    }
    current = "out-of-session"
    for name in ("asian", "london_open", "london_close", "newyork"):
        if zones[name]["active"]:
            if name == "asian":
                current = "asia"
            elif name in ("london_open", "london_close"):
                current = "london"
            else:
                current = "newyork"
            break
    zones["current"] = current
    return zones


def _is_kill_zone(timeframe):
    """Delegates to kill_zones(); returns True when inside any active kill zone."""
    return kill_zones()["current"] != "out-of-session"


def detect_equal_levels(candles, structure, tolerance=0.0005):
    """Detect equal highs / equal lows from swing points within a price tolerance."""
    highs = [(s["index"], s["price"]) for s in structure if s["type"] == "swingHigh"]
    lows = [(s["index"], s["price"]) for s in structure if s["type"] == "swingLow"]
    levels = []
    for pairs, level_type in ((highs, "equal_highs"), (lows, "equal_lows")):
        for i in range(len(pairs)):
            for j in range(i + 1, len(pairs)):
                idx1, p1 = pairs[i]
                idx2, p2 = pairs[j]
                if p1 == 0:
                    continue
                if abs(p1 - p2) / p1 <= tolerance:
                    avg = (p1 + p2) / 2
                    side = "high" if level_type == "equal_highs" else "low"
                    levels.append(
                        {
                            "type": level_type,
                            "price": round(avg, 8),
                            "firstIndex": idx1,
                            "secondIndex": idx2,
                            "swept": _was_swept(candles, idx2, avg, side),
                        }
                    )
    return levels


def detect_sweeps(candles, equal_levels, price):
    """Detect swept liquidity from equal levels whose extreme was exceeded then price closed back inside."""
    sweeps = []
    for level in equal_levels:
        if level["type"] == "equal_highs":
            direction = "sell_sweep"
            side = "high"
        else:
            direction = "buy_sweep"
            side = "low"
        start = level["secondIndex"] + 1
        swept_at = None
        for i in range(start, len(candles)):
            if side == "high" and candles[i]["high"] > level["price"]:
                swept_at = i
                break
            if side == "low" and candles[i]["low"] < level["price"]:
                swept_at = i
                break
        if swept_at is None:
            continue
        closed = None
        for i in range(swept_at, len(candles)):
            if side == "high" and candles[i]["close"] < level["price"]:
                closed = i
                break
            if side == "low" and candles[i]["close"] > level["price"]:
                closed = i
                break
        sweeps.append(
            {"type": "sweep", "level": level["price"], "direction": direction, "sweptAt": swept_at, "valid": closed is not None}
        )
    return sweeps


def track_fvg_fill(candles, fvgs, price):
    """Track each FVG's fill status by checking candles after its formation for trading back through the zone."""
    result = []
    for fvg in fvgs:
        entry = dict(fvg)
        zone = fvg.get("zone")
        index = fvg.get("index", 0)
        z_low, z_high = 0.0, 0.0
        zone_size = 0.0
        if zone and len(zone) == 2 and zone[1] > zone[0]:
            z_low, z_high = zone[0], zone[1]
            zone_size = z_high - z_low
        best_ratio = 0.0
        fill_index = None
        fully_filled = False
        if zone_size > 0:
            for i in range(index + 1, len(candles)):
                c = candles[i]
                overlap = min(c["high"], z_high) - max(c["low"], z_low)
                if overlap > 0:
                    ratio = min(overlap / zone_size, 1.0)
                    if fill_index is None:
                        fill_index = i
                    if overlap >= zone_size:
                        fully_filled = True
                        fill_index = i
                        best_ratio = 1.0
                        break
                    if ratio > best_ratio:
                        best_ratio = ratio
        entry["filled"] = fully_filled
        entry["fillIndex"] = fill_index
        entry["fillRatio"] = round(best_ratio, 2)
        result.append(entry)
    return result


def fvg_quality_score(fvg):
    """Deterministic 0-100 quality: smaller size relative to ATR and more recent formations score higher."""
    size = fvg.get("size", 0.0)
    fvg_price = fvg.get("price", 0.0) or 1.0
    atr = fvg.get("atr")
    if not atr or atr <= 0:
        atr = fvg_price * 0.005
    rel = size / atr if atr > 0 else 1.0
    size_component = max(0.0, min(100.0, 100.0 - 55.0 * rel))
    index = fvg.get("index", 0)
    total = fvg.get("totalCandles")
    if total and total > 0:
        recency = max(0.0, min(1.0, (total - index) / total))
    else:
        recency = 0.5
    quality = round(0.6 * size_component + 0.4 * recency * 100)
    return max(0, min(100, quality))


def confirm_setup(setup):
    """Deterministic entry confirmation from the computed SMC data."""
    candles = setup.get("candles") or []
    pd = setup.get("premiumDiscount") or {}
    obs = setup.get("orderBlocks") or []
    fvgs = setup.get("fvgs") or []
    sweeps = setup.get("sweeps") or []
    bos = setup.get("bos")
    choch = setup.get("choch")
    last = candles[-1] if candles else {}
    price = last.get("close", 0)

    signals = []

    position = pd.get("position")
    pd_aligned = position in ("premium", "discount")
    signals.append({"signal": "price_at_premium_discount", "aligned": pd_aligned, "detail": position or "none"})

    good_obs = [ob for ob in obs if ob.get("quality", 50) >= 50]
    good_fvgs = [f for f in fvgs if f.get("quality", 50) >= 50]
    levels_aligned = bool(good_obs or good_fvgs)
    signals.append({"signal": "orderblock_or_fvg", "aligned": levels_aligned, "detail": "ob=%d fvg=%d" % (len(good_obs), len(good_fvgs))})

    valid_sweeps = [s for s in sweeps if s.get("valid")]
    sweep_aligned = bool(valid_sweeps)
    signals.append({"signal": "liquidity_sweep", "aligned": sweep_aligned, "detail": "sweeps=%d" % len(valid_sweeps)})

    structure_aligned = bool(bos or choch)
    signals.append({"signal": "structure_alignment", "aligned": structure_aligned, "detail": "bos=%s choch=%s" % (bool(bos), bool(choch))})

    beyond = False
    if last and obs:
        for ob in obs:
            zone = ob.get("zone") or []
            if len(zone) == 2 and zone[1] > zone[0]:
                if ob.get("type") == "bullish" and price > zone[1]:
                    beyond = True
                if ob.get("type") == "bearish" and price < zone[0]:
                    beyond = True
    signals.append({"signal": "close_beyond_ob", "aligned": beyond, "detail": "price=%.8f" % price})

    aligned = [s for s in signals if s["aligned"]]
    opposed = [s for s in signals if not s["aligned"]]
    count = len(aligned)
    score = round(count / 5.0, 2)

    has_levels = bool(obs or fvgs or valid_sweeps or bos or choch)
    if not has_levels:
        confirmation = "no_valid_entry"
    elif not _has_retest(candles, obs, fvgs) and count < 4:
        confirmation = "wait_for_retest"
    elif count >= 4:
        confirmation = "confirmed"
    elif count == 3:
        confirmation = "partially_confirmed"
    elif len(opposed) >= 2:
        confirmation = "rejected"
    elif count == 2:
        confirmation = "wait_for_retest"
    else:
        confirmation = "rejected"

    return {"confirmation": Confirmation(confirmation), "signals": signals, "score": score}


def _has_retest(candles, obs, fvgs, lookback=5):
    """Return True when a recent candle traded back inside an OB or FVG zone."""
    if not candles:
        return False
    recent = candles[-lookback:]
    zones = [ob["zone"] for ob in obs if len(ob.get("zone", [])) == 2]
    zones += [f["zone"] for f in fvgs if len(f.get("zone", [])) == 2]
    for zone in zones:
        z_low, z_high = min(zone), max(zone)
        for c in recent:
            if c["low"] <= z_high and c["high"] >= z_low:
                return True
    return False


def _was_swept(candles, start_index, price, side):
    """Return True if the level extreme was exceeded after start_index and price closed back inside."""
    exceeded = False
    for i in range(start_index + 1, len(candles)):
        c = candles[i]
        if side == "high" and c["high"] > price:
            exceeded = True
        if side == "low" and c["low"] < price:
            exceeded = True
        if exceeded:
            if side == "high" and c["close"] < price:
                return True
            if side == "low" and c["close"] > price:
                return True
    return False


def _estimate_atr(candles, period=14):
    """Average true range estimate from the last `period` candles."""
    sample = candles[-period:]
    if not sample:
        return 0.0
    return sum(c["high"] - c["low"] for c in sample) / len(sample)

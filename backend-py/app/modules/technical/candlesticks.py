"""Candlestick pattern detection mirroring the Node technical/candlesticks.js."""
PATTERNS = {
    "doji": {"name": "Doji", "type": "neutral"},
    "gravestone_doji": {"name": "Gravestone Doji", "type": "bearish"},
    "dragonfly_doji": {"name": "Dragonfly Doji", "type": "bullish"},
    "long_legged_doji": {"name": "Long-Legged Doji", "type": "neutral"},
    "hammer": {"name": "Hammer", "type": "bullish"},
    "inverted_hammer": {"name": "Inverted Hammer", "type": "bullish"},
    "shooting_star": {"name": "Shooting Star", "type": "bearish"},
    "hanging_man": {"name": "Hanging Man", "type": "bearish"},
    "bullish_engulfing": {"name": "Bullish Engulfing", "type": "bullish"},
    "bearish_engulfing": {"name": "Bearish Engulfing", "type": "bearish"},
    "bullish_harami": {"name": "Bullish Harami", "type": "bullish"},
    "bearish_harami": {"name": "Bearish Harami", "type": "bearish"},
    "harami_cross": {"name": "Harami Cross", "type": "neutral"},
    "morning_star": {"name": "Morning Star", "type": "bullish"},
    "evening_star": {"name": "Evening Star", "type": "bearish"},
    "morning_doji_star": {"name": "Morning Doji Star", "type": "bullish"},
    "evening_doji_star": {"name": "Evening Doji Star", "type": "bearish"},
    "piercing_line": {"name": "Piercing Line", "type": "bullish"},
    "dark_cloud_cover": {"name": "Dark Cloud Cover", "type": "bearish"},
    "three_white_soldiers": {"name": "Three White Soldiers", "type": "bullish"},
    "three_black_crows": {"name": "Three Black Crows", "type": "bearish"},
    "three_inside_up": {"name": "Three Inside Up", "type": "bullish"},
    "three_inside_down": {"name": "Three Inside Down", "type": "bearish"},
    "three_outside_up": {"name": "Three Outside Up", "type": "bullish"},
    "three_outside_down": {"name": "Three Outside Down", "type": "bearish"},
    "bullish_belt_hold": {"name": "Bullish Belt Hold", "type": "bullish"},
    "bearish_belt_hold": {"name": "Bearish Belt Hold", "type": "bearish"},
    "bullish_marubozu": {"name": "Bullish Marubozu", "type": "bullish"},
    "bearish_marubozu": {"name": "Bearish Marubozu", "type": "bearish"},
    "spinning_top": {"name": "Spinning Top", "type": "neutral"},
    "high_wave": {"name": "High Wave", "type": "neutral"},
    "tweezer_top": {"name": "Tweezer Top", "type": "bearish"},
    "tweezer_bottom": {"name": "Tweezer Bottom", "type": "bullish"},
    "rising_three": {"name": "Rising Three", "type": "bullish"},
    "falling_three": {"name": "Falling Three", "type": "bearish"},
    "bullish_abandoned_baby": {"name": "Bullish Abandoned Baby", "type": "bullish"},
    "bearish_abandoned_baby": {"name": "Bearish Abandoned Baby", "type": "bearish"},
    "bullish_kicker": {"name": "Bullish Kicker", "type": "bullish"},
    "bearish_kicker": {"name": "Bearish Kicker", "type": "bearish"},
    "bullish_meeting_lines": {"name": "Bullish Meeting Lines", "type": "bullish"},
    "bearish_meeting_lines": {"name": "Bearish Meeting Lines", "type": "bearish"},
    "mat_hold": {"name": "Mat Hold", "type": "bullish"},
    "separating_lines_bull": {"name": "Bullish Separating Lines", "type": "bullish"},
    "separating_lines_bear": {"name": "Bearish Separating Lines", "type": "bearish"},
    "stick_sandwich": {"name": "Stick Sandwich", "type": "bullish"},
    "upsidedown_gap_two_crows": {"name": "Upside Gap Two Crows", "type": "bearish"},
    "two_crows": {"name": "Two Crows", "type": "bearish"},
    "three_stars_south": {"name": "Three Stars In The South", "type": "bullish"},
    "ladder_bottom": {"name": "Ladder Bottom", "type": "bullish"},
    "unique_three_river": {"name": "Unique Three River Bottom", "type": "bullish"},
    "concealing_baby_swallow": {"name": "Concealing Baby Swallow", "type": "bullish"},
    "thrusting": {"name": "Thrusting Pattern", "type": "bullish"},
    "in_neck": {"name": "In Neck", "type": "bearish"},
    "on_neck": {"name": "On Neck", "type": "bearish"},
    "homing_pigeon": {"name": "Homing Pigeon", "type": "bullish"},
    "descending_hawk": {"name": "Descending Hawk", "type": "bearish"},
    "advance_block": {"name": "Advance Block", "type": "bearish"},
    "deliberation": {"name": "Deliberation", "type": "bearish"},
    "breakaway": {"name": "Breakaway", "type": "neutral"},
    "matching_low": {"name": "Matching Low", "type": "bullish"},
    "matching_high": {"name": "Matching High", "type": "bearish"},
}


def _is_bullish(c):
    return c["close"] > c["open"]


def _is_bearish(c):
    return c["close"] < c["open"]


def _body(c):
    return abs(c["close"] - c["open"])


def _range(c):
    return c["high"] - c["low"]


def _upper_shadow(c):
    return c["high"] - max(c["open"], c["close"])


def _lower_shadow(c):
    return min(c["open"], c["close"]) - c["low"]


def _avg_body(candles, n):
    if n == 0:
        return 0
    return sum(_body(c) for c in candles[-n:]) / n


def _doji(c):
    return _body(c) <= _range(c) * 0.1


def detect_patterns(candles):
    out = []
    if len(candles) < 3:
        return out
    n = len(candles)
    c0 = candles[n - 1]
    c1 = candles[n - 2]
    c2 = candles[n - 3]
    c3 = candles[n - 4] if n >= 4 else None
    c4 = candles[n - 5] if n >= 5 else None
    bull = _is_bullish(c0)
    bear = _is_bearish(c0)
    body0 = _body(c0)
    range0 = _range(c0)

    if _doji(c0):
        if c0["open"] == c0["high"] and c0["close"] == c0["low"]:
            out.append("dragonfly_doji")
        elif c0["close"] == c0["high"] and c0["open"] == c0["low"]:
            out.append("gravestone_doji")
        elif _upper_shadow(c0) > range0 * 0.3 and _lower_shadow(c0) > range0 * 0.3:
            out.append("long_legged_doji")
        else:
            out.append("doji")
    if _lower_shadow(c0) > body0 * 2 and body0 < range0 * 0.35 and _upper_shadow(c0) < body0:
        out.append("hanging_man" if bear else "hammer")
    if _upper_shadow(c0) > body0 * 2 and body0 < range0 * 0.35 and _lower_shadow(c0) < body0:
        out.append("shooting_star" if bull else "inverted_hammer")
    if body0 > range0 * 0.8 and _upper_shadow(c0) < body0 * 0.1 and _lower_shadow(c0) < body0 * 0.1:
        out.append("bullish_marubozu" if bull else "bearish_marubozu")
    if c0["open"] == c0["low"] and c0["close"] == c0["high"] and body0 > range0 * 0.8:
        out.append("bullish_belt_hold")
    if c0["open"] == c0["high"] and c0["close"] == c0["low"] and body0 > range0 * 0.8:
        out.append("bearish_belt_hold")
    if body0 > range0 * 0.1 and body0 < range0 * 0.4 and _upper_shadow(c0) > body0 * 1.5 and _lower_shadow(c0) > body0 * 1.5:
        out.append("spinning_top")
    if body0 > range0 * 0.1 and body0 < range0 * 0.2 and _upper_shadow(c0) > body0 * 3 and _lower_shadow(c0) > body0 * 3:
        out.append("high_wave")

    if c1 and _is_bearish(c1) and bull:
        if c0["close"] > c1["open"] and c0["open"] < c1["close"] and c0["close"] > c1["close"]:
            out.append("bullish_engulfing")
    if c1 and _is_bullish(c1) and bear:
        if c0["close"] < c1["open"] and c0["open"] > c1["close"] and c0["close"] < c1["close"]:
            out.append("bearish_engulfing")
    if c1 and _is_bullish(c1) and bear and c0["close"] < c1["open"] and c0["open"] > c1["close"] and body0 < _body(c1) * 0.6:
        out.append("bearish_harami")
    if c1 and _is_bearish(c1) and bull and c0["close"] > c1["open"] and c0["open"] < c1["close"] and body0 < _body(c1) * 0.6:
        out.append("bullish_harami")
    if c1 and c0["close"] < c1["open"] and c0["open"] > c1["close"] and _doji(c0) and body0 < _body(c1) * 0.3:
        out.append("harami_cross")

    if c2 and c1 and _is_bearish(c2) and body0 > range0 * 0.5:
        if _is_bearish(c1) and _body(c1) > _range(c1) * 0.7 and c1["close"] < c2["close"] and c1["open"] < c2["close"] and bull and c0["close"] > (c1["open"] + c1["close"]) / 2:
            out.append("morning_star")
    if c2 and c1 and _is_bullish(c2) and bear:
        if _is_bullish(c1) and _body(c1) > _range(c1) * 0.7 and c1["close"] > c2["close"] and c1["open"] > c2["close"] and bear and c0["close"] < (c1["open"] + c1["close"]) / 2:
            out.append("evening_star")
    if c1 and _is_bearish(c1) and bull:
        if c0["open"] < c1["low"] and c0["close"] > (c1["open"] + c1["close"]) / 2 and c0["close"] < c1["open"]:
            out.append("piercing_line")
    if c1 and _is_bullish(c1) and bear:
        if c0["open"] > c1["high"] and c0["close"] < (c1["open"] + c1["close"]) / 2 and c0["close"] > c1["open"]:
            out.append("dark_cloud_cover")
    if c2 and c1 and _is_bullish(c2) and _is_bullish(c1) and bull and c0["close"] > c1["close"] and c1["close"] > c2["close"] and c0["open"] < c1["open"] and c1["open"] < c2["open"] and _body(c1) > _range(c1) * 0.6 and body0 > range0 * 0.6:
        out.append("three_white_soldiers")
    if c2 and c1 and _is_bearish(c2) and _is_bearish(c1) and bear and c0["close"] < c1["close"] and c1["close"] < c2["close"] and c0["open"] > c1["open"] and c1["open"] > c2["open"] and _body(c1) > _range(c1) * 0.6 and body0 > range0 * 0.6:
        out.append("three_black_crows")
    if c1 and _is_bullish(c1) and _is_bearish(c2) and _body(c1) > _range(c1) * 0.6 and c0["close"] > c1["high"]:
        out.append("three_inside_up")
    if c1 and _is_bearish(c1) and _is_bullish(c2) and _body(c1) > _range(c1) * 0.6 and c0["close"] < c1["low"]:
        out.append("three_inside_down")
    if c1 and _is_bearish(c1) and _is_bullish(c2) and c1["close"] < c2["close"] and c0["close"] > c1["open"] and c0["close"] > c2["high"]:
        out.append("three_outside_up")
    if c1 and _is_bullish(c1) and _is_bearish(c2) and c1["close"] > c2["close"] and c0["close"] < c1["open"] and c0["close"] < c2["low"]:
        out.append("three_outside_down")

    if c1 and c0["high"] == c1["high"] and bull != _is_bearish(c1) and body0 > range0 * 0.5:
        out.append("tweezer_top" if bear else "tweezer_bottom")

    if c1 and _is_bearish(c1) and c1["high"] < c0["high"] and c1["low"] > c0["low"] and c0["close"] > c1["high"]:
        out.append("bullish_kicker")
    if c1 and _is_bullish(c1) and c1["low"] > c0["low"] and c1["high"] < c0["high"] and c0["close"] < c1["low"]:
        out.append("bearish_kicker")

    if c1 and c0["open"] > c1["open"] and c0["close"] == c1["close"]:
        out.append("bullish_meeting_lines" if bull else "bearish_meeting_lines")

    if c1 and c2 and _is_bullish(c2) and _is_bearish(c1) and bull and c0["close"] > c2["high"]:
        out.append("rising_three")
    if c1 and c2 and _is_bearish(c2) and _is_bullish(c1) and bear and c0["close"] < c2["low"]:
        out.append("falling_three")

    if c2 and c1 and _is_bearish(c2) and _doji(c1) and bull:
        if c1["close"] < c2["close"] and c1["open"] < c2["close"] and c0["close"] > (c1["open"] + c1["close"]) / 2 and body0 > range0 * 0.5:
            out.append("morning_doji_star")
    if c2 and c1 and _is_bullish(c2) and _doji(c1) and bear:
        if c1["close"] > c2["close"] and c1["open"] > c2["close"] and c0["close"] < (c1["open"] + c1["close"]) / 2 and body0 > range0 * 0.5:
            out.append("evening_doji_star")
    if c2 and c1 and _is_bearish(c2) and _doji(c1) and bull and c1["high"] < c2["low"]:
        if c0["low"] > c1["high"] and c0["close"] > (c2["open"] + c2["close"]) / 2:
            out.append("bullish_abandoned_baby")
    if c2 and c1 and _is_bullish(c2) and _doji(c1) and bear and c1["low"] > c2["high"]:
        if c0["high"] < c1["low"] and c0["close"] < (c2["open"] + c2["close"]) / 2:
            out.append("bearish_abandoned_baby")

    if c1 and _is_bearish(c1) and _is_bullish(c0) and c0["open"] == c1["open"]:
        out.append("separating_lines_bull")
    if c1 and _is_bullish(c1) and _is_bearish(c0) and c0["open"] == c1["open"]:
        out.append("separating_lines_bear")

    if c2 and c1 and _is_bearish(c2) and _is_bullish(c1) and _is_bearish(c0) and c0["close"] == c2["close"]:
        out.append("stick_sandwich")

    if c2 and c1 and _is_bullish(c2) and _is_bearish(c1) and _is_bearish(c0):
        if c1["open"] > c2["high"] and c1["close"] > c2["high"]:
            if c1["open"] > c0["open"] > c1["close"] and c1["close"] > c0["close"] > c2["high"]:
                out.append("upsidedown_gap_two_crows")
    if c2 and c1 and _is_bullish(c2) and _is_bearish(c1) and _is_bearish(c0):
        if c1["open"] > c2["high"] and c2["close"] > c1["close"] > c2["open"]:
            if c1["open"] > c0["open"] > c1["close"] and c1["close"] > c0["close"] > c2["open"]:
                out.append("two_crows")

    if c2 and c1 and _is_bearish(c2) and _is_bearish(c1) and _is_bearish(c0):
        if c1["open"] < c2["open"] and c1["close"] < c2["close"] and c0["open"] < c1["open"] and c0["close"] < c1["close"]:
            if c1["low"] < c2["low"] and c0["low"] < c1["low"] and _body(c1) < _range(c1) * 0.5 and _body(c0) < _range(c0) * 0.5:
                out.append("three_stars_south")

    if c4 and c3 and _is_bearish(c4) and _is_bearish(c3) and _is_bearish(c2) and _is_bearish(c1):
        if c1["low"] < c2["low"] < c3["low"] < c4["low"] and _upper_shadow(c1) > _body(c1) * 2:
            if _is_bullish(c0) and c0["open"] > c1["close"] and c0["close"] > c1["high"]:
                out.append("ladder_bottom")

    if c2 and c1 and _is_bearish(c2) and _is_bearish(c1) and _is_bullish(c0):
        if c1["low"] < c2["low"] and c1["close"] > c2["close"] and _body(c2) > _range(c2) * 0.5:
            if c0["open"] > c1["close"] and c0["close"] < (c1["open"] + c1["close"]) / 2 and c0["close"] > c1["low"]:
                out.append("unique_three_river")

    if c3 and c2 and _is_bearish(c3) and _is_bearish(c2) and _is_bearish(c1):
        if c2["open"] < c3["open"] and c2["open"] > c3["close"] and c2["close"] < c3["close"]:
            if c1["open"] < c2["open"] and c1["open"] > c2["close"] and c1["close"] < c2["close"]:
                if _is_bullish(c0) and c0["close"] > c1["open"]:
                    out.append("concealing_baby_swallow")

    if c1 and _is_bearish(c1) and _is_bullish(c0):
        if c0["open"] < c1["low"] and c0["close"] > (c1["open"] + c1["close"]) / 2 and c0["close"] < c1["open"]:
            out.append("thrusting")
    if c1 and _is_bearish(c1) and _is_bullish(c0) and c0["close"] == c1["close"]:
        out.append("in_neck")
    if c1 and _is_bearish(c1) and _is_bullish(c0) and c0["close"] == c1["low"]:
        out.append("on_neck")

    if c1 and _is_bearish(c1) and _is_bearish(c0):
        if c0["open"] > c1["close"] and c0["open"] < c1["open"] and c0["close"] > c1["close"] and c0["close"] < c1["open"]:
            out.append("homing_pigeon")

    if c2 and c1 and _is_bullish(c2) and _is_bullish(c1) and _is_bullish(c0):
        if c2["open"] < c1["open"] < c2["close"] and c1["open"] < c1["close"] < c2["close"]:
            if c1["open"] < c0["open"] < c1["close"] and c1["open"] < c0["close"] < c1["close"]:
                out.append("descending_hawk")

    if c2 and c1 and _is_bullish(c2) and _is_bullish(c1) and _is_bullish(c0):
        if c2["open"] < c1["open"] < c2["close"] and c1["open"] < c1["close"] <= c2["close"]:
            if c1["open"] < c0["open"] < c1["close"] and c0["close"] <= c1["close"] and _upper_shadow(c0) > _body(c0):
                out.append("advance_block")

    if c2 and c1 and _is_bullish(c2) and _is_bullish(c1) and _is_bullish(c0):
        if _body(c2) > _range(c2) * 0.6 and _body(c1) > _range(c1) * 0.6:
            if c0["open"] > c1["close"] and _body(c0) < _range(c0) * 0.4 and c0["close"] < c1["high"]:
                out.append("deliberation")

    if c4 and c3 and _is_bearish(c4) and _is_bullish(c0):
        if _body(c4) > _range(c4) * 0.5:
            if c3["high"] < c4["low"] and c2["high"] < c4["low"] and c1["high"] < c4["low"]:
                if _body(c3) < _range(c3) * 0.6 and _body(c2) < _range(c2) * 0.6 and _body(c1) < _range(c1) * 0.6:
                    if c0["open"] > c3["high"] and c0["close"] > c4["open"]:
                        out.append("breakaway")
    if c4 and c3 and _is_bullish(c4) and _is_bearish(c0):
        if _body(c4) > _range(c4) * 0.5:
            if c3["low"] > c4["high"] and c2["low"] > c4["high"] and c1["low"] > c4["high"]:
                if _body(c3) < _range(c3) * 0.6 and _body(c2) < _range(c2) * 0.6 and _body(c1) < _range(c1) * 0.6:
                    if c0["open"] < c3["low"] and c0["close"] < c4["open"]:
                        out.append("breakaway")

    if c4 and c3 and _is_bullish(c4) and _body(c4) > _range(c4) * 0.5:
        if _is_bearish(c3) and _is_bearish(c2) and _is_bearish(c1) and _body(c3) < _range(c3) * 0.5 and _body(c2) < _range(c2) * 0.5 and _body(c1) < _range(c1) * 0.5:
            if c3["low"] >= c4["close"] and c2["low"] >= c4["close"] and c1["low"] >= c4["close"]:
                if _is_bullish(c0) and c0["close"] > max(c3["high"], c2["high"], c1["high"]):
                    out.append("mat_hold")

    if c1 and _is_bearish(c1) and _is_bearish(c0) and c0["low"] == c1["low"] and _body(c1) > _range(c1) * 0.4:
        out.append("matching_low")
    if c1 and _is_bullish(c1) and _is_bullish(c0) and c0["high"] == c1["high"] and _body(c1) > _range(c1) * 0.4:
        out.append("matching_high")

    unique = []
    for p in out:
        if p not in unique:
            unique.append(p)
    return [
        {"id": pid, **PATTERNS.get(pid, {"name": pid, "type": "neutral"}), "index": n - 1, "direction": PATTERNS.get(pid, {"type": "neutral"})["type"], "strength": _pattern_strength(pid, candles), "reliability": _pattern_reliability(pid)}
        for pid in unique
    ]


def _avg_vol(candles, n):
    return sum((c.get("volume") or 0) for c in candles[-n:]) / n


def _pattern_strength(pid, candles):
    entry = PATTERNS.get(pid)
    base = 0.7 if entry and entry["type"] in ("bullish", "bearish") else (0.4 if entry else 0.5)
    last = candles[-1] if candles else None
    vol_ratio = min(last["volume"] / (_avg_vol(candles, 20) or 1), 3) if last and last.get("volume") else 1
    return min(round((base * (0.6 + 0.4 * vol_ratio)) * 100) / 100, 0.98)


def _pattern_reliability(pid):
    reliabilities = {
        "three_white_soldiers": 0.9, "three_black_crows": 0.88, "bullish_engulfing": 0.82, "bearish_engulfing": 0.82,
        "morning_star": 0.85, "evening_star": 0.85, "hammer": 0.8, "shooting_star": 0.8, "hanging_man": 0.78,
        "dragonfly_doji": 0.75, "gravestone_doji": 0.75, "bullish_marubozu": 0.85, "bearish_marubozu": 0.85,
        "bullish_kicker": 0.8, "bearish_kicker": 0.8, "three_inside_up": 0.78, "three_inside_down": 0.78,
        "piercing_line": 0.76, "dark_cloud_cover": 0.76, "bullish_harami": 0.7, "bearish_harami": 0.7,
        "rising_three": 0.82, "falling_three": 0.82, "tweezer_bottom": 0.74, "tweezer_top": 0.74,
        "morning_doji_star": 0.83, "evening_doji_star": 0.83, "bullish_abandoned_baby": 0.87, "bearish_abandoned_baby": 0.87,
        "mat_hold": 0.8, "separating_lines_bull": 0.72, "separating_lines_bear": 0.72, "stick_sandwich": 0.7,
        "upsidedown_gap_two_crows": 0.74, "two_crows": 0.72, "three_stars_south": 0.7, "ladder_bottom": 0.76,
        "unique_three_river": 0.72, "concealing_baby_swallow": 0.74, "thrusting": 0.7, "in_neck": 0.66,
        "on_neck": 0.66, "homing_pigeon": 0.7, "descending_hawk": 0.68, "advance_block": 0.68,
        "deliberation": 0.66, "breakaway": 0.72, "matching_low": 0.7, "matching_high": 0.7,
    }
    return reliabilities.get(pid, 0.6)


def analyze_candlesticks(candles):
    patterns = detect_patterns(candles)
    bullish_count = sum(1 for p in patterns if p["type"] == "bullish")
    bearish_count = sum(1 for p in patterns if p["type"] == "bearish")
    bias = "bullish" if bullish_count > bearish_count else ("bearish" if bearish_count > bullish_count else "neutral")
    return {"patterns": patterns, "summary": {"count": len(patterns), "bullish": bullish_count, "bearish": bearish_count, "bias": bias}}

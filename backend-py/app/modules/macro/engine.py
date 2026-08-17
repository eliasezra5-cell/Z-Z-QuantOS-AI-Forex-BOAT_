"""Macro intelligence engine mirroring the Node macro/engine.js."""
import random
import time

from ...foundation.logger import logger
from ..marketdata.engine import get_quote, get_instrument


def init_macro():
    logger.info("Macro intelligence initialized")
    return get_macro_snapshot


def get_macro_snapshot():
    now = int(time.time() * 1000)
    snapshot = {
        "timestamp": now,
        "dollarIndex": _simulate_series(104.5, 0.3, 30),
        "bondYields": {
            "us10y": round(4.32 + (random.random() - 0.5) * 0.04, 2),
            "us2y": round(4.71 + (random.random() - 0.5) * 0.03, 2),
            "de10y": round(2.52 + (random.random() - 0.5) * 0.03, 2),
            "jp10y": round(0.92 + (random.random() - 0.5) * 0.02, 2),
            "uk10y": round(4.18 + (random.random() - 0.5) * 0.03, 2),
        },
        "correlations": {
            "dxy-gold": -0.82,
            "dxy-oil": -0.35,
            "gold-oil": 0.28,
            "btc-nasdaq": 0.65,
            "usd-crypto": -0.48,
            "equities-bonds": -0.55,
        },
        "riskOn": random.random() > 0.35,
        "indicators": {
            "vix": round(15.5 + (random.random() - 0.5) * 3, 2),
            "globalM2Growth": round(6.2 + (random.random() - 0.5) * 0.5, 2),
            "recessionProbability": round(random.random() * 20 + 10, 2),
            "marketBreadth": round(random.random() * 30 + 55, 2),
        },
        "global": {
            "fedFunds": 5.5,
            "ecbRate": 4.0,
            "bojRate": 0.0,
            "boeRate": 5.25,
            "growthForecast2026": 3.1,
            "inflationForecast": 2.9,
        },
    }
    snapshot["regime"] = detect_regime(snapshot)
    snapshot["yieldCurve"] = yield_curve_shape(snapshot)
    snapshot["crossAsset"] = cross_asset_analysis(snapshot)
    return snapshot


def detect_regime(snapshot=None):
    """Deterministically classify the market regime from macro indicators.

    The regime decision is rule-based only (no randomness). Thresholds:
    recessionProbability > 40 is a crisis factor, marketBreadth < 50 is bearish
    and > 65 bullish, vix > 28 signals crisis/risk-off and < 15 risk-on, and the
    riskOn flag nudges the aggregate score. Returns the regime label, a score in
    [-1, 1] and the contributing factors.
    """
    if snapshot is None:
        snapshot = get_macro_snapshot()
    indicators = snapshot.get("indicators") or {}
    recession = indicators.get("recessionProbability") or 0
    breadth = indicators.get("marketBreadth") or 50
    vix = indicators.get("vix") or 15
    risk_on = bool(snapshot.get("riskOn"))

    factors = {}
    if recession > 40:
        factors["recession"] = "crisis"
    elif recession > 25:
        factors["recession"] = "transitional"
    else:
        factors["recession"] = "benign"
    if breadth < 50:
        factors["breadth"] = "bearish"
    elif breadth > 65:
        factors["breadth"] = "bullish"
    else:
        factors["breadth"] = "neutral"
    if vix > 28:
        factors["vix"] = "crisis"
    elif vix > 20:
        factors["vix"] = "risk_off"
    elif vix < 15:
        factors["vix"] = "risk_on"
    else:
        factors["vix"] = "neutral"
    factors["riskOn"] = "risk_on" if risk_on else "risk_off"

    score = 0.0
    score += -1.0 if factors["recession"] == "crisis" else (-0.5 if factors["recession"] == "transitional" else 0.5)
    score += -1.0 if factors["breadth"] == "bearish" else (1.0 if factors["breadth"] == "bullish" else 0.0)
    score += -1.0 if factors["vix"] == "crisis" else (-0.5 if factors["vix"] == "risk_off" else (0.5 if factors["vix"] == "risk_on" else 0.0))
    score += 0.5 if risk_on else -0.5
    score = round(max(-1.0, min(1.0, score / 4.0)), 4)

    if factors["recession"] == "crisis" or factors["vix"] == "crisis":
        regime = "crisis"
    elif score > 0.25:
        regime = "risk_on"
    elif score < -0.25:
        regime = "risk_off"
    else:
        regime = "transitional"
    return {"regime": regime, "score": score, "factors": factors}


def yield_curve_shape(snapshot=None):
    """Classify the US yield curve from bond yields in the macro snapshot.

    spread = us10y - us2y. Inverted (spread < 0) implies a risk-off bias, normal
    (spread > 0.2) implies a risk-on bias and flat sits in between. The gold
    signal reflects safe-haven flows: risk-off supports gold, risk-on weighs it.
    """
    if snapshot is None:
        snapshot = get_macro_snapshot()
    yields = snapshot.get("bondYields") or {}
    us10y = yields.get("us10y") or 4.32
    us2y = yields.get("us2y") or 4.71
    spread = round(us10y - us2y, 2)
    if spread < 0:
        shape = "inverted"
        signal = "bullish-for-gold"
        detail = "US yield curve inverted (10y below 2y) — recessionary, risk-off bias supporting gold as a safe haven."
    elif spread > 0.2:
        shape = "normal"
        signal = "bearish-for-gold"
        detail = "US yield curve positively sloped — growth-friendly, risk-on bias weighing on gold's safe-haven appeal."
    else:
        shape = "flat"
        signal = "neutral"
        detail = "US yield curve flat — limited directional signal, watch for regime shifts."
    return {"shape": shape, "spread": spread, "signal": signal, "detail": detail}


def _simulate_series(base, vol, count):
    out = []
    v = base
    for _ in range(count):
        v += (random.random() - 0.5) * vol
        out.append(round(v, 2))
    return out


def cross_asset_analysis(snapshot=None):
    """Composite dollar/oil/bond read with a deterministic macro bias signal.

    Dollar trend is derived from the dollar-index series (rising = risk-off,
    falling = risk-on). Oil is inferred inversely to the dollar via the DXY-oil
    correlation. Bonds are read from the yield-curve shape. The three legs are
    summed into a single macroBias that supports (or fights) the current regime.
    """
    if snapshot is None:
        snapshot = get_macro_snapshot()
    dollar = snapshot.get("dollarIndex") or []
    if len(dollar) >= 2:
        drift = dollar[-1] - dollar[0]
        dollar_trend = "rising" if drift > 0.1 else ("falling" if drift < -0.1 else "flat")
    else:
        dollar_trend = "flat"

    curve = yield_curve_shape(snapshot)
    if curve["shape"] == "inverted":
        bond_leg = -1.0
        bond_read = "bonds price in a recession — risk-off"
    elif curve["shape"] == "normal":
        bond_leg = 1.0
        bond_read = "bonds price in growth — risk-on"
    else:
        bond_leg = 0.0
        bond_read = "yield curve flat — neutral"

    if dollar_trend == "rising":
        dollar_leg = -1.0
        oil_leg = 1.0
        dollar_read = "dollar bid — dampens gold & equities, pressures EM"
        oil_read = "oil firming on dollar strength/inflation"
    elif dollar_trend == "falling":
        dollar_leg = 1.0
        oil_leg = -1.0
        dollar_read = "dollar soft — risk-on tailwind for gold & equities"
        oil_read = "oil easing as the dollar retreats"
    else:
        dollar_leg = oil_leg = 0.0
        dollar_read = "dollar rangebound"
        oil_read = "oil without a directional dollar impulse"

    bias_score = round((dollar_leg + oil_leg + bond_leg) / 3.0, 4)
    if bias_score > 0.25:
        macro_bias = "risk_on"
    elif bias_score < -0.25:
        macro_bias = "risk_off"
    else:
        macro_bias = "neutral"

    regime = snapshot.get("regime") or detect_regime(snapshot)
    aligns = (
        (regime["regime"] == "risk_on" and macro_bias == "risk_on")
        or (regime["regime"] == "risk_off" and macro_bias == "risk_off")
        or (regime["regime"] in ("crisis", "transitional"))
    )

    return {
        "dollar": {"trend": dollar_trend, "read": dollar_read, "leg": dollar_leg},
        "oil": {"bias": "bullish" if oil_leg > 0 else ("bearish" if oil_leg < 0 else "neutral"), "read": oil_read, "leg": oil_leg},
        "bonds": {"read": bond_read, "leg": bond_leg, "curveShape": curve["shape"]},
        "macroBias": macro_bias,
        "biasScore": bias_score,
        "alignsWithRegime": aligns,
    }


def _hash_string(s):
    h = 0
    for ch in s:
        h = ((31 * h) + ord(ch)) & 0xFFFFFFFF
        if h & 0x80000000:
            h -= 0x100000000
    return (abs(h) % 10000) / 10000


def get_correlation_matrix(symbols=None):
    targets = symbols or ["XAUUSD", "WTI", "BTCUSD", "US500", "EURUSD"]
    matrix = {}
    for a in targets:
        matrix[a] = {}
        for b in targets:
            if a == b:
                matrix[a][b] = 1
                continue
            seed = _hash_string(f"{a}-{b}")
            matrix[a][b] = round(seed * 2 - 1, 2)
    return matrix


def correlate_with_quote(symbol):
    inst = get_instrument(symbol)
    quote = get_quote(symbol)
    macro = get_macro_snapshot()
    correlation_map = {
        "XAUUSD": macro["correlations"]["dxy-gold"],
        "WTI": macro["correlations"]["dxy-oil"],
        "BTCUSD": macro["correlations"]["btc-nasdaq"],
    }
    corr = correlation_map.get(symbol, 0.2)
    asset = "DXY" if symbol == "XAUUSD" else ("DXY" if symbol == "WTI" else ("Nasdaq" if symbol == "BTCUSD" else "DXY"))
    return {
        "symbol": symbol,
        "price": quote["price"],
        "dominantCorrelation": corr,
        "correlationAsset": asset,
        "riskOn": macro["riskOn"],
        "inference": "positive-correlation" if (correlation_map.get(symbol, 0) > 0.3) else "negative-correlation",
    }

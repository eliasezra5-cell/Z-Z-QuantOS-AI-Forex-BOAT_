"""Pro / advanced technical indicators (additive).

New file — does not touch the existing ``technical/indicators.py``. These are
pure-math ports of institutional-style indicators (Ichimoku, Fibonacci, TD
Sequential, Donchian, Clenow momentum, volatility cones, relative rotation).
Every function degrades gracefully: short/empty/invalid input returns None /
empty structures instead of raising.
"""
import numpy as np

DEFAULT_BENCHMARK = "US500"


def _to_arrays(df, fields=("high", "low", "close", "open", "volume")):
    """Accept a list of candle dicts or a DataFrame; return named arrays."""
    if hasattr(df, "to_dict"):
        records = df.to_dict("records")
    else:
        records = df or []
    out = {}
    for field in fields:
        try:
            out[field] = np.array([float(r.get(field)) for r in records if r.get(field) is not None], dtype=float)
        except (TypeError, ValueError):
            out[field] = np.array([], dtype=float)
    return out


def _py(value):
    """Numpy scalar -> python scalar (JSON safe, NaN/Inf -> None)."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(v) or np.isinf(v):
        return None
    return v


def _sma(arr, period):
    if arr.size == 0 or period <= 0:
        return np.full(max(arr.size, 0), np.nan)
    out = np.full(arr.size, np.nan)
    if arr.size >= period:
        csum = np.cumsum(np.insert(arr, 0, 0.0))
        out[period - 1:] = (csum[period:] - csum[:-period]) / period
    return out


def _rolling_max(arr, period):
    out = np.full(arr.size, np.nan)
    for i in range(len(arr)):
        if i + 1 >= period:
            out[i] = np.nanmax(arr[i + 1 - period:i + 1])
    return out


def _rolling_min(arr, period):
    out = np.full(arr.size, np.nan)
    for i in range(len(arr)):
        if i + 1 >= period:
            out[i] = np.nanmin(arr[i + 1 - period:i + 1])
    return out


def _last_valid(arr, default=None):
    for v in reversed(arr):
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            return _py(v)
    return default


# --------------------------------------------------------------------------- #
# Ichimoku Kinko Hyo
# --------------------------------------------------------------------------- #
def ichimoku(df, tenkan=9, kijun=26, senkou_b=52):
    """Ichimoku cloud. Returns series + latest values + cloud bias."""
    d = _to_arrays(df)
    high, low, close = d["high"], d["low"], d["close"]
    if close.size < max(kijun, senkou_b):
        return {"available": False, "reason": "insufficient-data"}

    tenkan_sen = (_rolling_max(high, tenkan) + _rolling_min(low, tenkan)) / 2.0
    kijun_sen = (_rolling_max(high, kijun) + _rolling_min(low, kijun)) / 2.0
    senkou_a = (tenkan_sen + kijun_sen) / 2.0
    senkou_b = (_rolling_max(high, senkou_b) + _rolling_min(low, senkou_b)) / 2.0
    chikou = np.full(close.size, np.nan)
    chikou[:close.size - kijun] = close[kijun:]

    shifted_a = np.full(close.size, np.nan)
    shifted_b = np.full(close.size, np.nan)
    shifted_a[kijun:] = senkou_a[:-kijun] if kijun else senkou_a
    shifted_b[kijun:] = senkou_b[:-kijun] if kijun else senkou_b

    a = _last_valid(shifted_a)
    b = _last_valid(shifted_b)
    price = _last_valid(close)
    bias = "bullish" if (a is not None and b is not None and price is not None and price > max(a, b)) else (
        "bearish" if (a is not None and b is not None and price is not None and price < min(a, b)) else "neutral"
    )

    return {
        "available": True,
        "tenkan": _last_valid(tenkan_sen),
        "kijun": _last_valid(kijun_sen),
        "senkouA": a,
        "senkouB": b,
        "chikou": _last_valid(chikou),
        "cloudBias": bias,
        "series": {
            "tenkan": [_py(v) for v in tenkan_sen],
            "kijun": [_py(v) for v in kijun_sen],
            "senkouA": [_py(v) for v in shifted_a],
            "senkouB": [_py(v) for v in shifted_b],
            "chikou": [_py(v) for v in chikou],
        },
    }


# --------------------------------------------------------------------------- #
# Fibonacci Retracement
# --------------------------------------------------------------------------- #
def fibonacci_retracement(df, lookback=200):
    """Swing-based Fibonacci retracement over the lookback window."""
    d = _to_arrays(df)
    high, low, close = d["high"], d["low"], d["close"]
    if close.size == 0:
        return {"available": False, "reason": "insufficient-data"}

    window = min(lookback, close.size)
    swing_high = float(np.max(high[-window:])) if high.size else None
    swing_low = float(np.min(low[-window:])) if low.size else None
    if swing_high is None or swing_low is None or swing_high <= swing_low:
        return {"available": False, "reason": "flat-range"}

    price = _last_valid(close)
    uptrend = (price or 0) >= (swing_low + (swing_high - swing_low) / 2.0)
    levels = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    ref_top = swing_high if uptrend else swing_low
    ref_bottom = swing_low if uptrend else swing_high
    retracements = []
    for ratio in levels:
        if uptrend:
            level_price = ref_top - (ref_top - ref_bottom) * ratio
        else:
            level_price = ref_bottom + (ref_bottom - ref_top) * ratio
        retracements.append({
            "level": ratio,
            "price": _py(level_price),
            "distancePct": round((level_price / ref_top - 1.0) * 100, 4) if ref_top else None,
        })

    return {
        "available": True,
        "swingHigh": _py(swing_high),
        "swingLow": _py(swing_low),
        "bias": "uptrend" if uptrend else "downtrend",
        "price": _py(price),
        "levels": retracements,
    }


# --------------------------------------------------------------------------- #
# Tom DeMark Sequential
# --------------------------------------------------------------------------- #
def demark_sequential(df, lookback=500):
    """TD Sequential Setup + Countdown (9 / 13 counts)."""
    d = _to_arrays(df)
    close = d["close"]
    if close.size < 5:
        return {"available": False, "reason": "insufficient-data"}

    lookback = min(lookback, close.size)
    series = close[-lookback:]
    buy_setup = 0
    sell_setup = 0
    setup_history = []
    countdown = 0
    setup_reached_9 = False

    for i in range(4, series.size):
        c = series[i]
        prev4 = series[i - 4]
        if c > prev4:
            buy_setup = buy_setup + 1 if buy_setup >= 0 else 1
            sell_setup = 0
            if buy_setup == 9:
                setup_reached_9 = True
        elif c < prev4:
            sell_setup = sell_setup + 1 if sell_setup >= 0 else 1
            buy_setup = 0
            if sell_setup == 9:
                setup_reached_9 = True
        else:
            buy_setup = 0
            sell_setup = 0
        setup_history.append({"buy": buy_setup, "sell": sell_setup})

    current_buy = setup_history[-1]["buy"] if setup_history else 0
    current_sell = setup_history[-1]["sell"] if setup_history else 0

    if setup_reached_9:
        signal = "buy-13-countdown" if current_buy >= 9 else "sell-13-countdown"
    else:
        signal = "buy-setup-9" if current_buy >= 9 else ("sell-setup-9" if current_sell >= 9 else "none")

    return {
        "available": True,
        "buySetup": int(current_buy),
        "sellSetup": int(current_sell),
        "setupReached9": bool(setup_reached_9),
        "signal": signal,
        "lookback": int(lookback),
    }


# --------------------------------------------------------------------------- #
# Donchian Channel
# --------------------------------------------------------------------------- #
def donchian_channel(df, period=20):
    """Donchian channel (rolling high/low)."""
    d = _to_arrays(df)
    high, low = d["high"], d["low"]
    if high.size < period:
        return {"available": False, "reason": "insufficient-data"}

    upper = _rolling_max(high, period)
    lower = _rolling_min(low, period)
    middle = (upper + lower) / 2.0
    price = _last_valid(d["close"])
    u = _last_valid(upper)
    l = _last_valid(lower)

    position = None
    if price is not None and u is not None and l is not None and u > l:
        position = round((price - l) / (u - l), 4)

    return {
        "available": True,
        "period": int(period),
        "upper": u,
        "middle": _last_valid(middle),
        "lower": l,
        "price": price,
        "position": position,
        "series": {
            "upper": [_py(v) for v in upper],
            "lower": [_py(v) for v in lower],
        },
    }


# --------------------------------------------------------------------------- #
# Clenow Momentum
# --------------------------------------------------------------------------- #
def clenow_momentum(df, period=90, ann=252):
    """Clenow momentum: slope * R^2 * annualized volatility of ln prices."""
    d = _to_arrays(df)
    close = d["close"]
    if close.size < period or period < 5:
        return {"available": False, "reason": "insufficient-data"}

    series = close[-period:]
    log_price = np.log(series)
    x = np.arange(period, dtype=float)
    n = period
    x_mean = x.mean()
    y_mean = log_price.mean()
    cov_xy = np.sum((x - x_mean) * (log_price - y_mean))
    var_x = np.sum((x - x_mean) ** 2)
    slope = cov_xy / var_x if var_x > 0 else 0.0
    intercept = y_mean - slope * x_mean
    pred = intercept + slope * x
    ss_res = np.sum((log_price - pred) ** 2)
    ss_tot = np.sum((log_price - y_mean) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    rets = np.diff(series) / series[:-1]
    vol_ann = float(np.std(rets) * np.sqrt(ann)) if rets.size > 1 else 0.0
    momentum = float(slope * r2 * vol_ann)

    return {
        "available": True,
        "period": int(period),
        "momentum": round(momentum, 6),
        "annualizedVolatility": round(vol_ann, 6),
        "rSquared": round(r2, 4),
        "slope": round(slope, 8),
        "trend": "positive" if momentum > 0 else ("negative" if momentum < 0 else "flat"),
        "price": _last_valid(close),
    }


# --------------------------------------------------------------------------- #
# Volatility Cones
# --------------------------------------------------------------------------- #
def volatility_cones(df, periods=None, window=252):
    """Realized-volatility cone percentiles across multiple holding periods."""
    d = _to_arrays(df)
    close = d["close"]
    if close.size < 10:
        return {"available": False, "reason": "insufficient-data"}

    periods = periods or [10, 20, 30, 60, 90]
    rets = np.diff(close) / close[:-1]
    cones = []
    for period in periods:
        if period < 2 or rets.size < period:
            cones.append({"period": int(period), "available": False})
            continue
        vols = []
        for i in range(period - 1, rets.size):
            seg = rets[i - period + 1:i + 1]
            if seg.size >= period:
                vols.append(np.std(seg) * np.sqrt(period))
        vols = np.array(vols)
        lookback = min(window, vols.size)
        recent = vols[-lookback:]
        current = float(vols[-1]) if vols.size else None
        percentiles = {
            "min": _py(np.min(recent)),
            "p25": _py(np.percentile(recent, 25)),
            "median": _py(np.median(recent)),
            "p75": _py(np.percentile(recent, 75)),
            "max": _py(np.max(recent)),
            "current": _py(current),
        }
        percentile_rank = float(np.mean(recent <= current)) if current is not None and recent.size else None
        cones.append({
            "period": int(period),
            "available": True,
            "percentiles": percentiles,
            "percentileRank": round(percentile_rank, 4) if percentile_rank is not None else None,
            "regime": "high-vol" if percentile_rank is not None and percentile_rank >= 0.75 else (
                "low-vol" if percentile_rank is not None and percentile_rank <= 0.25 else "normal"
            ),
        })
    return {"available": True, "window": int(window), "cones": cones}


# --------------------------------------------------------------------------- #
# Relative Rotation Graph (RRS)
# --------------------------------------------------------------------------- #
def relative_rotation(df, benchmark_df, window=30):
    """Relative strength ratio + momentum vs a benchmark (RRG-style)."""
    d = _to_arrays(df)
    b = _to_arrays(benchmark_df)
    close, bench = d["close"], b["close"]
    if close.size == 0 or bench.size == 0:
        return {"available": False, "reason": "insufficient-data"}

    n = min(close.size, bench.size)
    close, bench = close[-n:], bench[-n:]
    if n < max(window, 5):
        return {"available": False, "reason": "insufficient-data"}

    with np.errstate(divide="ignore", invalid="ignore"):
        rs_ratio = close / bench
    rs_ratio = np.nan_to_num(rs_ratio, nan=1.0, posinf=1.0, neginf=0.0)

    zscores = np.full(rs_ratio.size, np.nan)
    for i in range(window - 1, rs_ratio.size):
        seg = rs_ratio[i - window + 1:i + 1]
        mean = seg.mean()
        std = seg.std()
        zscores[i] = (rs_ratio[i] - mean) / std if std > 0 else 0.0

    momentum = np.full(rs_ratio.size, np.nan)
    for i in range(window - 1, rs_ratio.size):
        momentum[i] = rs_ratio[i] / rs_ratio[i - window + 1] - 1.0

    rs_z = _last_valid(zscores)
    rs_mom = _last_valid(momentum)

    if rs_z is not None and rs_mom is not None:
        if rs_z >= 0 and rs_mom >= 0:
            quadrant = "leading"
        elif rs_z >= 0 and rs_mom < 0:
            quadrant = "weakening"
        elif rs_z < 0 and rs_mom < 0:
            quadrant = "lagging"
        else:
            quadrant = "improving"
    else:
        quadrant = "unknown"

    return {
        "available": True,
        "window": int(window),
        "rsRatio": _last_valid(rs_ratio),
        "rsZScore": round(rs_z, 4) if rs_z is not None else None,
        "rsMomentum": round(rs_mom, 6) if rs_mom is not None else None,
        "quadrant": quadrant,
        "series": {
            "rsRatio": [_py(v) for v in rs_ratio],
            "zScore": [_py(v) for v in zscores],
            "momentum": [_py(v) for v in momentum],
        },
    }

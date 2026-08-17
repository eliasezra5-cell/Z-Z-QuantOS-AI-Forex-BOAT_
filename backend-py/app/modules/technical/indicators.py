"""Technical indicators mirroring the Node technical/indicators.js.

JS `null` maps to Python `None`. Note that JS `== null` matches both null and
undefined (and is not true for NaN), which we replicate via `_is_null`.
"""
import math

from ..marketdata.engine import generate_candles


def _is_null(v):
    return v is None


def sma(values, period):
    out = []
    n = len(values)
    for i in range(n):
        if i < period - 1:
            out.append(None)
            continue
        total = 0.0
        broken = False
        for j in range(i - period + 1, i + 1):
            if _is_null(values[j]):
                total = math.nan
                break
            total += values[j]
        out.append(None if math.isnan(total) else total / period)
    return out


def ema(values, period):
    out = []
    k = 2 / (period + 1)
    prev = None
    for i in range(len(values)):
        if i < period - 1:
            out.append(None)
            continue
        if prev is None:
            total = 0.0
            for j in range(i - period + 1, i + 1):
                total += values[j]
            prev = total / period
        else:
            prev = values[i] * k + prev * (1 - k)
        out.append(prev)
    return out


def rsi(values, period=14):
    out = []
    avg_gain = 0
    avg_loss = 0
    for i in range(len(values)):
        if i < period:
            out.append(None)
            continue
        change = values[i] - values[i - 1]
        gain = change if change > 0 else 0
        loss = -change if change < 0 else 0
        if i == period:
            g = 0
            l = 0
            for j in range(i - period + 1, i + 1):
                c = values[j] - values[j - 1]
                if c > 0:
                    g += c
                else:
                    l -= c
            avg_gain = g / period
            avg_loss = l / period
        else:
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            out.append(50 if avg_gain == 0 else 100)
        else:
            out.append(100 - 100 / (1 + avg_gain / avg_loss))
    return out


def macd(values, fast=12, slow=26, signal=9):
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    line = [
        (ema_fast[i] - ema_slow[i]) if (not _is_null(ema_fast[i]) and not _is_null(ema_slow[i])) else None
        for i in range(len(values))
    ]
    signal_arr = ema([0 if _is_null(v) else v for v in line], signal)
    histogram = []
    for i in range(len(line)):
        if _is_null(line[i]) or _is_null(signal_arr[i]):
            histogram.append(None)
        else:
            histogram.append(line[i] - signal_arr[i])
    return {"line": line, "signal": signal_arr, "histogram": histogram, "macd": line, "signalLine": signal_arr}


def bollinger(values, period=20, mult=2):
    mid = sma(values, period)
    upper = []
    lower = []
    for i in range(len(values)):
        if _is_null(mid[i]):
            upper.append(None)
            lower.append(None)
            continue
        variance = 0.0
        for j in range(i - period + 1, i + 1):
            variance += (values[j] - mid[i]) ** 2
        sd = math.sqrt(variance / period)
        upper.append(mid[i] + mult * sd)
        lower.append(mid[i] - mult * sd)
    return {"upper": upper, "middle": mid, "lower": lower}


def atr(candles, period=14):
    trs = []
    for i in range(len(candles)):
        if i == 0:
            trs.append(candles[i]["high"] - candles[i]["low"])
            continue
        c = candles[i]
        prev = candles[i - 1]
        trs.append(max(c["high"] - c["low"], abs(c["high"] - prev["close"]), abs(c["low"] - prev["close"])))
    return ema(trs, period)


def adx(candles, period=14):
    n = len(candles)
    plus_dm = [0]
    minus_dm = [0]
    tr = [candles[0]["high"] - candles[0]["low"] if candles else 0]
    for i in range(1, n):
        up = candles[i]["high"] - candles[i - 1]["high"]
        down = candles[i - 1]["low"] - candles[i]["low"]
        plus_dm.append(up if (up > down and up > 0) else 0)
        minus_dm.append(down if (down > up and down > 0) else 0)
        tr.append(max(candles[i]["high"] - candles[i]["low"], abs(candles[i]["high"] - candles[i - 1]["close"]), abs(candles[i]["low"] - candles[i - 1]["close"])))
    atr_val = ema(tr, period)
    plus_di = []
    minus_di = []
    dx = []
    sma_pdm = sma(plus_dm, period)
    sma_mdm = sma(minus_dm, period)
    for i in range(len(tr)):
        if _is_null(atr_val[i]) or atr_val[i] == 0:
            plus_di.append(None)
            minus_di.append(None)
            dx.append(None)
            continue
        pdi = (sma_pdm[i] if sma_pdm[i] is not None else 0) / atr_val[i] * 100
        mdi = (sma_mdm[i] if sma_mdm[i] is not None else 0) / atr_val[i] * 100
        plus_di.append(pdi)
        minus_di.append(mdi)
        dx.append(abs(pdi - mdi) / (pdi + mdi or 1) * 100)
    adx_val = ema([0 if _is_null(v) else v for v in dx], period)
    result = [None if _is_null(v) else adx_val[i] for i, v in enumerate(dx)]
    return {"adx": result, "plusDI": plus_di, "minusDI": minus_di}


def stochastic(candles, period=14, smooth_k=3, smooth_d=3):
    raw_k = []
    for i in range(len(candles)):
        if i < period - 1:
            raw_k.append(None)
            continue
        high = -math.inf
        low = math.inf
        for j in range(i - period + 1, i + 1):
            high = max(high, candles[j]["high"])
            low = min(low, candles[j]["low"])
        raw_k.append((candles[i]["close"] - low) / (high - low or 1) * 100)
    k = sma(raw_k, smooth_k)
    d = sma(k, smooth_d)
    return {"k": k, "d": d}


def obv(candles):
    out = [0]
    for i in range(1, len(candles)):
        if candles[i]["close"] > candles[i - 1]["close"]:
            out.append(out[i - 1] + candles[i]["volume"])
        elif candles[i]["close"] < candles[i - 1]["close"]:
            out.append(out[i - 1] - candles[i]["volume"])
        else:
            out.append(out[i - 1])
    return out


def cmf(candles, period=20):
    out = []
    for i in range(len(candles)):
        if i < period - 1:
            out.append(None)
            continue
        mfv = 0.0
        vol = 0.0
        for j in range(i - period + 1, i + 1):
            c = candles[j]
            mfm = 0 if (c["high"] - c["low"]) == 0 else ((c["close"] - c["low"]) - (c["high"] - c["close"])) / (c["high"] - c["low"])
            mfv += mfm * c["volume"]
            vol += c["volume"]
        out.append(0 if vol == 0 else mfv / vol)
    return out


def cci(candles, period=20):
    out = []
    for i in range(len(candles)):
        if i < period - 1:
            out.append(None)
            continue
        tp = candles[i]["high"] + candles[i]["low"] + candles[i]["close"]
        total = 0.0
        for j in range(i - period + 1, i + 1):
            total += candles[j]["high"] + candles[j]["low"] + candles[j]["close"]
        mean = total / period
        dev = 0.0
        for j in range(i - period + 1, i + 1):
            dev += abs((candles[j]["high"] + candles[j]["low"] + candles[j]["close"]) - mean)
        md = dev / period
        out.append(0 if md == 0 else (tp - mean) / (0.015 * md))
    return out


def mfi(candles, period=14):
    out = []
    for i in range(len(candles)):
        if i < period:
            out.append(None)
            continue
        pos = 0.0
        neg = 0.0
        for j in range(i - period + 1, i + 1):
            tf = candles[j]["high"] + candles[j]["low"] + candles[j]["close"]
            ptf = candles[j - 1]["high"] + candles[j - 1]["low"] + candles[j - 1]["close"]
            rmf = tf * candles[j]["volume"]
            if tf > ptf:
                pos += rmf
            elif tf < ptf:
                neg += rmf
        out.append(100 if neg == 0 else 100 - 100 / (1 + pos / neg))
    return out


def roc(values, period=12):
    out = []
    for i in range(len(values)):
        if i < period:
            out.append(None)
            continue
        out.append((values[i] - values[i - period]) / values[i - period] * 100)
    return out


def vwap(candles):
    out = []
    cum_pv = 0.0
    cum_vol = 0.0
    for i in range(len(candles)):
        tp = (candles[i]["high"] + candles[i]["low"] + candles[i]["close"]) / 3
        cum_pv += tp * candles[i]["volume"]
        cum_vol += candles[i]["volume"]
        out.append(tp if cum_vol == 0 else cum_pv / cum_vol)
    return out


def super_trend(candles, period=10, mult=3):
    atr_val = atr(candles, period)
    out = []
    prev_close = None
    final_upper = None
    final_lower = None
    trend = 1
    for i in range(len(candles)):
        if i < period or _is_null(atr_val[i]):
            out.append(None)
            continue
        c = candles[i]
        hl2 = (c["high"] + c["low"]) / 2
        upper = hl2 + mult * atr_val[i]
        lower = hl2 - mult * atr_val[i]
        if final_upper is not None:
            if upper < final_upper or c["close"] > final_upper:
                upper = final_upper
            if lower > final_lower or c["close"] < final_lower:
                lower = final_lower
        final_upper = upper
        final_lower = lower
        if prev_close is not None and prev_close <= final_upper:
            trend = 1
        elif prev_close is not None and prev_close >= final_lower:
            trend = -1
        out.append({"value": final_lower if trend == 1 else final_upper, "trend": trend})
        prev_close = c["close"]
    return out


def williams_r(candles, period=14):
    """Williams %R oscillator, scaled to -100..0 (values above -20 = overbought, below -80 = oversold)."""
    out = []
    for i in range(len(candles)):
        if i < period - 1:
            out.append(None)
            continue
        high = max(candles[j]["high"] for j in range(i - period + 1, i + 1))
        low = min(candles[j]["low"] for j in range(i - period + 1, i + 1))
        rng = high - low
        out.append(-100.0 * (high - candles[i]["close"]) / rng if rng > 0 else None)
    return out


def volume_ma(candles, period=20):
    """Simple moving average of candle volume; None until the period has warmed up."""
    vols = [c.get("volume", 0) or 0 for c in candles]
    return sma(vols, period)


def ichimoku(candles, tenkan=9, kijun=26, senkou=52):
    n = len(candles)

    def helper(i, length):
        if i < length - 1:
            return None
        h = -math.inf
        l = math.inf
        for j in range(i - length + 1, i + 1):
            h = max(h, candles[j]["high"])
            l = min(l, candles[j]["low"])
        return (h + l) / 2

    tenkan_sen = [helper(i, tenkan) for i in range(n)]
    kijun_sen = [helper(i, kijun) for i in range(n)]
    senkou_a = [
        None if (_is_null(tenkan_sen[i]) or _is_null(kijun_sen[i])) else (tenkan_sen[i] + kijun_sen[i]) / 2
        for i in range(n)
    ]
    senkou_b = [helper(i, senkou) for i in range(n)]
    chikou = [candles[i + kijun]["close"] if i + kijun < n else None for i in range(n)]
    return {"tenkanSen": tenkan_sen, "kijunSen": kijun_sen, "senkouA": senkou_a, "senkouB": senkou_b, "chikou": chikou}


def keltner(candles, period=20, mult=2):
    ema_val = ema([c["close"] for c in candles], period)
    atr_val = atr(candles, period)
    upper = []
    lower = []
    for i in range(len(candles)):
        if _is_null(ema_val[i]) or _is_null(atr_val[i]):
            upper.append(None)
            lower.append(None)
            continue
        upper.append(ema_val[i] + mult * atr_val[i])
        lower.append(ema_val[i] - mult * atr_val[i])
    return {"upper": upper, "middle": ema_val, "lower": lower}


def donchian(candles, period=20):
    upper = []
    lower = []
    for i in range(len(candles)):
        if i < period - 1:
            upper.append(None)
            lower.append(None)
            continue
        h = -math.inf
        l = math.inf
        for j in range(i - period + 1, i + 1):
            h = max(h, candles[j]["high"])
            l = min(l, candles[j]["low"])
        upper.append(h)
        lower.append(l)
    return {"upper": upper, "lower": lower}


def parabolic_sar(candles, step=0.02, max_step=0.2):
    out = []
    if len(candles) == 0:
        return out
    sar = candles[0]["low"]
    af = step
    trend = 1
    ep = candles[0]["high"]
    for i in range(1, len(candles)):
        sar = sar + af * (ep - sar)
        if trend == 1:
            prev_low = candles[i - 1]["low"]
            prev2_low = candles[i - 2]["low"] if i >= 2 else candles[i - 1]["low"]
            sar = min(sar, prev_low, prev2_low)
            if candles[i]["low"] < sar:
                trend = -1
                sar = ep
                ep = candles[i]["low"]
                af = step
            elif candles[i]["high"] > ep:
                ep = candles[i]["high"]
                af = min(af + step, max_step)
        else:
            prev_high = candles[i - 1]["high"]
            prev2_high = candles[i - 2]["high"] if i >= 2 else candles[i - 1]["high"]
            sar = max(sar, prev_high, prev2_high)
            if candles[i]["high"] > sar:
                trend = 1
                sar = ep
                ep = candles[i]["high"]
                af = step
            elif candles[i]["low"] < ep:
                ep = candles[i]["low"]
                af = min(af + step, max_step)
        out.append({"sar": sar, "trend": trend})
    return [None, *out]


def calculate_all_indicators(candles):
    closes = [c["close"] for c in candles]
    last = len(candles) - 1
    bb = bollinger(closes)
    macd_data = macd(closes)
    stoch = stochastic(candles)
    st_result = super_trend(candles)
    st_last = st_result[-1] if st_result else None
    ps_result = parabolic_sar(candles)
    ps_last = ps_result[-1] if ps_result else None
    wr = williams_r(candles)
    vma = volume_ma(candles)
    return {
        "sma20": sma(closes, 20)[last],
        "sma50": sma(closes, 50)[last],
        "sma200": sma(closes, 200)[last],
        "ema20": ema(closes, 20)[last],
        "ema50": ema(closes, 50)[last],
        "ema200": ema(closes, 200)[last],
        "rsi14": rsi(closes, 14)[last],
        "macd": macd_data,
        "adx": adx(candles)["adx"][last],
        "atr14": atr(candles, 14)[last],
        "bollinger": {"upper": bb["upper"][last], "middle": bb["middle"][last], "lower": bb["lower"][last]},
        "vwap": vwap(candles)[last],
        "stochastic": stoch,
        "obv": obv(candles)[last],
        "cmf20": cmf(candles)[last],
        "cci20": cci(candles)[last],
        "mfi14": mfi(candles)[last],
        "roc12": roc(closes)[last],
        "williamsR14": wr[last],
        "volumeMa20": vma[last],
        "superTrend": st_last,
        "keltner": keltner(candles),
        "donchian": donchian(candles),
        "parabolicSar": ps_last,
        "ichimoku": ichimoku(candles),
    }

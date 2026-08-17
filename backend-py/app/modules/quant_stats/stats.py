"""Quantitative statistics (additive pro module).

Pure statistical analysis over return / price series: CAPM, normality tests,
unit-root tests and rolling statistics. Uses numpy/scipy/statsmodels and
degrades gracefully on short/invalid input.
"""
import numpy as np

from .common import _py, _safe_series


def capm(asset_returns, benchmark_returns, risk_free_rate=0.0):
    """Single-factor CAPM regression: returns alpha, beta, R2, correlation."""
    a = _safe_series(asset_returns)
    b = _safe_series(benchmark_returns)
    if a.size < 5 or b.size < 5:
        return {"available": False, "reason": "insufficient-data"}

    n = min(a.size, b.size)
    a, b = a[-n:], b[-n:]
    excess_a = a - risk_free_rate / 252.0 if risk_free_rate else a
    excess_b = b - risk_free_rate / 252.0 if risk_free_rate else b

    var_b = float(np.var(excess_b))
    if var_b <= 0:
        return {"available": False, "reason": "zero-benchmark-variance"}

    beta = float(np.cov(excess_a, excess_b)[0][1] / var_b)
    alpha = float(np.mean(excess_a) - beta * np.mean(excess_b))
    corr = float(np.corrcoef(a, b)[0][1]) if a.size > 1 else 0.0
    r2 = float(np.corrcoef(a, b)[0][1] ** 2) if a.size > 1 else 0.0

    residual = excess_a - (alpha + beta * excess_b)
    total_var = float(np.var(excess_a)) if excess_a.size > 1 else 0.0
    res_var = float(np.var(residual)) if residual.size > 1 else 0.0
    systematic = float(np.var(beta * excess_b)) if excess_b.size > 1 else 0.0
    unsystematic = res_var

    beta_annual = float(np.std(a) * np.sqrt(252)) if a.size > 1 else 0.0

    return {
        "available": True,
        "alpha": round(alpha, 8),
        "beta": round(beta, 6),
        "correlation": round(corr, 6),
        "rSquared": round(r2, 6),
        "systematicVariance": round(systematic, 12),
        "unsystematicVariance": round(unsystematic, 12),
        "totalVariance": round(total_var, 12),
        "assetVolatilityAnnualized": round(beta_annual, 6),
        "riskFreeRate": _py(risk_free_rate),
        "n": int(n),
    }


def normality(returns):
    """Normality tests: Shapiro-Wilk + D'Agostino K^2 + skew/kurtosis."""
    from scipy import stats as scipy_stats

    r = _safe_series(returns)
    if r.size < 8:
        return {"available": False, "reason": "insufficient-data"}

    result = {"available": True, "n": int(r.size)}
    result["skewness"] = round(float(scipy_stats.skew(r)), 6)
    result["kurtosis"] = round(float(scipy_stats.kurtosis(r)), 6)

    try:
        if r.size <= 5000:
            w, p = scipy_stats.shapiro(r)
            result["shapiro"] = {"statistic": round(float(w), 6), "pValue": round(float(p), 6),
                                 "normal": bool(p >= 0.05)}
        else:
            result["shapiro"] = None
    except Exception as exc:  # pragma: no cover - defensive
        result["shapiro"] = {"error": str(exc)}

    try:
        if r.size >= 20:
            k2, p_k2 = scipy_stats.normaltest(r)
            result["dagostino"] = {"statistic": round(float(k2), 6), "pValue": round(float(p_k2), 6),
                                   "normal": bool(p_k2 >= 0.05)}
        else:
            result["dagostino"] = None
    except Exception as exc:  # pragma: no cover - defensive
        result["dagostino"] = {"error": str(exc)}

    verdicts = []
    if result.get("shapiro") and result["shapiro"].get("normal") is not None:
        verdicts.append("normal" if result["shapiro"]["normal"] else "non-normal")
    if result.get("dagostino") and result["dagostino"].get("normal") is not None:
        verdicts.append("normal" if result["dagostino"]["normal"] else "non-normal")
    result["verdict"] = "normal" if verdicts and all(v == "normal" for v in verdicts) else "non-normal"
    return result


def unit_root(series):
    """ADF + KPSS unit-root tests on a price series."""
    from statsmodels.tsa.stattools import adfuller, kpss

    s = _safe_series(series)
    if s.size < 10:
        return {"available": False, "reason": "insufficient-data"}

    result = {"available": True, "n": int(s.size)}

    try:
        adf_stat, adf_p, usedlag, nobs, crit, icbest = adfuller(s, autolag="AIC")
        result["adf"] = {
            "statistic": round(float(adf_stat), 6),
            "pValue": round(float(adf_p), 6),
            "usedLag": int(usedlag),
            "nobs": int(nobs),
            "criticalValues": {k: round(float(v), 4) for k, v in crit.items()},
            "stationary": bool(adf_p < 0.05),
        }
    except Exception as exc:  # pragma: no cover - defensive
        result["adf"] = {"error": str(exc)}

    try:
        kpss_stat, kpss_p, kpss_lags, kpss_crit = kpss(s, regression="c", nlags="auto")
        result["kpss"] = {
            "statistic": round(float(kpss_stat), 6),
            "pValue": round(float(kpss_p), 6),
            "lags": int(kpss_lags),
            "criticalValues": {k: round(float(v), 4) for k, v in kpss_crit.items()},
            "stationary": bool(kpss_p >= 0.05),
        }
    except Exception as exc:  # pragma: no cover - defensive
        result["kpss"] = {"error": str(exc)}

    verdicts = []
    adf_ok = result.get("adf", {}).get("stationary")
    kpss_ok = result.get("kpss", {}).get("stationary")
    if adf_ok is not None and kpss_ok is not None:
        verdicts.append("stationary" if adf_ok and kpss_ok else "non-stationary")
    elif adf_ok is not None:
        verdicts.append("stationary" if adf_ok else "non-stationary")
    elif kpss_ok is not None:
        verdicts.append("stationary" if kpss_ok else "non-stationary")
    result["verdict"] = verdicts[0] if verdicts else "unknown"
    return result


def rolling_stats(returns, window=20):
    """Rolling mean/std/skew/kurtosis/min/max + current z-score."""
    from scipy import stats as scipy_stats

    r = _safe_series(returns)
    if r.size < window or window < 2:
        return {"available": False, "reason": "insufficient-data"}

    def _roll(fn):
        out = np.full(r.size, np.nan)
        for i in range(window - 1, r.size):
            try:
                out[i] = float(fn(r[i - window + 1:i + 1]))
            except Exception:
                out[i] = np.nan
        return out

    rolling_mean = _roll(np.mean)
    rolling_std = _roll(np.std)
    rolling_min = _roll(np.min)
    rolling_max = _roll(np.max)
    rolling_skew = _roll(scipy_stats.skew)
    rolling_kurt = _roll(scipy_stats.kurtosis)

    cur_mean = rolling_mean[-1]
    cur_std = rolling_std[-1]
    zscore = (r[-1] - cur_mean) / cur_std if cur_std and cur_std > 0 else 0.0

    return {
        "available": True,
        "window": int(window),
        "n": int(r.size),
        "current": {
            "mean": _py(rolling_mean[-1]),
            "std": _py(rolling_std[-1]),
            "min": _py(rolling_min[-1]),
            "max": _py(rolling_max[-1]),
            "skewness": _py(rolling_skew[-1]),
            "kurtosis": _py(rolling_kurt[-1]),
            "zScore": round(float(zscore), 6),
        },
        "series": {
            "mean": [_py(v) for v in rolling_mean],
            "std": [_py(v) for v in rolling_std],
            "min": [_py(v) for v in rolling_min],
            "max": [_py(v) for v in rolling_max],
            "skewness": [_py(v) for v in rolling_skew],
            "kurtosis": [_py(v) for v in rolling_kurt],
        },
    }

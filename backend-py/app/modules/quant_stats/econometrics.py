"""Econometrics for the quant_stats module (additive).

Correlation matrix, cointegration (Engle-Granger / Johansen via statsmodels)
and OLS regression. All degrade gracefully on short/invalid input.
"""
import numpy as np

from .common import _py, _safe_series


def correlation(x, y, method="pearson"):
    """Correlation between two series with p-value (scipy)."""
    from scipy import stats as scipy_stats

    a = _safe_series(x)
    b = _safe_series(y)
    if a.size < 5 or b.size < 5:
        return {"available": False, "reason": "insufficient-data"}
    n = min(a.size, b.size)
    a, b = a[-n:], b[-n:]
    methods = {
        "pearson": scipy_stats.pearsonr,
        "spearman": scipy_stats.spearmanr,
        "kendall": scipy_stats.kendalltau,
    }
    fn = methods.get((method or "pearson").lower(), scipy_stats.pearsonr)
    try:
        stat, p = fn(a, b)
        return {
            "available": True,
            "method": (method or "pearson").lower(),
            "coefficient": round(float(stat), 6),
            "pValue": round(float(p), 6),
            "n": int(n),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "reason": "internal-error", "error": str(exc)}


def correlation_matrix(series_map, method="pearson"):
    """Full correlation matrix across several named series."""
    names = list(series_map.keys())
    if len(names) < 2:
        return {"available": False, "reason": "insufficient-series"}
    matrix = {}
    for i, ni in enumerate(names):
        matrix[ni] = {}
        for j, nj in enumerate(names):
            if j == i:
                matrix[ni][nj] = 1.0
            elif j < i:
                matrix[ni][nj] = matrix[nj][ni]
            else:
                res = correlation(series_map[ni], series_map[nj], method=method)
                matrix[ni][nj] = res.get("coefficient") if res.get("available") else None
    return {
        "available": True,
        "method": method,
        "series": names,
        "matrix": matrix,
    }


def cointegration(x, y):
    """Engle-Granger cointegration test between two price series."""
    from statsmodels.tsa.stattools import coint

    a = _safe_series(x)
    b = _safe_series(y)
    if a.size < 20 or b.size < 20:
        return {"available": False, "reason": "insufficient-data"}
    n = min(a.size, b.size)
    a, b = a[-n:], b[-n:]
    try:
        stat, p, crit = coint(a, b)
        crit_values = {}
        if hasattr(crit, "items"):
            crit_values = {k: round(float(v), 4) for k, v in crit.items()}
        elif hasattr(crit, "__iter__"):
            try:
                crit_values = {"1%": round(float(crit[0]), 4), "5%": round(float(crit[1]), 4),
                               "10%": round(float(crit[2]), 4)}
            except Exception:
                crit_values = {}
        return {
            "available": True,
            "method": "engle-granger",
            "statistic": round(float(stat), 6),
            "pValue": round(float(p), 6),
            "criticalValues": crit_values,
            "cointegrated": bool(p < 0.05),
            "n": int(n),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "reason": "internal-error", "error": str(exc)}


def johansen(matrix, det_order=0, k_ar_diff=1):
    """Johansen cointegration test on a matrix of price series (rows=time)."""
    try:
        from statsmodels.tsa.vector_ar.vecm import coint_johansen
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "reason": "internal-error", "error": str(exc)}
    arr = _safe_series(matrix) if not hasattr(matrix, "shape") else np.asarray(matrix, dtype=float)
    if arr.ndim != 2 or arr.shape[0] < 30 or arr.shape[1] < 2:
        return {"available": False, "reason": "insufficient-data"}
    try:
        res = coint_johansen(arr, det_order, k_ar_diff)
        return {
            "available": True,
            "method": "johansen",
            "traceStatistic": [_py(v) for v in res.lr1],
            "traceCritical": {k: [_py(v) for v in row] for k, row in res.cvt.items()},
            "maxEigenStatistic": [_py(v) for v in res.lr2],
            "maxEigenCritical": {k: [_py(v) for v in row] for k, row in res.cvm.items()},
            "eigenvectors": [[_py(v) for v in row] for row in res.evec],
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "reason": "internal-error", "error": str(exc)}


def ols(y, x, add_const=True):
    """OLS regression of y on x (one or more regressors) via statsmodels."""
    from statsmodels.api import OLS as SmOLS
    from statsmodels.tools import add_constant

    y_arr = _safe_series(y)
    if y_arr.size < 10:
        return {"available": False, "reason": "insufficient-data"}

    if isinstance(x, dict):
        names = list(x.keys())
        x_cols = [_safe_series(x[k]) for k in names]
        n = min([y_arr.size] + [c.size for c in x_cols])
        y_arr = y_arr[-n:]
        X = np.column_stack([c[-n:] for c in x_cols])
    else:
        x_arr = _safe_series(x)
        n = min(y_arr.size, x_arr.size)
        y_arr = y_arr[-n:]
        X = x_arr[-n:].reshape(-1, 1)
        names = ["x1"]

    if add_const:
        X = add_constant(X, has_constant="add")
        col_names = ["const"] + names
    else:
        col_names = names

    try:
        model = SmOLS(y_arr, X).fit()
        resid = np.asarray(model.resid, dtype=float)
        dw = None
        if resid.size > 2:
            diff = np.diff(resid)
            denom = float(np.sum(resid ** 2))
            dw = float(np.sum(diff ** 2) / denom) if denom > 0 else None
        params = model.params
        tvalues = model.tvalues
        pvalues = model.pvalues
        ci = model.conf_int()
        coefficients = []
        for i, name in enumerate(col_names):
            coefficients.append({
                "name": name,
                "coefficient": round(float(params[i]), 8),
                "stdError": round(float(model.bse[i]), 8),
                "tStatistic": round(float(tvalues[i]), 6),
                "pValue": round(float(pvalues[i]), 6),
                "confIntLow": round(float(ci[i][0]), 8),
                "confIntHigh": round(float(ci[i][1]), 8),
            })
        return {
            "available": True,
            "method": "OLS",
            "n": int(model.nobs),
            "rSquared": round(float(model.rsquared), 6),
            "adjRSquared": round(float(model.rsquared_adj), 6),
            "fStatistic": round(float(model.fvalue), 6),
            "fPValue": round(float(model.f_pvalue), 6),
            "aic": round(float(model.aic), 4),
            "bic": round(float(model.bic), 4),
            "dw": round(dw, 4) if dw is not None else None,
            "coefficients": coefficients,
            "residualStdDev": round(float(np.std(resid)), 8),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": False, "reason": "internal-error", "error": str(exc)}

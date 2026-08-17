"""Portfolio allocation + stress-testing engine (additive, skfolio-based).

Provides two capabilities for the trader:

  1. risk-based multi-asset allocation — Hierarchical Risk Parity (HRP) and a
     CVaR-minimizing allocation, built with the ``skfolio`` library on top of
     the existing marketdata candle feed (``generate_candles`` is reused, no
     fetch logic is duplicated here).
  2. portfolio stress-testing — "how much would my current portfolio lose
     under a crisis scenario". skfolio ships no named crisis presets, so the
     fixed set of selectable scenarios below is mapped to a manually-defined
     factor shock per asset class (the exact allowance in the spec). When
     skfolio is installed the engine additionally attempts a synthetic-data
     (``VineCopula`` conditioning) stress estimate; if that fails or skfolio
     is missing it degrades to the deterministic factor-shock model.

skfolio is imported lazily so that a missing / partially-installed package can
never crash the app — every public function returns a clean
``{"status": "degraded", ...}`` payload instead of raising.
"""
import math

from ...foundation.logger import logger

DEFAULT_LOOKBACK = 250
MIN_CANDLES = 60
MIN_RETURN_ROWS = 30
TRADING_DAYS = 252

# Fixed set of selectable stress-test presets for the frontend dropdown.
STRESS_SCENARIOS = [
    {
        "id": "2008_financial_crisis",
        "name": "2008 Financial Crisis",
        "description": "Global equity crash and credit freeze; safe-haven bid into gold and bonds.",
    },
    {
        "id": "covid_crash",
        "name": "COVID Crash (Mar 2020)",
        "description": "Rapid risk-off, liquidity scramble and a broad dollar spike.",
    },
    {
        "id": "fed_rate_shock",
        "name": "Fed Rate Shock",
        "description": "Surprise hawkish repricing; equities and EM hit, USD strengthens.",
    },
    {
        "id": "oil_price_crash",
        "name": "Oil Price Crash",
        "description": "Energy selloff drags oil-sensitive FX and equity indices lower.",
    },
]

# Manual factor shocks per scenario (approximate stressed cumulative return per
# symbol). Symbols not present fall back to a conservative asset-class default.
_FACTOR_SHOCKS = {
    "2008_financial_crisis": {
        "US500": -0.45, "NAS100": -0.48, "US30": -0.38, "WTI": -0.62,
        "XAUUSD": 0.08, "XAGUSD": -0.06, "EURUSD": -0.05, "GBPUSD": -0.10,
        "USDJPY": -0.12, "AUDUSD": -0.20, "BTCUSD": -0.50, "ETHUSD": -0.55,
        "AAPL": -0.45, "TSLA": -0.55,
    },
    "covid_crash": {
        "US500": -0.34, "NAS100": -0.32, "US30": -0.36, "WTI": -0.55,
        "XAUUSD": 0.05, "XAGUSD": -0.10, "EURUSD": -0.03, "GBPUSD": -0.08,
        "USDJPY": -0.10, "AUDUSD": -0.15, "BTCUSD": -0.40, "ETHUSD": -0.45,
        "AAPL": -0.30, "TSLA": -0.40,
    },
    "fed_rate_shock": {
        "US500": -0.15, "NAS100": -0.20, "US30": -0.12, "WTI": -0.08,
        "XAUUSD": -0.12, "XAGUSD": -0.14, "EURUSD": -0.04, "GBPUSD": -0.04,
        "USDJPY": 0.06, "AUDUSD": -0.06, "BTCUSD": -0.18, "ETHUSD": -0.20,
        "AAPL": -0.12, "TSLA": -0.18,
    },
    "oil_price_crash": {
        "US500": -0.10, "NAS100": -0.12, "US30": -0.08, "WTI": -0.42,
        "XAUUSD": 0.03, "XAGUSD": -0.06, "EURUSD": -0.03, "GBPUSD": -0.03,
        "USDJPY": -0.04, "AUDUSD": -0.10, "BTCUSD": -0.15, "ETHUSD": -0.16,
        "AAPL": -0.08, "TSLA": -0.10,
    },
}

# Conservative per-asset-class default shock when a symbol has no direct entry.
_CLASS_DEFAULTS = {
    "equity": -0.15,
    "index": -0.15,
    "crypto": -0.25,
    "commodity": -0.15,
    "fx": -0.04,
}


def _class_for_symbol(symbol):
    """Coarse asset-class label used only for stress-shock fallbacks."""
    sym = str(symbol or "").upper()
    if sym in ("XAUUSD", "XAGUSD", "WTI", "UKOIL", "USOIL"):
        return "commodity"
    if sym in ("BTCUSD", "ETHUSD"):
        return "crypto"
    if sym in ("US500", "NAS100", "US30", "SPX500", "NDX100", "DJ30"):
        return "index"
    if any(sym.endswith(c) for c in ("USD", "JPY", "EUR", "GBP", "AUD", "CAD", "NZD", "CHF")):
        return "fx"
    return "equity"


def _fetch_aligned_returns(symbols, lookback):
    """Reuse the existing marketdata candle feed; return an aligned returns
    DataFrame (symbol columns, daily simple returns) or ``None``."""
    try:
        from ..marketdata.engine import generate_candles
        import pandas as pd
    except Exception as exc:  # noqa: BLE001 - data layer must degrade cleanly
        logger.warn(f"portfolio optimizer: data layer unavailable: {exc}")
        return None

    lookback = max(MIN_CANDLES, int(lookback or DEFAULT_LOOKBACK))
    closes = {}
    for symbol in symbols:
        try:
            candles = generate_candles(symbol, timeframe="D1", count=lookback)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not break the rest
            logger.warn(f"portfolio optimizer: candle fetch failed for {symbol}: {exc}")
            continue
        if not candles or len(candles) < MIN_CANDLES:
            logger.warn(f"portfolio optimizer: insufficient candles for {symbol}")
            continue
        # Positional alignment: last N closes per symbol. Candle grids differ
        # across symbols (live feeds / simulator use independent timestamps), so
        # exact-time joins would drop every row — positional alignment keeps the
        # most recent window for each symbol.
        closes[symbol] = [float(c["close"]) for c in candles]

    if len(closes) < 2:
        return None
    prices = pd.DataFrame(closes)
    returns = prices.pct_change().dropna(how="any")
    if returns.shape[0] < MIN_RETURN_ROWS:
        return None
    return returns.iloc[-lookback:]


def _annualized_vol(series):
    """Annualized realized volatility from a simple-returns Series."""
    std = series.std()
    if std is None or math.isnan(std) or std <= 0:
        return 0.0
    return float(std * math.sqrt(TRADING_DAYS))


def _cvar(series, alpha=0.95):
    """Historical CVaR at the given confidence level (positive loss)."""
    import numpy as np

    arr = series.dropna().to_numpy()
    if arr.size == 0:
        return 0.0
    n = max(1, int((1 - alpha) * arr.size))
    return float(-1.0 * np.sort(arr)[:n].mean())


def _portfolio_metrics(returns_df):
    """Per-asset volatility / CVaR and the correlation matrix."""
    import numpy as np

    metrics = {}
    for col in returns_df.columns:
        series = returns_df[col]
        metrics[col] = {
            "expectedVolatility": round(_annualized_vol(series), 4),
            "cvar": round(_cvar(series), 4),
        }
    corr = returns_df.corr()
    corr_map = {
        str(i): {str(j): (None if math.isnan(float(corr.loc[i, j])) else round(float(corr.loc[i, j]), 4))
                 for j in corr.columns}
        for i in corr.index
    }
    return metrics, corr_map


def allocate(symbols, lookback=DEFAULT_LOOKBACK):
    """HRP + CVaR-min allocations with basic risk stats.

    Returns ``{"status": "ok", ...}`` or a clean ``{"status": "degraded", ...}``.
    """
    symbols = [str(s).upper() for s in (symbols or []) if str(s).strip()]
    if len(symbols) < 2:
        return {"status": "degraded", "error": "at least two symbols are required for allocation"}

    try:
        import skfolio  # noqa: F401 - presence check only
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "error": f"skfolio is not installed: {exc}"}

    returns_df = _fetch_aligned_returns(symbols, lookback)
    if returns_df is None or returns_df.shape[1] < 2:
        return {"status": "degraded", "error": "insufficient aligned price history for the selected symbols"}

    cols = list(returns_df.columns)
    try:
        import numpy as np

        from skfolio import RiskMeasure
        from skfolio.optimization import HierarchicalRiskParity, MeanRisk

        hrp_model = HierarchicalRiskParity(risk_measure=RiskMeasure.VARIANCE)
        hrp_model.fit(returns_df)
        hrp_weights = {cols[i]: round(float(hrp_model.weights_[i]), 4) for i in range(len(cols))}

        cvar_model = MeanRisk(risk_measure=RiskMeasure.CVAR)
        cvar_model.fit(returns_df)
        cvar_weights = {cols[i]: round(float(cvar_model.weights_[i]), 4) for i in range(len(cols))}

        cov = returns_df.cov().to_numpy() * TRADING_DAYS
        hrp_vol = float(math.sqrt(float(np.dot(np.dot(np.array([hrp_weights[c] for c in cols]), cov), np.array([hrp_weights[c] for c in cols])))))
        cvar_vol = float(math.sqrt(float(np.dot(np.dot(np.array([cvar_weights[c] for c in cols]), cov), np.array([cvar_weights[c] for c in cols])))))
        hrp_stats = {
            "expectedVolatility": round(hrp_vol, 4),
            "cvar": round(float(getattr(hrp_model.predict(returns_df), "cvar", 0.0) or 0.0), 4),
        }
        cvar_stats = {
            "expectedVolatility": round(cvar_vol, 4),
            "cvar": round(float(getattr(cvar_model.predict(returns_df), "cvar", 0.0) or 0.0), 4),
        }
    except Exception as exc:  # noqa: BLE001 - optimizer must never crash the route
        logger.warn(f"portfolio optimizer: skfolio fit failed: {exc}")
        return {"status": "degraded", "error": f"allocation failed: {exc}"}

    per_asset, corr_map = _portfolio_metrics(returns_df)
    return {
        "status": "ok",
        "symbols": cols,
        "lookback": len(returns_df),
        "hrp": {"weights": hrp_weights, "riskStats": hrp_stats},
        "cvar": {"weights": cvar_weights, "riskStats": cvar_stats},
        "riskStats": {"perAsset": per_asset, "correlation": corr_map},
    }


def _skfolio_stress_estimate(returns_df, weights_map, shock_spec):
    """Attempt a skfolio synthetic-data (VineCopula conditioning) stress
    estimate of the portfolio's stressed return. Raises on any failure so the
    caller can fall back to the deterministic factor-shock model."""
    from skfolio.distribution import VineCopula

    cols = list(returns_df.columns)
    central = next((c for c in cols if c in shock_spec), cols[0])
    shock_value = float(shock_spec.get(central, -0.15))
    vine = VineCopula(log_transform=True, central_assets=[central], n_jobs=1, random_state=42)
    vine.fit(returns_df)
    stressed = vine.sample(n_samples=5000, conditioning={central: shock_value})
    if hasattr(stressed, "columns"):  # pandas DataFrame
        means = stressed.mean()
        import numpy as np

        return float((means.to_numpy() * np.array([float(weights_map.get(c, 0.0)) for c in cols])).sum())
    import numpy as np

    means = np.asarray(stressed).mean(axis=0)
    return float((means * np.array([float(weights_map.get(c, 0.0)) for c in cols])).sum())


def run_stress_test(symbols, weights, scenario):
    """Estimated portfolio P&L / drawdown under a named crisis scenario.

    Tries skfolio's synthetic-data stress first, then falls back to the
    deterministic per-asset factor-shock model. Never raises.
    """
    scenario_id = str(scenario or "").lower()
    scenario_meta = next((s for s in STRESS_SCENARIOS if s["id"] == scenario_id), None)
    if not scenario_meta:
        return {
            "status": "degraded",
            "error": f"unknown scenario '{scenario}'",
            "available": [s["id"] for s in STRESS_SCENARIOS],
        }

    symbols = [str(s).upper() for s in (symbols or []) if str(s).strip()]
    if not symbols:
        return {"status": "degraded", "error": "symbols are required for a stress test"}

    weights_map = {}
    for sym in symbols:
        w = weights.get(sym)
        if w is None:
            w = weights.get(sym.lower())
        try:
            weights_map[sym] = float(w) if w is not None else 0.0
        except (TypeError, ValueError):
            weights_map[sym] = 0.0
    total = sum(weights_map.values())
    if total <= 0:
        return {"status": "degraded", "error": "portfolio weights must sum to a positive value"}
    weights_map = {k: v / total for k, v in weights_map.items()}

    shock_spec = _FACTOR_SHOCKS.get(scenario_id, {})

    method = "factor_shock"
    stressed_return = 0.0
    try:
        returns_df = _fetch_aligned_returns(symbols, DEFAULT_LOOKBACK)
        if returns_df is not None:
            stressed_return = _skfolio_stress_estimate(returns_df, weights_map, shock_spec)
            method = "skfolio_vine_copula"
    except Exception as exc:  # noqa: BLE001 - fall back to the deterministic model
        logger.warn(f"portfolio optimizer: skfolio stress estimate failed, using factor shocks: {exc}")

    if method == "factor_shock":
        per_symbol = {}
        for sym in symbols:
            shocked = shock_spec.get(sym)
            if shocked is None:
                shocked = _CLASS_DEFAULTS.get(_class_for_symbol(sym), -0.10)
            per_symbol[sym] = round(float(shocked), 4)
        stressed_return = sum(weights_map[sym] * per_symbol[sym] for sym in symbols)

    loss_pct = round(stressed_return * 100.0, 2)
    per_symbol_rows = [
        {
            "symbol": sym,
            "weight": round(weights_map[sym], 4),
            "shockedReturnPct": round(
                (shock_spec.get(sym) if shock_spec.get(sym) is not None
                 else _CLASS_DEFAULTS.get(_class_for_symbol(sym), -0.10)) * 100.0, 2),
            "contributionPct": round(weights_map[sym] * 100.0 * loss_pct, 2),
        }
        for sym in symbols
    ]
    return {
        "status": "ok",
        "scenario": scenario_meta,
        "method": method,
        "portfolioLossPct": loss_pct,
        "drawdownEstimatePct": round(loss_pct, 2),
        "perSymbol": per_symbol_rows,
    }

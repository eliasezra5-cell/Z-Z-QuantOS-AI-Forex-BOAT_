"""Additive API router for pro quant statistics.

Mounted alongside the main router at /api. Provides POST /api/pro/quant/...
endpoints (capm, normality, unit-root, rolling-stats, correlation,
cointegration, ols) backed by modules/quant_stats/. Existing routes untouched.
"""
import logging

from fastapi import APIRouter

from ..foundation.logger import logger
from ..modules.marketdata.engine import generate_candles
from ..modules.quant_stats import econometrics, stats


def _returns(symbol, timeframe="H1", count=250):
    candles = generate_candles(symbol, timeframe, count)
    prices = [c["close"] for c in candles]
    if len(prices) < 3:
        return []
    out = []
    prev = prices[0]
    for p in prices[1:]:
        if prev:
            out.append((p - prev) / prev)
        prev = p
    return out


def _prices(symbol, timeframe="H1", count=250):
    candles = generate_candles(symbol, timeframe, count)
    return [c["close"] for c in candles]


def create_quant_stats_router():
    router = APIRouter()

    @router.post("/pro/quant/capm")
    def quant_capm(body: dict = None):
        body = body or {}
        symbol = body.get("symbol", "XAUUSD")
        benchmark = body.get("benchmark", "US500")
        timeframe = body.get("timeframe", "H1")
        count = int(body.get("count", 250))
        rf = float(body.get("riskFreeRate", 0.0))
        try:
            asset = _returns(symbol, timeframe, count)
            bench = _returns(benchmark, timeframe, count)
            result = stats.capm(asset, bench, risk_free_rate=rf)
            return {"symbol": symbol, "benchmark": benchmark, "timeframe": timeframe, "test": "capm", **result}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("quant/capm failed: %s", exc)
            return {"symbol": symbol, "benchmark": benchmark, "test": "capm",
                    "available": False, "reason": "internal-error"}

    @router.post("/pro/quant/normality")
    def quant_normality(body: dict = None):
        body = body or {}
        symbol = body.get("symbol", "XAUUSD")
        timeframe = body.get("timeframe", "H1")
        count = int(body.get("count", 250))
        try:
            rets = _returns(symbol, timeframe, count)
            result = stats.normality(rets)
            return {"symbol": symbol, "timeframe": timeframe, "test": "normality", **result}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("quant/normality failed: %s", exc)
            return {"symbol": symbol, "timeframe": timeframe, "test": "normality",
                    "available": False, "reason": "internal-error"}

    @router.post("/pro/quant/unit-root")
    def quant_unit_root(body: dict = None):
        body = body or {}
        symbol = body.get("symbol", "XAUUSD")
        timeframe = body.get("timeframe", "D")
        count = int(body.get("count", 250))
        try:
            prices = _prices(symbol, timeframe, count)
            result = stats.unit_root(prices)
            return {"symbol": symbol, "timeframe": timeframe, "test": "unit-root", **result}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("quant/unit-root failed: %s", exc)
            return {"symbol": symbol, "timeframe": timeframe, "test": "unit-root",
                    "available": False, "reason": "internal-error"}

    @router.post("/pro/quant/rolling-stats")
    def quant_rolling_stats(body: dict = None):
        body = body or {}
        symbol = body.get("symbol", "XAUUSD")
        timeframe = body.get("timeframe", "H1")
        count = int(body.get("count", 250))
        window = int(body.get("window", 20))
        try:
            rets = _returns(symbol, timeframe, count)
            result = stats.rolling_stats(rets, window=window)
            return {"symbol": symbol, "timeframe": timeframe, "test": "rolling-stats", **result}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("quant/rolling-stats failed: %s", exc)
            return {"symbol": symbol, "timeframe": timeframe, "test": "rolling-stats",
                    "available": False, "reason": "internal-error"}

    @router.post("/pro/quant/correlation")
    def quant_correlation(body: dict = None):
        body = body or {}
        symbol = body.get("symbol", "XAUUSD")
        benchmark = body.get("benchmark", "US500")
        timeframe = body.get("timeframe", "D")
        count = int(body.get("count", 250))
        method = body.get("method", "pearson")
        try:
            a = _returns(symbol, timeframe, count)
            b = _returns(benchmark, timeframe, count)
            result = econometrics.correlation(a, b, method=method)
            return {"symbol": symbol, "benchmark": benchmark, "timeframe": timeframe, "test": "correlation", **result}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("quant/correlation failed: %s", exc)
            return {"symbol": symbol, "benchmark": benchmark, "timeframe": timeframe,
                    "test": "correlation", "available": False, "reason": "internal-error"}

    @router.post("/pro/quant/cointegration")
    def quant_cointegration(body: dict = None):
        body = body or {}
        symbol = body.get("symbol", "XAUUSD")
        benchmark = body.get("benchmark", "US500")
        timeframe = body.get("timeframe", "D")
        count = int(body.get("count", 250))
        try:
            a = _prices(symbol, timeframe, count)
            b = _prices(benchmark, timeframe, count)
            result = econometrics.cointegration(a, b)
            return {"symbol": symbol, "benchmark": benchmark, "timeframe": timeframe, "test": "cointegration", **result}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("quant/cointegration failed: %s", exc)
            return {"symbol": symbol, "benchmark": benchmark, "timeframe": timeframe,
                    "test": "cointegration", "available": False, "reason": "internal-error"}

    @router.post("/pro/quant/ols")
    def quant_ols(body: dict = None):
        body = body or {}
        symbol = body.get("symbol", "XAUUSD")
        benchmark = body.get("benchmark", "US500")
        timeframe = body.get("timeframe", "D")
        count = int(body.get("count", 250))
        try:
            y = _returns(symbol, timeframe, count)
            x = _returns(benchmark, timeframe, count)
            result = econometrics.ols(y, x, add_const=True)
            return {"symbol": symbol, "regressor": benchmark, "timeframe": timeframe, "test": "ols", **result}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("quant/ols failed: %s", exc)
            return {"symbol": symbol, "regressor": benchmark, "timeframe": timeframe,
                    "test": "ols", "available": False, "reason": "internal-error"}

    return router

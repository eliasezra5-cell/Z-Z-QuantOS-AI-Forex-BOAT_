"""Additive pro-technical router.

Mounted alongside the main router at /api. Provides new /api/technical/pro/...
endpoints backed by modules/technical/indicators_pro.py. Existing
/technical/indicators endpoints in routes/api.py are untouched.
"""
import logging

from fastapi import APIRouter, Query

from ..foundation.logger import logger
from ..modules.marketdata.engine import generate_candles
from ..modules.technical import indicators_pro as pro

DEFAULT_BENCHMARK = pro.DEFAULT_BENCHMARK


def _candles(symbol, timeframe, count):
    return generate_candles(symbol, timeframe, count)


def create_technical_pro_router():
    router = APIRouter()

    @router.get("/technical/pro/ichimoku/{symbol}")
    def ichimoku(
        symbol: str,
        timeframe: str = Query("H1"),
        count: int = Query(300, ge=60, le=1000),
        tenkan: int = Query(9, ge=2),
        kijun: int = Query(26, ge=2),
        senkou_b: int = Query(52, ge=2),
    ):
        try:
            candles = _candles(symbol, timeframe, count)
            result = pro.ichimoku(candles, tenkan=tenkan, kijun=kijun, senkou_b=senkou_b)
            return {"symbol": symbol, "timeframe": timeframe, "indicator": "ichimoku", **result}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("pro/ichimoku failed for %s: %s", symbol, exc)
            return {"symbol": symbol, "timeframe": timeframe, "indicator": "ichimoku",
                    "available": False, "reason": "internal-error"}

    @router.get("/technical/pro/fibonacci/{symbol}")
    def fibonacci(
        symbol: str,
        timeframe: str = Query("H1"),
        count: int = Query(300, ge=60, le=1000),
        lookback: int = Query(200, ge=20),
    ):
        try:
            candles = _candles(symbol, timeframe, count)
            result = pro.fibonacci_retracement(candles, lookback=lookback)
            return {"symbol": symbol, "timeframe": timeframe, "indicator": "fibonacci", **result}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("pro/fibonacci failed for %s: %s", symbol, exc)
            return {"symbol": symbol, "timeframe": timeframe, "indicator": "fibonacci",
                    "available": False, "reason": "internal-error"}

    @router.get("/technical/pro/demark/{symbol}")
    def demark(
        symbol: str,
        timeframe: str = Query("H1"),
        count: int = Query(500, ge=60, le=1000),
    ):
        try:
            candles = _candles(symbol, timeframe, count)
            result = pro.demark_sequential(candles, lookback=count)
            return {"symbol": symbol, "timeframe": timeframe, "indicator": "demark", **result}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("pro/demark failed for %s: %s", symbol, exc)
            return {"symbol": symbol, "timeframe": timeframe, "indicator": "demark",
                    "available": False, "reason": "internal-error"}

    @router.get("/technical/pro/donchian/{symbol}")
    def donchian(
        symbol: str,
        timeframe: str = Query("H1"),
        count: int = Query(300, ge=60, le=1000),
        period: int = Query(20, ge=5),
    ):
        try:
            candles = _candles(symbol, timeframe, count)
            result = pro.donchian_channel(candles, period=period)
            return {"symbol": symbol, "timeframe": timeframe, "indicator": "donchian", **result}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("pro/donchian failed for %s: %s", symbol, exc)
            return {"symbol": symbol, "timeframe": timeframe, "indicator": "donchian",
                    "available": False, "reason": "internal-error"}

    @router.get("/technical/pro/clenow/{symbol}")
    def clenow(
        symbol: str,
        timeframe: str = Query("D"),
        count: int = Query(250, ge=90, le=1000),
        period: int = Query(90, ge=30),
    ):
        try:
            candles = _candles(symbol, timeframe, count)
            result = pro.clenow_momentum(candles, period=period)
            return {"symbol": symbol, "timeframe": timeframe, "indicator": "clenow", **result}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("pro/clenow failed for %s: %s", symbol, exc)
            return {"symbol": symbol, "timeframe": timeframe, "indicator": "clenow",
                    "available": False, "reason": "internal-error"}

    @router.get("/technical/pro/volatility-cones/{symbol}")
    def volatility_cones(
        symbol: str,
        timeframe: str = Query("D"),
        count: int = Query(400, ge=120, le=1000),
    ):
        try:
            candles = _candles(symbol, timeframe, count)
            result = pro.volatility_cones(candles)
            return {"symbol": symbol, "timeframe": timeframe, "indicator": "volatility-cones", **result}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("pro/volatility-cones failed for %s: %s", symbol, exc)
            return {"symbol": symbol, "timeframe": timeframe, "indicator": "volatility-cones",
                    "available": False, "reason": "internal-error"}

    @router.get("/technical/pro/relative-rotation/{symbol}")
    def relative_rotation(
        symbol: str,
        timeframe: str = Query("D"),
        count: int = Query(300, ge=60, le=1000),
        benchmark: str = Query(DEFAULT_BENCHMARK),
        window: int = Query(30, ge=5),
    ):
        try:
            candles = _candles(symbol, timeframe, count)
            bench_candles = _candles(benchmark, timeframe, count)
            result = pro.relative_rotation(candles, bench_candles, window=window)
            return {
                "symbol": symbol, "benchmark": benchmark, "timeframe": timeframe,
                "indicator": "relative-rotation", **result,
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("pro/relative-rotation failed for %s: %s", symbol, exc)
            return {"symbol": symbol, "benchmark": benchmark, "timeframe": timeframe,
                    "indicator": "relative-rotation", "available": False, "reason": "internal-error"}

    return router

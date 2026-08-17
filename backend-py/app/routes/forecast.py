"""Kronos Forecast router (additive, mounted at /api/pro/forecast).

Read-only GET that wraps modules/forecasting/kronos_engine.forecast(). The
engine is lazy-loaded and fails safe — a missing torch/model/download returns a
clean ``{"status": "unavailable", ...}`` payload with HTTP 200, never a crash.
"""
from fastapi import APIRouter, Query

from ..foundation.logger import logger
from ..modules.forecasting import kronos_engine


def create_forecast_router():
    router = APIRouter()

    @router.get("/pro/forecast/{symbol}")
    def forecast(
        symbol: str,
        horizon: int = Query(default=kronos_engine.DEFAULT_HORIZON, ge=1, le=256),
    ):
        try:
            return kronos_engine.forecast(symbol, horizon=horizon)
        except Exception as exc:  # noqa: BLE001 - defensive, engine never raises
            logger.warn(f"pro/forecast failed ({exc})")
            return {
                "status": "unavailable",
                "symbol": str(symbol).upper(),
                "horizon": horizon,
                "error": str(exc),
            }

    return router

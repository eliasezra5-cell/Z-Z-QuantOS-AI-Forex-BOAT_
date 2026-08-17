"""Derivatives router (additive pro module, Task 1.7).

Mounted at /api, provides:
  - GET /api/pro/derivatives/options-chain/{symbol}
  - GET /api/pro/derivatives/unusual/{symbol}
  - GET /api/pro/derivatives/futures-curve/{symbol}
  - GET /api/pro/derivatives/summary/{symbol}
"""
from fastapi import APIRouter

from ..foundation.logger import logger
from ..modules.derivatives import engine


def create_derivatives_router():
    router = APIRouter()

    @router.get("/pro/derivatives/options-chain/{symbol}")
    def options_chain(symbol: str, days: int = 30):
        try:
            return {"status": "ok", "data": engine.options_chain(symbol, days)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("derivatives/options-chain failed: %s", exc)
            return {"status": "degraded", "data": {"note": str(exc)}}

    @router.get("/pro/derivatives/unusual/{symbol}")
    def unusual_activity(symbol: str, limit: int = 8):
        try:
            return {"status": "ok", "data": engine.unusual_activity(symbol, limit)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("derivatives/unusual failed: %s", exc)
            return {"status": "degraded", "data": {"note": str(exc)}}

    @router.get("/pro/derivatives/futures-curve/{symbol}")
    def futures_curve(symbol: str):
        try:
            return {"status": "ok", "data": engine.futures_curve(symbol)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("derivatives/futures-curve failed: %s", exc)
            return {"status": "degraded", "data": {"note": str(exc)}}

    @router.get("/pro/derivatives/summary/{symbol}")
    def summary(symbol: str):
        try:
            return {"status": "ok", "data": engine.summary(symbol)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("derivatives/summary failed: %s", exc)
            return {"status": "degraded", "data": {"note": str(exc)}}

    return router

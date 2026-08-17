"""Additive API router for pro Institutional / Smart-Money flow.

Mounted alongside the main router at /api. Provides GET /api/pro/institutional/...
endpoints backed by modules/institutional_flow/. Existing routes untouched.
Every endpoint degrades gracefully — a failing provider returns partial data
plus a ``sources_failed`` list instead of crashing.
"""
from fastapi import APIRouter, Query

from ..foundation.logger import logger
from ..modules.institutional_flow import engine


def create_institutional_flow_router():
    router = APIRouter()

    @router.get("/pro/institutional/overview")
    def institutional_overview(
        symbol: str = Query("AAPL"),
        asset: str = Query("gold"),
    ):
        try:
            return engine.institutional_overview(symbol=symbol, asset=asset)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("institutional/overview failed: %s", exc)
            return {"available": False, "reason": "internal-error", "note": str(exc)}

    @router.get("/pro/institutional/short-interest/{symbol}")
    def short_interest(symbol: str):
        try:
            return engine.short_interest(symbol)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("institutional/short-interest failed: %s", exc)
            return {"symbol": symbol, "available": False, "reason": "internal-error", "note": str(exc)}

    @router.get("/pro/institutional/short-volume/{symbol}")
    def short_volume(symbol: str):
        try:
            return engine.short_volume(symbol)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("institutional/short-volume failed: %s", exc)
            return {"symbol": symbol, "available": False, "reason": "internal-error", "note": str(exc)}

    @router.get("/pro/institutional/darkpool/{symbol}")
    def darkpool(symbol: str):
        try:
            return engine.darkpool(symbol)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("institutional/darkpool failed: %s", exc)
            return {"symbol": symbol, "available": False, "reason": "internal-error", "note": str(exc)}

    @router.get("/pro/institutional/cot/{asset}")
    def cot(asset: str):
        try:
            return engine.cot(asset)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("institutional/cot failed: %s", exc)
            return {"asset": asset, "available": False, "reason": "internal-error", "note": str(exc)}

    @router.get("/pro/institutional/congress-trades")
    def congress_trades(limit: int = Query(12, ge=1, le=50)):
        try:
            return engine.congress_trades(limit=limit)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("institutional/congress-trades failed: %s", exc)
            return {"available": False, "reason": "internal-error", "note": str(exc)}

    @router.get("/pro/institutional/sec-filings/{symbol}")
    def sec_filings(symbol: str):
        try:
            return engine.sec_filings(symbol)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("institutional/sec-filings failed: %s", exc)
            return {"symbol": symbol, "available": False, "reason": "internal-error", "note": str(exc)}

    return router

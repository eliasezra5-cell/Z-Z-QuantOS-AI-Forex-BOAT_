"""Spec-aligned Fixed Income / Rates router (additive).

Mounted alongside the main router at /api. Provides the spec-named surface:
  - GET /api/pro/fixedincome/yield-curve
  - GET /api/pro/fixedincome/rates
  - GET /api/pro/fixedincome/spreads
Backed by modules/fixedincome/engine.py. Existing /curve, /history, /overview
endpoints remain untouched.
"""
from fastapi import APIRouter

from ..foundation.logger import logger
from ..modules.fixedincome import engine


def create_fixedincome_engine_router():
    router = APIRouter()

    @router.get("/pro/fixedincome/yield-curve")
    def yield_curve():
        try:
            return {"status": "ok", "data": engine.yield_curve()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("fixedincome/yield-curve failed: %s", exc)
            return {"status": "degraded", "data": {"note": str(exc)}}

    @router.get("/pro/fixedincome/rates")
    def rates():
        try:
            return {"status": "ok", "data": engine.rates()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("fixedincome/rates failed: %s", exc)
            return {"status": "degraded", "data": {"note": str(exc)}}

    @router.get("/pro/fixedincome/spreads")
    def spreads():
        try:
            return {"status": "ok", "data": engine.spreads()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("fixedincome/spreads failed: %s", exc)
            return {"status": "degraded", "data": {"note": str(exc)}}

    return router

"""Additive API router for pro Fixed Income.

Mounted alongside the main router at /api. Provides GET /api/pro/fixedincome/...
endpoints backed by modules/fixedincome/service.py. Existing routes untouched.
"""
import logging

from fastapi import APIRouter, Query

from ..foundation.logger import logger
from ..modules.fixedincome import service


def create_fixedincome_router():
    router = APIRouter()

    @router.get("/pro/fixedincome/curve")
    def treasury_curve():
        try:
            return {"status": "ok", "data": service.get_treasury_curve()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("fixedincome/curve failed: %s", exc)
            return {"status": "degraded", "data": service._simulate_yields()}

    @router.get("/pro/fixedincome/history")
    def yield_history(
        series: str = Query("DGS10"),
        count: int = Query(250, ge=30, le=1000),
    ):
        try:
            return {"status": "ok", "data": service.get_yield_curve_history(series, count)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("fixedincome/history failed: %s", exc)
            return {"status": "degraded", "data": {"series": series, "source": "error",
                                                   "data": [], "note": str(exc)}}

    @router.get("/pro/fixedincome/overview")
    def fixed_income_overview():
        try:
            curve = service.get_treasury_curve()
            us10y = next((p for p in (curve.get("curve") or []) if p["maturity"] == "us10y"), {})
            us2y = next((p for p in (curve.get("curve") or []) if p["maturity"] == "us2y"), {})
            spreads = curve.get("spreads") or {}
            inv_curve = (spreads.get("2s10s") or 0) < 0
            return {
                "status": "ok",
                "data": {
                    "source": curve.get("source"),
                    "us10y": us10y.get("yieldPct"),
                    "us2y": us2y.get("yieldPct"),
                    "spread2s10s": spreads.get("2s10s"),
                    "spread3m10y": spreads.get("3m10y"),
                    "invertedCurve": bool(inv_curve),
                    "fedFunds": (curve.get("rates") or {}).get("fedFunds"),
                    "note": curve.get("note"),
                },
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("fixedincome/overview failed: %s", exc)
            return {"status": "degraded", "data": {"note": str(exc)}}

    return router

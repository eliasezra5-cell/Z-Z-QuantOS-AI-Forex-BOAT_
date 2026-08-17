"""Additive API router for pro Extra Macro (official sources).

Mounted alongside the main router at /api. Provides:
  - GET /api/pro/macro/sources
  - GET /api/pro/macro/{source}/{id}
backed by modules/macro/extra.py. Existing macro routes untouched.
"""
import logging

from fastapi import APIRouter

from ..foundation.logger import logger
from ..modules.macro import extra


def create_macro_extra_router():
    router = APIRouter()

    @router.get("/pro/macro/sources")
    def macro_sources():
        try:
            return {"status": "ok", "data": extra.official_sources_status()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("macro/sources failed: %s", exc)
            return {"status": "degraded", "data": {"sources": {}}}

    @router.get("/pro/macro/{source}/{series_id}")
    def macro_indicator(source: str, series_id: str):
        try:
            return {"status": "ok", "data": extra.fetch_source_series(source, series_id)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("macro/%s failed: %s", source, exc)
            return {"status": "degraded", "source": source, "series": series_id,
                    "data": {"available": False, "reason": "internal-error", "note": str(exc)}}

    return router

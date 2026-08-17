"""Prediction Markets router (additive pro module).

Mounted alongside the main router at /api. Provides:
  - GET /api/pro/prediction-markets/search?topic=...&limit=...
  - GET /api/pro/prediction-markets/macro-overview
Backed by modules/prediction_markets/engine.py. Existing routes untouched.
"""
from fastapi import APIRouter, Query

from ..foundation.logger import logger
from ..modules.prediction_markets import engine


def create_prediction_markets_router():
    router = APIRouter()

    @router.get("/pro/prediction-markets/search")
    def prediction_markets_search(
        topic: str = Query("", description="Topic keyword"),
        limit: int = Query(6, ge=1, le=50),
    ):
        try:
            return {"status": "ok", "data": engine.search_markets(topic, limit=limit)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("prediction-markets/search failed: %s", exc)
            return {
                "status": "degraded",
                "data": {
                    "available": False,
                    "source": "polymarket",
                    "topic": topic,
                    "note": str(exc),
                    "markets": [],
                },
            }

    @router.get("/pro/prediction-markets/macro-overview")
    def prediction_markets_macro_overview(
        limit: int = Query(4, ge=1, le=10),
    ):
        try:
            return {"status": "ok", "data": engine.macro_overview(limit_per_topic=limit)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warn("prediction-markets/macro-overview failed: %s", exc)
            return {
                "status": "degraded",
                "data": {
                    "available": False,
                    "source": "polymarket",
                    "note": str(exc),
                    "groups": [],
                },
            }

    return router

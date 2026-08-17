"""Portfolio Optimizer router (additive, mounted at /api/pro/portfolio-optimizer).

Backed by modules/portfolio_optimizer/engine.py. Every endpoint fails safe —
a missing skfolio install, insufficient data or an unknown scenario returns a
clean ``{"status": "degraded", ...}`` payload with HTTP 200, never a crash.
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..foundation.logger import logger
from ..modules.portfolio_optimizer import engine


class AllocateRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=2, description="Portfolio symbols, e.g. ['XAUUSD', 'US500']")
    lookback: int = Field(default=engine.DEFAULT_LOOKBACK, ge=60, le=2000, description="Lookback period in daily candles")


class StressTestRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1)
    weights: dict[str, float] = Field(default_factory=dict)
    scenario: str = Field(..., description="One of the ids from GET /stress-scenarios")


def create_portfolio_optimizer_router():
    router = APIRouter()

    @router.post("/pro/portfolio-optimizer/allocate")
    def allocate(req: AllocateRequest):
        try:
            return engine.allocate(req.symbols, lookback=req.lookback)
        except Exception as exc:  # noqa: BLE001 - defensive, engine never raises
            logger.warn(f"portfolio-optimizer/allocate failed: {exc}")
            return {"status": "degraded", "error": str(exc)}

    @router.get("/pro/portfolio-optimizer/stress-scenarios")
    def stress_scenarios():
        try:
            return {"status": "ok", "scenarios": engine.STRESS_SCENARIOS}
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.warn(f"portfolio-optimizer/stress-scenarios failed: {exc}")
            return {"status": "degraded", "error": str(exc)}

    @router.post("/pro/portfolio-optimizer/stress-test")
    def stress_test(req: StressTestRequest):
        try:
            return engine.run_stress_test(req.symbols, req.weights, req.scenario)
        except Exception as exc:  # noqa: BLE001 - defensive, engine never raises
            logger.warn(f"portfolio-optimizer/stress-test failed: {exc}")
            return {"status": "degraded", "error": str(exc)}

    return router

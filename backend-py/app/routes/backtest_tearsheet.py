"""Backtest Tearsheet router (additive, mounted at /api/pro/backtest/tearsheet).

POST: runs the existing ``run_backtest`` with the given params, then builds an
institutional tearsheet (CAGR / Sharpe / Sortino / Calmar / volatility,
drawdown series, monthly returns, trade distribution). Pure analytics on the
existing result shape — the backtest engine itself is untouched. Fails safe to
``{"status": "degraded", ...}`` with HTTP 200, never a crash.
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..foundation.logger import logger
from ..modules.backtest.engine import run_backtest
from ..modules.backtest.tearsheet import build_tearsheet


class TearsheetRequest(BaseModel):
    symbol: str = Field(default="EURUSD")
    strategy: str = Field(default="trend-follow")
    timeframe: str = Field(default="H1")
    candles: int = Field(default=500, ge=100, le=2000)
    initialCapital: float = Field(default=100000, gt=0)
    riskPerTrade: float = Field(default=0.02, ge=0.0, le=1.0)


def create_backtest_tearsheet_router():
    router = APIRouter()

    @router.post("/pro/backtest/tearsheet")
    def tearsheet(req: TearsheetRequest):
        try:
            result = run_backtest(req.model_dump())
            return build_tearsheet(result)
        except Exception as exc:  # noqa: BLE001 - defensive, engine never raises
            logger.warn(f"pro/backtest/tearsheet failed: {exc}")
            return {"status": "degraded", "error": str(exc)}

    return router

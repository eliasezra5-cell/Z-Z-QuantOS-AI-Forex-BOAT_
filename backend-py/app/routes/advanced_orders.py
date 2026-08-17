"""Advanced Order Types + Pre-Trade Checks router (additive, PRO).

Mounted at ``/api/pro/advanced-orders``:

  - ``GET  /capabilities``  supported order types + time-in-force + config
  - ``POST /check``         dry-run the full pre-trade checklist (never places)
  - ``POST /place``         run the checklist, then place (market / limit /
                            stop-market / stop-limit / bracket; OCO places its
                            legs together with a shared ocoId)

Every path fails safe: a rejected checklist returns HTTP 200 with
``{"status": "rejected", ...}`` (never a crash), and placement always passes
through the MT5 adapter's ``placeOrder`` so the existing fail-closed trading
engine gates still apply on top of the new checklist.
"""
import time
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..foundation.logger import logger
from ..modules.mt5.adapter import init_mt5
from ..modules.risk.pretrade_checks import (
    run_pretrade_checks,
    supported_capabilities,
)


class OcoLeg(BaseModel):
    side: str
    volume: float = Field(default=0.1)
    type: str = Field(default="limit")
    price: float | None = None
    stopLoss: float | None = None
    takeProfit: float | None = None


class AdvancedOrderRequest(BaseModel):
    symbol: str
    side: str
    type: str = Field(default="market")
    volume: float = Field(default=0.1)
    price: float | None = None
    stopLoss: float | None = None
    takeProfit: float | None = None
    timeInForce: str | None = None
    comment: str = "advanced-order"
    oco: list[OcoLeg] | None = None


def _to_order(req: AdvancedOrderRequest) -> dict:
    order = {
        "symbol": str(req.symbol).upper(),
        "side": str(req.side).lower(),
        "type": str(req.type).lower(),
        "volume": float(req.volume),
        "comment": req.comment,
        "source": "pro-advanced-orders",
    }
    if req.price is not None:
        order["price"] = float(req.price)
    if req.stopLoss is not None:
        order["stopLoss"] = float(req.stopLoss)
    if req.takeProfit is not None:
        order["takeProfit"] = float(req.takeProfit)
    if req.timeInForce:
        order["timeInForce"] = str(req.timeInForce).upper()
    return order


def _leg_to_order(req: AdvancedOrderRequest, leg: OcoLeg) -> dict:
    return {
        "symbol": str(req.symbol).upper(),
        "side": str(leg.side).lower(),
        "type": str(leg.type).lower(),
        "volume": float(leg.volume),
        "comment": f"{req.comment}-oco",
        "source": "pro-advanced-orders",
        **({"price": float(leg.price)} if leg.price is not None else {}),
        **({"stopLoss": float(leg.stopLoss)} if leg.stopLoss is not None else {}),
        **({"takeProfit": float(leg.takeProfit)} if leg.takeProfit is not None else {}),
        **({"timeInForce": str(req.timeInForce).upper()} if req.timeInForce else {}),
    }


def create_advanced_orders_router():
    router = APIRouter()

    @router.get("/pro/advanced-orders/capabilities")
    def capabilities():
        try:
            return {"status": "ok", **supported_capabilities()}
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.warn(f"advanced-orders/capabilities failed: {exc}")
            return {"status": "degraded", "error": str(exc)}

    @router.post("/pro/advanced-orders/check")
    def check(req: AdvancedOrderRequest):
        try:
            order = _to_order(req)
            legs = [_leg_to_order(req, leg) for leg in (req.oco or [])]
            result = run_pretrade_checks(order)
            if legs:
                result["legs"] = [run_pretrade_checks(leg) for leg in legs]
                result["legViolations"] = [
                    v for r in result["legs"] for v in r["violations"]
                ]
                if result["legViolations"]:
                    result["approved"] = False
                    result["status"] = "rejected"
                    result["violations"] = list(result["violations"]) + result["legViolations"]
            return result
        except Exception as exc:  # noqa: BLE001 - defensive, engine never raises
            logger.warn(f"advanced-orders/check failed: {exc}")
            return {"status": "rejected", "error": str(exc)}

    @router.post("/pro/advanced-orders/place")
    async def place(req: AdvancedOrderRequest):
        try:
            mt5 = init_mt5()
            order = _to_order(req)
            result = run_pretrade_checks(order)
            legs = [_leg_to_order(req, leg) for leg in (req.oco or [])]
            leg_results = [run_pretrade_checks(leg) for leg in legs]
            if result["status"] != "approved" or any(r["status"] != "approved" for r in leg_results):
                return {
                    "status": "rejected",
                    "reason": "pre-trade checks failed",
                    "pretrade": result,
                    "legs": leg_results,
                }

            oco_id = f"oco-{uuid.uuid4().hex[:12]}" if legs else None
            placed = []
            primary = await mt5["placeOrder"](order)
            placed.append({"kind": "primary", "order": order, "result": primary})
            for leg in legs:
                leg["ocoId"] = oco_id
                leg_result = await mt5["placeOrder"](leg)
                placed.append({"kind": "oco-leg", "order": leg, "result": leg_result})

            return {
                "status": "placed",
                "pretrade": result,
                "ocoId": oco_id,
                "placed": placed,
                "timestamp": int(time.time() * 1000),
            }
        except Exception as exc:  # noqa: BLE001 - placement failure is surfaced, never a 500 crash
            logger.warn(f"advanced-orders/place failed: {exc}")
            return {"status": "error", "error": str(exc)}

    return router

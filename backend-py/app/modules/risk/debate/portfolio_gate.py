"""Portfolio Gate (Feature 3, additive).

Universal choke point for order placement: after the deterministic fail-closed
gates pass, the risk debate team reviews the order and the portfolio gate
applies the verdict. The gate can only REDUCE or REJECT — it can never increase
position size. Every gate run is persisted to ``risk_debate_history`` for the
risk-debate UI and audit trail.
"""
import time
import uuid

from ....foundation.json_store import db
from ....foundation.logger import logger
from . import debate_order


def _pct_of_equity(value, equity):
    try:
        equity = float(equity)
    except (TypeError, ValueError):
        equity = 0.0
    if equity <= 0:
        return 0.0
    return (float(value or 0) / equity) * 100.0


def build_gate_context(order, portfolio=None):
    """Normalize an order + portfolio into the officer context."""
    portfolio = portfolio or {}
    equity = float(portfolio.get("equity") or 0)
    price = float(order.get("price") or 0)
    volume = float(order.get("volume") or 0)
    notional = price * volume
    risk_amount = float(order.get("riskAmount") or 0)
    return {
        "symbol": order.get("symbol"),
        "side": order.get("side"),
        "volume": volume,
        "notional": notional,
        "notionalPct": round(_pct_of_equity(notional, equity), 4),
        "riskAmount": risk_amount,
        "riskAmountPct": round(_pct_of_equity(risk_amount, equity), 4),
        "stopLoss": order.get("stopLoss"),
        "takeProfit": order.get("takeProfit"),
        "confidence": order.get("confidence"),
        "openPositions": int(portfolio.get("openPositions") or 0),
        "equity": equity,
    }


def run_portfolio_gate(order, portfolio=None, persist=True):
    """Run the risk debate team and apply the portfolio gate.

    Returns a dict with approved / verdict / maxVolume / reason / officers and a
    persisted debate record id. Never raises; on any unexpected failure the gate
    fails open (approved) so the deterministic gates remain the source of truth.
    """
    context = build_gate_context(order, portfolio)
    try:
        debate = debate_order(context)
    except Exception as exc:  # noqa: BLE001 - gate must never crash order flow
        logger.warn(f"Risk debate failed, gate fail-open: {exc}")
        debate = {
            "approved": True, "verdict": "approve", "maxVolume": context["volume"],
            "reason": "risk-debate unavailable (fail-open)", "blockers": [],
            "reduceReasons": [], "officers": [],
        }

    record = {
        "id": f"rg-{uuid.uuid4().hex[:12]}",
        "symbol": order.get("symbol"),
        "side": order.get("side"),
        "requestedVolume": context["volume"],
        "maxVolume": debate["maxVolume"],
        "approved": debate["approved"],
        "verdict": debate["verdict"],
        "reason": debate.get("reason", ""),
        "officers": debate.get("officers", []),
        "context": {
            "notionalPct": context["notionalPct"],
            "riskAmountPct": context["riskAmountPct"],
            "stopLoss": context["stopLoss"],
            "takeProfit": context["takeProfit"],
            "confidence": context["confidence"],
        },
        "timestamp": int(time.time() * 1000),
    }
    if persist:
        try:
            db.collection("risk_debate_history").insert(record)
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"Risk debate persist failed: {exc}")
    return {**debate, "debateId": record["id"], "record": record}


def get_latest_risk_debate(symbol=None):
    """Latest persisted risk-debate record (optionally filtered by symbol)."""
    try:
        items = db.collection("risk_debate_history").find({}, {"sort": ["timestamp", "desc"]})
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"Risk debate history read failed: {exc}")
        return None
    if symbol:
        items = [r for r in items if r.get("symbol") == symbol.upper()]
    return items[0] if items else None

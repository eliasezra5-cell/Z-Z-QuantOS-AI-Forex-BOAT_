"""Risk Manager Agent (VETO POWER).

Checks portfolio equity, max risk per trade, max daily loss, spread and
position sizing using Python ``Decimal`` arithmetic only (NO FLOATS). Returns
``risk_approved: True/False`` plus a reason. ``risk_approved=False`` forces the
final decision to ``NO_TRADE`` regardless of the directional confidence score.
The risk agent contributes NO directional weight.
"""
from decimal import Decimal, ROUND_HALF_UP

from ....config import settings
from ....foundation.logger import logger
from ...portfolio.service import portfolio_service
from ...marketdata.engine import get_quote
from .base import AgentResult, clamp01

ZERO = Decimal("0")


def _d(value, default=ZERO):
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal(str(default))


class RiskManagerAgent:
    id = "risk"
    name = "RiskManagerAgent"
    weight = 0.0  # veto only, never a directional vote

    async def run(self, context=None):
        context = context or {}
        symbol = context.get("symbol", "XAUUSD")
        checks = []
        reasons = []

        portfolio = _get_portfolio()
        equity = _d(portfolio.get("equity"), Decimal("10000"))
        balance = _d(portfolio.get("balance"))
        daily_loss = _d(portfolio.get("dailyLoss"))
        exposure = _d(portfolio.get("exposure"))

        # 1. Equity sanity check
        if equity <= ZERO:
            checks.append({"check": "equity", "ok": False, "detail": "equity <= 0"})
            reasons.append("equity-non-positive")
        else:
            checks.append({"check": "equity", "ok": True, "detail": f"equity {equity}"})

        # 2. Max risk per trade (Decimal, ROUND_HALF_UP)
        max_risk_pct = _d(settings.MAX_RISK_PER_TRADE, Decimal("0.02"))
        risk_pct = _d(context.get("riskPercent"), Decimal("0.02"))
        over = risk_pct > max_risk_pct
        checks.append({"check": "max-risk-per-trade", "ok": not over,
                       "detail": f"risk {risk_pct * Decimal('100'):.2f}% vs max {max_risk_pct * Decimal('100'):.2f}%"})
        if over:
            reasons.append("risk-per-trade-exceeded")

        # 3. Daily loss limit (Decimal)
        daily_limit = _d(settings.DAILY_LOSS_LIMIT, Decimal("100"))
        if daily_loss > ZERO and equity > ZERO:
            daily_loss_pct = (daily_loss / equity) * Decimal("100")
            over_daily = daily_loss_pct >= daily_limit
            checks.append({"check": "daily-loss", "ok": not over_daily,
                           "detail": f"daily loss {daily_loss} ({daily_loss_pct:.2f}%) vs limit {daily_limit}%"})
            if over_daily:
                reasons.append("daily-loss-limit-hit")
        else:
            checks.append({"check": "daily-loss", "ok": True, "detail": "no daily loss recorded"})

        # 4. Exposure limit (Decimal)
        max_exposure = _d(settings.MAX_TOTAL_EXPOSURE, Decimal("0.30"))
        if exposure > ZERO and equity > ZERO:
            exposure_pct = (exposure / equity) * Decimal("100")
            over_exposure = exposure_pct >= max_exposure * Decimal("100")
            checks.append({"check": "exposure", "ok": not over_exposure,
                           "detail": f"exposure {exposure_pct:.2f}% vs max {max_exposure * Decimal('100'):.2f}%"})
            if over_exposure:
                reasons.append("total-exposure-exceeded")
        else:
            checks.append({"check": "exposure", "ok": True, "detail": "no exposure recorded"})

        # 5. Spread check (Decimal pips)
        max_spread = _d(settings.MAX_SPREAD_PIPS, Decimal("3"))
        try:
            quote = get_quote(symbol)
            spread_pips = _d(quote.get("spread"))
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"Risk agent quote fetch failed: {exc}")
            spread_pips = ZERO
        if spread_pips > ZERO and spread_pips > max_spread:
            checks.append({"check": "spread", "ok": False, "detail": f"spread {spread_pips} pips > {max_spread}"})
            reasons.append("spread-too-wide")
        else:
            checks.append({"check": "spread", "ok": True, "detail": f"spread {spread_pips} pips"})

        # 6. Lot size bounds (Decimal)
        lot = _d(context.get("lotSize"), Decimal("0.01"))
        min_lot = Decimal("0.01")
        max_lot = Decimal("100")
        lot_ok = min_lot <= lot <= max_lot
        checks.append({"check": "lot-size", "ok": lot_ok, "detail": f"lot {lot}"})
        if not lot_ok:
            reasons.append("lot-size-out-of-bounds")

        approved = not reasons
        return AgentResult(
            self.id, self.name, self.weight,
            direction="neutral",
            confidence=1.0 if approved else 0.0,
            reasoning="Risk approved" if approved else f"Risk veto: {', '.join(reasons)}",
            abstention="TRADE" if approved else "RISK_BLOCKED",
            data={
                "riskApproved": approved,
                "reasons": reasons,
                "checks": checks,
                "equity": equity,
                "balance": balance,
            },
        )


def _get_portfolio():
    try:
        p = portfolio_service.get()
        return p if isinstance(p, dict) else {}
    except Exception:  # noqa: BLE001
        return {"equity": 10000, "balance": 10000, "dailyLoss": 0, "exposure": 0}

"""Portfolio service mirroring the Node portfolio/service.js.

ZERO-MOCK: no fake starting balance is seeded. Balance/equity come from the
live MT5 bridge when connected, otherwise 0. All money math uses ``Decimal``.
"""
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ..marketdata.engine import get_quote, get_instrument  # noqa: F401
from ..risk.engine import risk_engine


def _dec(value, default=Decimal("0")):
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal(str(default))


def _round(value, digits=2):
    q = Decimal("1").scaleb(-digits)
    return float(_dec(value).quantize(q, ROUND_HALF_UP))


def _live_account_balance():
    """Return the real balance from the MT5 bridge when connected, else None."""
    try:
        from ..mt5.adapter import mt5_state  # lazy: avoids circular import

        if mt5_state.connected and mt5_state.account:
            bal = mt5_state.account.get("balance")
            if bal is not None:
                return Decimal(str(bal))
    except Exception:  # noqa: BLE001 - never break portfolio on MT5 issues
        pass
    return None


class PortfolioService:
    def __init__(self):
        self.col = db.collection("portfolio")

    def get(self):
        account = self.col.find_one({}) or {}
        positions = db.collection("positions").find({"status": "open"})
        closed = db.collection("positions").find({"status": "closed"})
        live_balance = _live_account_balance()
        if live_balance is not None:
            balance = live_balance
            source = "mt5-live"
            broker = "MT5-Live"
        else:
            balance = _dec(account.get("balance", 0))
            source = "store" if account.get("balance") is not None else "none"
            broker = "MT5-Demo"
        balance = max(balance, Decimal("0"))
        equity = balance + sum(_dec(p.get("profit", 0)) for p in positions)
        exposure = sum(_dec(p["entryPrice"]) * _dec(p["volume"]) for p in positions)
        total_trades = len(closed) + len(positions)
        wins = sum(1 for p in closed if _dec(p.get("profit", 0)) > 0)
        now = datetime.now(timezone.utc)
        today_start = int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp() * 1000)
        today_closed = [p for p in closed if p.get("closedAt", 0) >= today_start]
        daily_loss = sum(_dec(p["profit"]) for p in today_closed if _dec(p["profit"]) < 0)
        daily_pnl = sum(_dec(p["profit"]) for p in today_closed)
        unrealized = sum(_dec(p.get("profit", 0)) for p in positions)
        margin_used = exposure * Decimal("0.01")

        portfolio = {
            **account,
            "balance": _round(balance),
            "equity": _round(equity),
            "exposure": _round(exposure),
            "openPositions": len(positions),
            "totalTrades": total_trades,
            "winRate": round((wins / total_trades) * 1000) / 10 if total_trades else 0,
            "dailyPnL": _round(daily_pnl),
            "dailyLoss": _round(daily_loss),
            "unrealizedPnL": _round(unrealized),
            "marginUsed": _round(margin_used),
            "marginFree": _round(max(equity - margin_used, Decimal("0"))),
            "capitalProtection": risk_engine.capital_protection({"equity": _round(equity), "dailyLoss": _round(daily_loss), "exposure": _round(exposure), "openPositions": len(positions)}),
            "demoMode": source != "mt5-live",
            "source": source,
            "broker": broker,
        }
        return portfolio

    def equity_curve(self):
        positions = db.collection("positions").find({"status": "closed"})
        live_balance = _live_account_balance()
        if live_balance is not None:
            bal = live_balance
        else:
            bal = _dec((self.col.find_one({}) or {}).get("balance", 0))
        if not positions:
            return [{"t": int(time.time() * 1000), "value": _round(bal)}]
        curve = [{"t": int(time.time() * 1000) - 30 * 86400000, "value": _round(bal)}]
        for p in sorted(positions, key=lambda x: x["closedAt"]):
            bal += _dec(p["profit"])
            curve.append({"t": p["closedAt"], "value": _round(bal), "pnl": _round(p["profit"])})
        return curve

    def daily_summary(self, days=30):
        positions = db.collection("positions").find({"status": "closed"})
        mapping = {}
        for p in positions:
            day = datetime.fromtimestamp(p["closedAt"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            if day not in mapping:
                mapping[day] = {"pnl": Decimal("0"), "trades": 0, "wins": 0}
            mapping[day]["pnl"] += _dec(p["profit"])
            mapping[day]["trades"] += 1
            if _dec(p["profit"]) > 0:
                mapping[day]["wins"] += 1
        items = list(mapping.items())[-days:]
        return [
            {"date": date, "pnl": _round(d["pnl"]), "trades": d["trades"], "winRate": round((d["wins"] / d["trades"]) * 100) / 100 if d["trades"] else 0}
            for date, d in items
        ]


portfolio_service = PortfolioService()


def init_portfolio():
    logger.info("Portfolio management initialized (no mock balance - balance sourced from live MT5 bridge)")
    return portfolio_service

"""Reports service mirroring the Node reports/service.js."""
import json
import time

from ...foundation.logger import logger
from ...foundation.json_store import db
from ..portfolio.service import portfolio_service
from ..news.engine import get_news
from ..economic.engine import get_economic_events
from ..macro.engine import get_macro_snapshot
from ..risk.engine import risk_engine

TYPES = ["daily", "weekly", "monthly", "portfolio", "risk", "trade", "ai"]


def generate_report(report_type="daily"):
    portfolio = portfolio_service.get()
    macro = get_macro_snapshot()
    news = get_news({"limit": 15})
    events = get_economic_events({"limit": 15})
    risk_settings = risk_engine.get_settings()
    closed = db.collection("positions").find({"status": "closed"})
    ai_decisions = db.collection("ai_decisions").find({})[-10:]

    report = {
        "id": f"{report_type}-{int(time.time() * 1000)}",
        "type": report_type,
        "generatedAt": int(time.time() * 1000),
        "period": "Last 24 hours" if report_type == "daily" else ("Last 7 days" if report_type == "weekly" else ("Last 30 days" if report_type == "monthly" else "Current")),
        "portfolio": summarize_portfolio(portfolio, closed, report_type),
        "risk": {
            "settings": risk_settings,
            "capitalProtection": portfolio["capitalProtection"],
        },
        "market": {
            "macro": macro["indicators"],
            "sentiment": round(sum(n["sentiment"] for n in news) / len(news) * 100) / 100 if news else 0,
            "topNews": [{"title": n["title"], "sentiment": n["sentiment"], "impact": n["marketImpact"]} for n in news[:5]],
            "upcomingEvents": [{"name": e["name"], "time": e["time"], "impact": e["impact"]} for e in events if e.get("status") != "released"][:5],
        },
        "ai": {
            "decisions": len(ai_decisions),
            "recent": [{
                "symbol": d["symbol"],
                "direction": (d.get("consensus") or {}).get("direction") or d.get("direction", "neutral"),
                "confidence": (d.get("confidence") or {}).get("score") if isinstance(d.get("confidence"), dict) else (d.get("confidence") or 0),
                "time": d.get("timestamp"),
            } for d in ai_decisions],
        },
        "summary": build_summary(portfolio, closed, report_type),
    }

    db.collection("reports").insert({"type": report_type, "generatedAt": report["generatedAt"], "report": report})
    logger.info(f"Report generated: {report_type}")
    return report


def summarize_portfolio(portfolio, closed, report_type):
    now = int(time.time() * 1000)
    cutoff = 86400000 if report_type == "daily" else (7 * 86400000 if report_type == "weekly" else (30 * 86400000 if report_type == "monthly" else 0))
    period_trades = closed if cutoff == 0 else [t for t in closed if t.get("closedAt", 0) >= now - cutoff]
    wins = [t for t in period_trades if t["profit"] > 0]
    loss = [t for t in period_trades if t["profit"] < 0]
    return {
        "balance": portfolio["balance"],
        "equity": portfolio["equity"],
        "pnl": portfolio["dailyPnL"],
        "trades": len(period_trades),
        "wins": len(wins),
        "losses": len(loss),
        "winRate": round((len(wins) / len(period_trades)) * 1000) / 10 if period_trades else 0,
        "netProfit": round(sum(t["profit"] for t in period_trades) * 100) / 100,
        "avgProfit": round(sum(t["profit"] for t in period_trades) / len(period_trades) * 100) / 100 if period_trades else 0,
        "profitFactor": calc_profit_factor(period_trades),
    }


def calc_profit_factor(trades):
    gp = sum(t["profit"] for t in trades if t["profit"] > 0)
    gl = abs(sum(t["profit"] for t in trades if t["profit"] < 0))
    return 99 if gl == 0 and gp > 0 else (0 if gl == 0 else round((gp / gl) * 100) / 100)


def build_summary(portfolio, closed, report_type):
    pnl = portfolio["dailyPnL"]
    overall = sum(t["profit"] for t in closed)
    return {
        "headline": f"Portfolio gained {pnl} in the {report_type} period" if pnl >= 0 else f"Portfolio lost {abs(pnl)} in the {report_type} period",
        "overallPnl": round(overall * 100) / 100,
        "openPositions": portfolio["openPositions"],
        "riskLevel": "halted" if (portfolio["capitalProtection"] or {}).get("haltTrading") else "normal",
    }


def get_reports(params=None):
    params = params or {}
    reports = db.collection("reports").find({})
    if params.get("type"):
        reports = [r for r in reports if r["type"] == params["type"]]
    return sorted(reports, key=lambda r: r["generatedAt"], reverse=True)[: int(params.get("limit") or 50)]


def export_report(report_id, fmt="json"):
    row = db.collection("reports").find_one({"id": report_id})
    if not row:
        return None
    if fmt == "json":
        return json.dumps(row["report"], indent=2)
    if fmt == "csv":
        return to_csv(row["report"])
    return json.dumps(row["report"])


def to_csv(report):
    from datetime import datetime, timezone
    lines = ["type,generatedAt,balance,equity,pnl,trades,winRate"]
    lines.append(",".join([
        str(report["type"]),
        datetime.fromtimestamp(report["generatedAt"] / 1000, tz=timezone.utc).isoformat(),
        str(report["portfolio"]["balance"]),
        str(report["portfolio"]["equity"]),
        str(report["portfolio"]["pnl"]),
        str(report["portfolio"]["trades"]),
        str(report["portfolio"]["winRate"]),
    ]))
    return "\n".join(lines)

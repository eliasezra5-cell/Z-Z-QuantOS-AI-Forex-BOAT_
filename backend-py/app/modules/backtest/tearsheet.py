"""Backtest Tearsheet Engine (additive, PRO).

Computes an institutional-style tearsheet from an existing ``run_backtest``
result — no new backtest loop, no model downloads, pure analytics on the shape
``engine.summarize`` already produces:

  - Performance: CAGR, Sharpe, Sortino, Calmar, annualized volatility
  - Drawdown series + max drawdown
  - Monthly returns table (equity curve grouped by calendar month)
  - Trade distribution stats: avg win / avg loss, expectancy, largest
    win/loss, win/loss streak, profit factor (computed from the trade list
    available on the result — ``summarize`` keeps the last 50)

Everything is defensive: a malformed or empty result yields clean zeros / empty
series rather than a crash, so a tearsheet can be rendered for any run that
``run_backtest`` returns.
"""
import math
from datetime import datetime, timezone

from ...foundation.logger import logger

TRADING_DAYS_PER_YEAR = 252
MS_PER_DAY = 86400000.0
MS_PER_YEAR = 365.25 * MS_PER_DAY


def _f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _periods_per_year(timeframe):
    mult = {"M15": 96, "M30": 48, "H1": 24, "H4": 6, "D1": 1, "W1": 1 / 5}
    return mult.get(str(timeframe or "H1").upper(), 24) * TRADING_DAYS_PER_YEAR


def _years_from_curve(equity, timeframe, count):
    if len(equity) >= 2:
        t0 = _f(equity[0].get("t"))
        t1 = _f(equity[-1].get("t"))
        span_ms = t1 - t0
        if span_ms > 0:
            return span_ms / MS_PER_YEAR
    tf_ms = {"M15": 15 * 60000, "M30": 30 * 60000, "H1": 3600000, "H4": 4 * 3600000, "D1": MS_PER_DAY}.get(
        str(timeframe or "H1").upper(), 3600000
    )
    count = max(int(count or 500), 2)
    return max((count - 1) * tf_ms, 1) / MS_PER_YEAR


def _equity_returns(equity):
    values = [_f(p.get("value")) for p in equity if isinstance(p, dict)]
    values = [v for v in values if v > 0]
    if len(values) < 2:
        return values, []
    returns = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev > 0:
            returns.append((values[i] - prev) / prev)
    return values, returns


def _drawdown_series(equity):
    values = [_f(p.get("value")) for p in equity if isinstance(p, dict)]
    values = [v for v in values if v > 0]
    series = []
    peak = 0.0
    max_dd = 0.0
    for i, v in enumerate(values):
        peak = max(peak, v)
        dd = ((peak - v) / peak) * 100 if peak > 0 else 0.0
        series.append({
            "t": _f(equity[i].get("t")) if i < len(equity) else None,
            "index": i,
            "value": round(v, 2),
            "drawdownPct": round(dd, 2),
        })
        max_dd = max(max_dd, dd)
    return series, max_dd


def _monthly_returns(equity):
    values = [{"t": _f(p.get("t")), "value": _f(p.get("value"))} for p in equity if isinstance(p, dict)]
    values = [v for v in values if v["value"] > 0]
    if not values:
        return []
    first = min(v["t"] for v in values if v["t"])
    last = max(v["t"] for v in values if v["t"])
    if not first or not last or last <= first:
        return []
    by_month = {}
    for v in values:
        if not v["t"]:
            continue
        dt = datetime.fromtimestamp(v["t"] / 1000.0, tz=timezone.utc)
        key = f"{dt.year:04d}-{dt.month:02d}"
        by_month.setdefault(key, []).append(v)
    months = sorted(by_month)
    out = []
    prev_last = None
    for key in months:
        pts = by_month[key]
        month_start = pts[0]["value"]
        month_end = pts[-1]["value"]
        if prev_last is not None and prev_last > 0:
            ret_pct = (month_start - prev_last) / prev_last * 100
        else:
            ret_pct = (month_end - month_start) / month_start * 100 if month_start > 0 else 0.0
        out.append({
            "month": key,
            "startEquity": round(month_start, 2),
            "endEquity": round(month_end, 2),
            "returnPct": round(ret_pct, 2),
        })
        prev_last = month_end
    return out


def _trade_stats(trades):
    trades = [t for t in (trades or []) if isinstance(t, dict)]
    profits = [_f(t.get("profit")) for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    longest_win = longest_loss = 0
    cur_win = cur_loss = 0
    for p in profits:
        if p > 0:
            cur_win += 1
            cur_loss = 0
            longest_win = max(longest_win, cur_win)
        elif p < 0:
            cur_loss += 1
            cur_win = 0
            longest_loss = max(longest_loss, cur_loss)
        else:
            cur_win = cur_loss = 0

    reasons = {}
    for t in trades:
        r = str(t.get("reason") or "unknown")
        reasons.setdefault(r, {"count": 0, "netProfit": 0.0, "avgProfit": 0.0})
        reasons[r]["count"] += 1
        reasons[r]["netProfit"] = round(reasons[r]["netProfit"] + _f(t.get("profit")), 2)
        reasons[r]["avgProfit"] = round(reasons[r]["netProfit"] / reasons[r]["count"], 2)

    return {
        "totalTrades": len(trades),
        "winRate": (len(wins) / len(trades)) * 100 if trades else 0.0,
        "profitFactor": round(pf, 2),
        "avgWin": round(avg_win, 2),
        "avgLoss": round(avg_loss, 2),
        "expectancy": round(sum(profits) / len(profits), 2) if profits else 0.0,
        "largestWin": round(max(wins), 2) if wins else 0.0,
        "largestLoss": round(min(losses), 2) if losses else 0.0,
        "longestWinStreak": longest_win,
        "longestLossStreak": longest_loss,
        "byReason": reasons,
    }


def build_tearsheet(result):
    """Build the full tearsheet. Never raises; clean zeros on malformed input."""
    result = result or {}
    try:
        summary = {
            "symbol": result.get("symbol") or "EURUSD",
            "strategy": result.get("strategy") or "trend-follow",
            "timeframe": result.get("timeframe") or "H1",
            "initialCapital": _f(result.get("initialCapital"), 100000),
            "finalCapital": _f(result.get("finalCapital")),
            "netProfit": _f(result.get("netProfit")),
            "returnPct": _f(result.get("returnPct")),
            "totalTrades": int(result.get("totalTrades") or 0),
            "winRate": _f(result.get("winRate")),
            "profitFactor": _f(result.get("profitFactor")),
            "maxDrawdown": _f(result.get("maxDrawdown")),
            "avgTrade": _f(result.get("avgTrade")),
        }
        equity = result.get("equityCurve") or []
        trades = result.get("trades") or []
        timeframe = summary["timeframe"]
        count = len(equity) or 500

        years = _years_from_curve(equity, timeframe, count)
        values, returns = _equity_returns(equity)
        ppy = _periods_per_year(timeframe)

        initial = summary["initialCapital"] or 100000
        final = summary["finalCapital"] or initial
        cagr = 0.0
        if years > 0 and initial > 0 and final > 0:
            cagr = (math.pow(final / initial, 1.0 / years) - 1.0) * 100

        vol_annual = 0.0
        sharpe = 0.0
        sortino = 0.0
        if returns:
            mean = sum(returns) / len(returns)
            var = sum((r - mean) ** 2 for r in returns) / len(returns)
            std = math.sqrt(var) if var > 0 else 0.0
            vol_annual = std * math.sqrt(ppy) * 100
            if std > 0:
                sharpe = (mean / std) * math.sqrt(ppy)
                downside = [r for r in returns if r < 0]
                if downside:
                    dvar = sum(r * r for r in downside) / len(downside)
                    dstd = math.sqrt(dvar)
                    if dstd > 0:
                        sortino = (mean / dstd) * math.sqrt(ppy)

        drawdown_series, max_dd = _drawdown_series(equity)
        calmar = (cagr / max_dd) if max_dd > 0 else 0.0
        monthly = _monthly_returns(equity)
        trade_stats = _trade_stats(trades)

        return {
            "status": "ok",
            "summary": summary,
            "performance": {
                "cagrPct": round(cagr, 2),
                "sharpe": round(sharpe, 2),
                "sortino": round(sortino, 2),
                "calmar": round(calmar, 2),
                "volatilityPct": round(vol_annual, 2),
                "maxDrawdownPct": round(max_dd, 2),
                "periodsPerYear": int(ppy),
            },
            "monthlyReturns": monthly,
            "drawdownSeries": drawdown_series,
            "tradeStats": trade_stats,
            "timestamp": int(__import__("time").time() * 1000),
        }
    except Exception as exc:  # noqa: BLE001 - tearsheet must degrade, never crash
        logger.warn(f"tearsheet build failed: {exc}")
        return {"status": "degraded", "error": str(exc), "summary": {}, "performance": {}}

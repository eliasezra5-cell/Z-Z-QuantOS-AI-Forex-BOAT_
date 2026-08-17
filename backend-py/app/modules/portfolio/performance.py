"""Performance Analytics (Batch 19).

Win rate, profit factor, Sharpe, Sortino, Calmar, expectancy, max drawdown,
recovery factor. Time analytics (by hour/day/month/session), category
analytics (news category, confidence range, direction, instrument, source
tier), AI performance (accuracy, calibration, agent accuracy, false
positives, missed opportunities). Filter by source AI News vs External Algo.
"""
import math
import time

from ...foundation.json_store import db


def _returns(equity_curve):
    out = []
    prev = None
    for e in equity_curve:
        v = e.get("value") if isinstance(e, dict) else e
        if prev is not None and prev > 0:
            out.append((v - prev) / prev)
        prev = v
    return out


def _stddev(xs):
    if len(xs) < 2:
        return 0.0
    mean = sum(xs) / len(xs)
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1))


def _max_drawdown(equity_curve):
    peak = None
    mdd = 0.0
    for e in equity_curve:
        v = e.get("value") if isinstance(e, dict) else e
        peak = v if peak is None or v > peak else peak
        if peak:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


def calculate_metrics(trades, equity_curve, initial_capital):
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] < 0]
    n = len(trades)
    net = sum(t["profit"] for t in trades)
    gross_profit = sum(t["profit"] for t in wins)
    gross_loss = sum(t["profit"] for t in losses)

    win_rate = (len(wins) / n) if n else 0
    profit_factor = 99 if (gross_loss == 0 and gross_profit > 0) else (0 if gross_loss == 0 else gross_profit / abs(gross_loss))
    expectancy = net / n if n else 0

    rets = _returns(equity_curve)
    period_returns = sum(rets)
    mean_r = sum(rets) / len(rets) if rets else 0
    sd = _stddev(rets)
    sharpe = (mean_r / sd * math.sqrt(252)) if sd > 0 else 0
    downside = [r for r in rets if r < 0]
    dsd = _stddev(downside)
    sortino = (mean_r / dsd * math.sqrt(252)) if dsd > 0 else 0

    mdd = _max_drawdown(equity_curve)
    calmar = (period_returns / mdd) if mdd > 0 else 0
    recovery_factor = (abs(net) / mdd) if mdd > 0 else 0

    return {
        "total_trades": n,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "expectancy": round(expectancy, 4),
        "max_drawdown": round(mdd, 4),
        "recovery_factor": round(recovery_factor, 4),
        "net_profit": round(net, 2),
        "avg_win": round(gross_profit / len(wins), 2) if wins else 0,
        "avg_loss": round(gross_loss / len(losses), 2) if losses else 0,
    }


class PerformanceAnalytics:
    def __init__(self):
        self.col = db.collection("performance")

    def compute(self, source=None):
        trades = db.collection("positions").find({"status": "closed"})
        if source:
            trades = [t for t in trades if t.get("source") == source]
        equity = db.collection("portfolio_equity_curve").find({})
        if not equity:
            balance = db.collection("portfolio").find({}) or [{"balance": 100000}]
            equity = [{"value": balance[0].get("balance", 100000)}]
        metrics = calculate_metrics(trades, equity, 100000)
        metrics["source"] = source or "all"
        metrics["trades"] = len(trades)
        metrics["computedAt"] = int(time.time() * 1000)
        return metrics

    def time_analytics(self, source=None):
        trades = db.collection("positions").find({"status": "closed"})
        if source:
            trades = [t for t in trades if t.get("source") == source]
        by_hour = {}
        by_day = {}
        by_month = {}
        by_session = {}
        for t in trades:
            ts = t.get("openedAt") or 0
            import datetime
            dt = datetime.datetime.fromtimestamp(ts / 1000, tz=datetime.timezone.utc)
            by_hour.setdefault(dt.hour, []).append(t["profit"])
            by_day.setdefault(dt.strftime("%A"), []).append(t["profit"])
            by_month.setdefault(dt.strftime("%Y-%m"), []).append(t["profit"])
            hour = dt.hour
            if 0 <= hour < 8:
                sess = "asia"
            elif 8 <= hour < 13:
                sess = "london"
            else:
                sess = "newyork"
            by_session.setdefault(sess, []).append(t["profit"])
        def agg(mapping):
            return {k: {"trades": len(v), "pnl": round(sum(v), 2), "avg": round(sum(v) / len(v), 2) if v else 0} for k, v in sorted(mapping.items(), key=lambda kv: kv[0])}
        return {"by_hour": agg(by_hour), "by_day": agg(by_day), "by_month": agg(by_month), "by_session": agg(by_session)}

    def category_analytics(self):
        trades = db.collection("positions").find({"status": "closed"})
        cats = {}
        for t in trades:
            cat = t.get("newsCategory") or t.get("category") or "other"
            entry = cats.setdefault(cat, {"trades": 0, "pnl": 0.0, "wins": 0})
            entry["trades"] += 1
            entry["pnl"] += t["profit"]
            if t["profit"] > 0:
                entry["wins"] += 1
            entry["win_rate"] = round(entry["wins"] / entry["trades"], 4)
        conf_ranges = {"70-79": [], "80-89": [], "90-100": []}
        for t in trades:
            c = t.get("confidence")
            if c is None:
                continue
            if c < 0.70:
                continue
            elif c < 0.80:
                conf_ranges["70-79"].append(t["profit"])
            elif c < 0.90:
                conf_ranges["80-89"].append(t["profit"])
            else:
                conf_ranges["90-100"].append(t["profit"])
        by_direction = {}
        for t in trades:
            d = t.get("side")
            by_direction.setdefault(d, []).append(t["profit"])
        by_instrument = {}
        for t in trades:
            s = t.get("symbol")
            by_instrument.setdefault(s, []).append(t["profit"])
        def agg(mapping):
            if isinstance(mapping, dict) and all(isinstance(v, list) for v in mapping.values()):
                return {k: {"trades": len(v), "pnl": round(sum(v), 2)} for k, v in mapping.items()}
            return mapping
        return {
            "by_news_category": cats,
            "by_confidence_range": agg(conf_ranges),
            "by_direction": agg(by_direction),
            "by_instrument": agg(by_instrument),
        }

    def ai_performance(self):
        decisions = db.collection("ai_decisions").find({})
        total = 0
        correct = 0
        false_positives = 0
        missed = 0
        by_agent = {}
        for d in decisions:
            total += 1
            direction = (d.get("consensus") or {}).get("direction")
            conf = (d.get("confidence") or {}).get("score", 0)
            outcome = d.get("outcome") or d.get("correct")
            if outcome is True:
                correct += 1
            if direction in ("buy", "sell") and outcome is False:
                false_positives += 1
            if direction == "no_trade" and (d.get("missedTrade")):
                missed += 1
            for a in d.get("agents") or []:
                aid = a.get("id")
                entry = by_agent.setdefault(aid, {"correct": 0, "total": 0})
                entry["total"] += 1
                if a.get("correct") is True:
                    entry["correct"] += 1
        accuracy = correct / total if total else 0
        return {
            "decisions": total,
            "accuracy": round(accuracy, 4),
            "false_positives": false_positives,
            "missed_opportunities": missed,
            "confidence_calibration": self._calibration(decisions),
            "agent_accuracy": {k: round(v["correct"] / v["total"], 4) if v["total"] else 0 for k, v in by_agent.items()},
        }

    @staticmethod
    def _calibration(decisions):
        buckets = {"0.5-0.7": {"n": 0, "correct": 0}, "0.7-0.9": {"n": 0, "correct": 0}, "0.9-1.0": {"n": 0, "correct": 0}}
        for d in decisions:
            conf = (d.get("confidence") or {}).get("score", 0)
            if conf < 0.5:
                continue
            bucket = "0.5-0.7" if conf < 0.7 else ("0.7-0.9" if conf < 0.9 else "0.9-1.0")
            buckets[bucket]["n"] += 1
            if d.get("correct") is True:
                buckets[bucket]["correct"] += 1
        out = {}
        for k, v in buckets.items():
            out[k] = {"samples": v["n"], "accuracy": round(v["correct"] / v["n"], 4) if v["n"] else None}
        return out


performance_analytics = PerformanceAnalytics()


def init_performance_analytics():
    from ...foundation.logger import logger
    logger.info("Performance analytics initialized")
    return performance_analytics

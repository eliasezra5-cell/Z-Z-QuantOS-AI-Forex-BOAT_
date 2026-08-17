"""Portfolio Risk Analyzers (Batch 14, additive).

Adds the missing Batch 14 risk analyzers on top of ``risk/engine.py``:

  - Portfolio risk analyzer  : aggregate exposure, concentration, drawdown
  - Correlation analyzer     : cross-symbol exposure concentration
  - Volatility analyzer      : ATR/vol regime scaling for sizing
  - News risk analyzer       : high-impact event exposure and news-derived risk
  - Session risk analyzer    : session liquidity/kill-zone based risk windows

These are additive; ``risk/engine.py``, ``risk/deterministic.py`` and
``risk/capital_protection.py`` are left untouched. Each analyzer returns a
dict with a ``riskLevel`` in {low, medium, high, critical} and ``blocking``
flag so the pipeline can fail-closed without modifying existing gates.
"""
import math
import time

from ...foundation.logger import logger

RISK_LEVELS = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _level_from_score(score):
    if score >= 0.75:
        return "critical", True
    if score >= 0.55:
        return "high", True
    if score >= 0.30:
        return "medium", False
    return "low", False


class PortfolioRiskAnalyzer:
    """Aggregate portfolio risk: exposure, concentration, drawdown, leverage."""

    id = "portfolio"

    def analyze(self, portfolio):
        equity = portfolio.get("equity", 0) or 0
        exposure = portfolio.get("exposure", 0) or 0
        margin = portfolio.get("margin", 0) or 0
        drawdown = portfolio.get("maxDrawdownPct", portfolio.get("drawdownPct", 0)) or 0
        open_positions = portfolio.get("openPositions", 0) or 0
        max_positions = portfolio.get("maxOpenPositions", 10) or 10

        scores = []
        if equity > 0:
            scores.append(exposure / equity)                      # exposure ratio
            scores.append(margin / equity * 2.0 if equity else 0)  # leverage scaled
        scores.append(drawdown / 100.0)
        if open_positions and max_positions:
            scores.append(open_positions / max_positions * 0.5)
        score = min(1.0, sum(scores))
        level, blocking = _level_from_score(score)
        return {
            "analyzer": self.id,
            "riskLevel": level,
            "score": round(score, 4),
            "blocking": blocking,
            "exposure": exposure,
            "marginUsage": round(margin / equity * 100, 2) if equity else 0,
            "drawdownPct": drawdown,
            "openPositions": open_positions,
            "details": "Portfolio aggregate risk assessment",
        }


class CorrelationAnalyzer:
    """Cross-symbol correlation/concentration risk for a proposed trade."""

    id = "correlation"

    CORRELATION_MAP = {
        ("XAUUSD", "EURUSD"): 0.6, ("XAUUSD", "GBPUSD"): 0.55, ("XAUUSD", "USDJPY"): -0.4,
        ("XAUUSD", "US500"): 0.3, ("EURUSD", "GBPUSD"): 0.85, ("EURUSD", "USDJPY"): -0.7,
        ("GBPUSD", "EURUSD"): 0.85, ("USOIL", "XAUUSD"): 0.2, ("US500", "XAUUSD"): 0.3,
    }

    def _correlation(self, a, b):
        if a == b:
            return 1.0
        return self.CORRELATION_MAP.get((a, b)) or self.CORRELATION_MAP.get((b, a)) or 0.0

    def analyze(self, trade, positions):
        symbol = trade.get("symbol")
        weighted = 0.0
        total = 0.0
        correlated_count = 0
        for p in positions or []:
            if p.get("symbol") == symbol:
                continue
            corr = abs(self._correlation(symbol, p.get("symbol")))
            notional = p.get("notional") or 0
            weighted += corr * notional
            total += notional
            if corr > 0.6:
                correlated_count += 1
        score = (weighted / total) if total else 0.0
        score = min(1.0, score + correlated_count * 0.15)
        level, blocking = _level_from_score(score)
        return {
            "analyzer": self.id,
            "riskLevel": level,
            "score": round(score, 4),
            "blocking": blocking,
            "correlatedPositions": correlated_count,
            "details": f"Correlation-weighted exposure {score:.2f} vs correlated positions {correlated_count}",
        }


class VolatilityAnalyzer:
    """Volatility regime scaling for position sizing and risk assessment."""

    id = "volatility"

    def analyze(self, atr_value, atr_percent=None, baseline_atr=None):
        atr = float(atr_value or 0)
        if atr <= 0:
            return {"analyzer": self.id, "riskLevel": "low", "score": 0.0, "blocking": False, "details": "No ATR data"}
        base = float(baseline_atr) if baseline_atr else atr
        ratio = atr / base if base else 1.0
        score = min(1.0, max(0.0, (ratio - 1.0) / 1.0))
        level, blocking = _level_from_score(score)
        return {
            "analyzer": self.id,
            "riskLevel": level,
            "score": round(score, 4),
            "blocking": blocking,
            "atr": round(atr, 4),
            "atrRatio": round(ratio, 3),
            "details": f"Volatility regime ratio {ratio:.2f}x baseline",
        }


class NewsRiskAnalyzer:
    """News-driven risk: imminent high-impact events on correlated symbols."""

    id = "news"

    def analyze(self, symbol, high_impact_events, window_ms=4 * 3600000):
        now = int(time.time() * 1000)
        relevant = 0
        for e in high_impact_events or []:
            if not (now <= (e.get("time") or 0) <= now + window_ms):
                continue
            cur = e.get("currency") or ""
            if cur == "USD" and symbol in ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "US500"):
                relevant += 1
            elif cur == "EUR" and symbol in ("EURUSD",):
                relevant += 1
            elif cur == "JPY" and symbol in ("USDJPY",):
                relevant += 1
            elif cur == "GBP" and symbol in ("GBPUSD",):
                relevant += 1
        score = min(1.0, relevant * 0.3)
        level, blocking = _level_from_score(score)
        return {
            "analyzer": self.id,
            "riskLevel": level,
            "score": round(score, 4),
            "blocking": blocking,
            "relevantEvents": relevant,
            "windowMs": window_ms,
            "details": f"{relevant} high-impact events in window for {symbol}",
        }


class SessionRiskAnalyzer:
    """Session liquidity risk: avoid low-liquidity kill zones for execution."""

    id = "session"

    # (utc_hour_start, utc_hour_end) of active trading sessions.
    HIGH_LIQUIDITY_RANGES = [
        (7, 12),   # London morning
        (12, 17),  # London/NY overlap
    ]
    LOW_LIQUIDITY_RANGES = [
        (0, 6),    # Asia late / Sydney close
        (20, 24),  # post-NY close
    ]

    def session(self, utc_hour):
        for lo, hi in self.HIGH_LIQUIDITY_RANGES:
            if lo <= utc_hour < hi:
                return "high-liquidity"
        for lo, hi in self.LOW_LIQUIDITY_RANGES:
            if lo <= utc_hour < hi:
                return "low-liquidity"
        return "normal"

    def analyze(self, utc_hour=None, symbol="XAUUSD"):
        utc_hour = utc_hour if utc_hour is not None else time.gmtime().tm_hour
        session = self.session(utc_hour)
        if session == "low-liquidity":
            return {"analyzer": self.id, "riskLevel": "high", "score": 0.7, "blocking": True,
                    "session": session, "details": f"Low-liquidity session (UTC {utc_hour:02d}:00) for {symbol}"}
        if session == "normal":
            return {"analyzer": self.id, "riskLevel": "medium", "score": 0.35, "blocking": False,
                    "session": session, "details": f"Normal liquidity session (UTC {utc_hour:02d}:00) for {symbol}"}
        return {"analyzer": self.id, "riskLevel": "low", "score": 0.1, "blocking": False,
                "session": session, "details": f"High-liquidity session (UTC {utc_hour:02d}:00) for {symbol}"}


portfolio_risk_analyzer = PortfolioRiskAnalyzer()
correlation_analyzer = CorrelationAnalyzer()
volatility_analyzer = VolatilityAnalyzer()
news_risk_analyzer = NewsRiskAnalyzer()
session_risk_analyzer = SessionRiskAnalyzer()


def analyze_all(trade, portfolio, positions=None, atr_value=None, high_impact_events=None, utc_hour=None):
    """Run every analyzer and aggregate into one report.

    ``blocking`` is True when any analyzer returns a blocking verdict, so the
    pipeline can fail-closed without touching existing gate code.
    """
    results = {
        "portfolio": portfolio_risk_analyzer.analyze(portfolio),
        "correlation": correlation_analyzer.analyze(trade, positions),
        "volatility": volatility_analyzer.analyze(atr_value),
        "news": news_risk_analyzer.analyze(trade.get("symbol"), high_impact_events),
        "session": session_risk_analyzer.analyze(utc_hour, trade.get("symbol")),
    }
    blocking = any(r["blocking"] for r in results.values())
    worst = max((r["score"] for r in results.values()), default=0.0)
    level, _ = _level_from_score(worst)
    return {
        "riskLevel": level,
        "score": round(worst, 4),
        "blocking": blocking,
        "analyzers": results,
        "timestamp": int(time.time() * 1000),
    }


def init_risk_analyzers():
    logger.info("Portfolio risk analyzers (portfolio/correlation/volatility/news/session) initialized")
    return analyze_all

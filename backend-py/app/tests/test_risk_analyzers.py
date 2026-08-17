"""Unit tests for additive risk analyzers (Batch 14)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test")

from app.modules.risk.analyzers import (  # noqa: E402
    CorrelationAnalyzer,
    NewsRiskAnalyzer,
    PortfolioRiskAnalyzer,
    SessionRiskAnalyzer,
    VolatilityAnalyzer,
    analyze_all,
)


def test_portfolio_low_risk_when_clean():
    out = PortfolioRiskAnalyzer().analyze({"equity": 10000, "exposure": 1000, "margin": 500, "maxDrawdownPct": 3, "openPositions": 1, "maxOpenPositions": 10})
    assert out["riskLevel"] in ("low", "medium")
    assert out["blocking"] is False


def test_portfolio_critical_at_high_exposure():
    out = PortfolioRiskAnalyzer().analyze({"equity": 10000, "exposure": 9000, "margin": 8000, "maxDrawdownPct": 40, "openPositions": 9, "maxOpenPositions": 10})
    assert out["riskLevel"] in ("high", "critical")
    assert out["blocking"] is True


def test_correlation_zero_when_no_positions():
    out = CorrelationAnalyzer().analyze({"symbol": "XAUUSD"}, [])
    assert out["score"] == 0.0
    assert out["blocking"] is False


def test_correlation_detects_correlated_positions():
    out = CorrelationAnalyzer().analyze(
        {"symbol": "EURUSD"},
        [{"symbol": "GBPUSD", "notional": 5000}, {"symbol": "USDJPY", "notional": 5000}],
    )
    assert out["score"] > 0
    assert out["correlatedPositions"] > 0


def test_volatility_normal_regime_low_risk():
    out = VolatilityAnalyzer().analyze(atr_value=5.0, baseline_atr=5.0)
    assert out["riskLevel"] == "low"
    assert out["blocking"] is False


def test_volatility_spike_blocks():
    out = VolatilityAnalyzer().analyze(atr_value=15.0, baseline_atr=5.0)
    assert out["riskLevel"] in ("high", "critical")
    assert out["blocking"] is True


def test_news_risk_no_events_low():
    out = NewsRiskAnalyzer().analyze("XAUUSD", [])
    assert out["riskLevel"] == "low"
    assert out["relevantEvents"] == 0


def test_news_risk_detects_usd_events_for_gold():
    now = int(__import__("time").time() * 1000)
    events = [{"time": now + 3600000, "currency": "USD", "impact": 3}]
    out = NewsRiskAnalyzer().analyze("XAUUSD", events)
    assert out["relevantEvents"] == 1
    assert out["score"] > 0


def test_session_low_liquidity_blocks():
    out = SessionRiskAnalyzer().analyze(utc_hour=3, symbol="XAUUSD")
    assert out["session"] == "low-liquidity"
    assert out["blocking"] is True


def test_session_high_liquidity_ok():
    out = SessionRiskAnalyzer().analyze(utc_hour=9, symbol="XAUUSD")
    assert out["session"] == "high-liquidity"
    assert out["blocking"] is False


def test_analyze_all_aggregates():
    out = analyze_all(
        {"symbol": "XAUUSD"},
        {"equity": 10000, "exposure": 2000},
        positions=[],
        atr_value=5.0,
        high_impact_events=[],
        utc_hour=9,
    )
    assert set(out["analyzers"].keys()) == {"portfolio", "correlation", "volatility", "news", "session"}
    assert "riskLevel" in out and "blocking" in out

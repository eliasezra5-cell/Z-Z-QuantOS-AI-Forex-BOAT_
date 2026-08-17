"""Unit tests for Feature 2 — social sentiment + fundamentals agents."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test")

import asyncio  # noqa: E402

from app.modules.ai.agents.base import AgentResult  # noqa: E402
from app.modules.ai.agents.fundamentals_agent import (  # noqa: E402
    FundamentalsAnalysisAgent,
    compute_fundamentals,
    _symbol_currencies,
)
from app.modules.ai.agents.sentiment_agent import (  # noqa: E402
    SentimentAnalysisAgent,
    _aggregate,
    _strict_parse,
)
from app.modules.ai.consensus_v2 import compute_consensus  # noqa: E402

NOW = int(__import__("time").time() * 1000)


def _ev(name, currency, impact, direction, confidence, ts_offset=0, instruments=()):
    return {
        "name": name,
        "currency": currency,
        "impact": impact,
        "time": NOW + ts_offset,
        "ai": {
            "direction": direction,
            "confidence": confidence,
            "affectedCurrencies": [currency],
            "affectedInstruments": list(instruments),
        },
    }


def test_symbol_currencies_parsing():
    assert _symbol_currencies("XAUUSD") == ("XAU", "USD")
    assert _symbol_currencies("EURUSD") == ("EUR", "USD")
    assert _symbol_currencies("USDJPY") == ("USD", "JPY")
    assert _symbol_currencies("AAPL") == ("", "USD")
    assert _symbol_currencies("us500") == ("", "USD")


def test_fundamentals_insufficient_when_no_events():
    res = compute_fundamentals("XAUUSD", events=[])
    assert res == {"abstain": "DATA_INSUFFICIENT"}


def test_fundamentals_insufficient_when_events_out_of_window():
    events = [_ev("CPI", "USD", 3, "bullish", 0.8, ts_offset=-10 * 24 * 3600000)]
    res = compute_fundamentals("XAUUSD", events=events)
    assert res == {"abstain": "DATA_INSUFFICIENT"}


def test_fundamentals_low_impact_ignored():
    events = [_ev("CPI", "USD", 1, "bullish", 0.8, ts_offset=0)]
    res = compute_fundamentals("XAUUSD", events=events)
    assert res == {"abstain": "DATA_INSUFFICIENT"}


def test_fundamentals_quote_currency_inverse_signal():
    # Strong USD (bullish USD) prices gold inversely -> bearish signal.
    events = [_ev("CPI", "USD", 3, "bullish", 0.8, ts_offset=0, instruments=["XAUUSD"])]
    res = compute_fundamentals("XAUUSD", events=events)
    assert res["direction"] == "sell"
    assert res["net"] < 0
    assert res["used"] == 1


def test_fundamentals_base_currency_direct_signal():
    # Strong EUR lifts EURUSD -> bullish signal.
    events = [_ev("ECB Rate", "EUR", 3, "bullish", 0.7, ts_offset=0, instruments=["EURUSD"])]
    res = compute_fundamentals("EURUSD", events=events)
    assert res["direction"] == "buy"
    assert res["net"] > 0


def test_fundamentals_insufficient_agent_result(monkeypatch):
    import app.modules.ai.agents.fundamentals_agent as fa

    monkeypatch.setattr(fa, "get_economic_events", lambda *a, **k: [])

    async def _run():
        return await FundamentalsAnalysisAgent().run({"symbol": "XAUUSD"})

    result = asyncio.run(_run())
    assert result.abstention == "DATA_INSUFFICIENT"
    assert result.direction == "neutral"
    assert result.agent_id == "custom-fundamentals"


def test_aggregate_none_when_no_data():
    assert _aggregate([], []) is None


def test_aggregate_positive_news_sentiment():
    news = [{"sentiment": 0.6, "confidence": 0.8}, {"sentiment": 0.2, "confidence": 0.5}]
    agg = _aggregate(news, [])
    assert agg["score"] > 0.15
    assert agg["label"] == "bullish"
    assert agg["breakdown"]["news"]["count"] == 2
    assert agg["breakdown"]["social"]["count"] == 0


def test_aggregate_negative_social_sentiment():
    social = [{"sentiment": -0.4}, {"sentiment": -0.3}]
    agg = _aggregate([], social)
    assert agg["score"] < -0.15
    assert agg["label"] == "bearish"


def test_sentiment_agent_insufficient_when_no_data(monkeypatch):
    import app.modules.ai.agents.sentiment_agent as sa

    monkeypatch.setattr(sa, "collect_social_sentiment", lambda *a, **k: [])
    monkeypatch.setattr(sa, "get_news", lambda *a, **k: [])

    async def _run():
        return await SentimentAnalysisAgent().run({"symbol": "XAUUSD"})

    result = asyncio.run(_run())
    assert result.abstention == "DATA_INSUFFICIENT"
    assert result.agent_id == "custom-sentiment"


def test_sentiment_parser_accepts_valid():
    parsed = _strict_parse(
        '{"sentimentScore": 0.4, "label": "bullish", "confidence": 0.7, '
        '"sourceBreakdown": {"news": {"count": 2, "avgSentiment": 0.3}, '
        '"social": {"count": 0, "avgSentiment": 0.0}}}',
        "t",
    )
    assert parsed["sentimentScore"] == 0.4


def test_sentiment_parser_rejects_missing_fields():
    import pytest as _pt

    with _pt.raises(Exception):
        _strict_parse('{"sentimentScore": 0.4}', "t")


def test_custom_agents_in_consensus_capped():
    news = AgentResult("news", "NewsAnalysisAgent", 0.40, direction="buy", confidence=0.60, abstention="TRADE")
    hist = AgentResult("historical", "HistoricalPatternAgent", 0.20, direction="buy", confidence=0.55, abstention="TRADE")
    macro = AgentResult("macro", "MacroAnalysisAgent", 0.20, direction="buy", confidence=0.50, abstention="TRADE")
    tech = AgentResult("technical", "TechnicalExecutionAgent", 0.20, direction="neutral", confidence=0.85, abstention="TRADE")
    risk = AgentResult("risk", "RiskManagerAgent", 0.0, direction="neutral", confidence=1.0, abstention="TRADE",
                       data={"riskApproved": True})
    sentiment = AgentResult("custom-sentiment", "SentimentAnalysisAgent", 0.10, direction="buy", confidence=0.6,
                            abstention="TRADE")
    fundamentals = AgentResult("custom-fundamentals", "FundamentalsAnalysisAgent", 0.10, direction="buy", confidence=0.7,
                               abstention="TRADE")
    out = compute_consensus([news, hist, macro, tech, risk, sentiment, fundamentals], risk)
    assert any(a.get("agent") == "SentimentAnalysisAgent" for a in out["customAgents"])
    assert any(a.get("agent") == "FundamentalsAnalysisAgent" for a in out["customAgents"])
    assert out["weights"]["custom"] == 0.20

"""Unit tests for Feature 1 — Bull vs Bear researcher debate."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test")

from app.modules.ai.agents.base import AgentResult  # noqa: E402
from app.modules.ai.agents.bear_researcher_agent import _strict_parse as bear_parse  # noqa: E402
from app.modules.ai.agents.bull_researcher_agent import _strict_parse as bull_parse  # noqa: E402
from app.modules.ai.consensus_v2 import compute_consensus  # noqa: E402
from app.modules.ai.research_manager import ResearchManager, rating_for_net  # noqa: E402

research_manager = ResearchManager()


def _bull(confidence=0.80):
    return AgentResult("bull", "BullResearcherAgent", 0.10, direction="buy",
                       confidence=confidence, abstention="TRADE", reasoning="arg",
                       data={"stance": "bull", "argument": "safe haven bid",
                             "confidence": confidence, "counters": ["rate cuts"]})


def _bear(confidence=0.40):
    return AgentResult("bear", "BearResearcherAgent", 0.10, direction="sell",
                       confidence=confidence, abstention="TRADE", reasoning="arg",
                       data={"stance": "bear", "argument": "dollar strength",
                             "confidence": confidence, "counters": ["dxy"]})


def _core(direction="buy", risk_ok=True):
    news = AgentResult("news", "NewsAnalysisAgent", 0.40, direction=direction, confidence=0.60,
                       abstention="TRADE", reasoning="n")
    hist = AgentResult("historical", "HistoricalPatternAgent", 0.20, direction=direction, confidence=0.55,
                       abstention="TRADE", reasoning="h")
    macro = AgentResult("macro", "MacroAnalysisAgent", 0.20, direction=direction, confidence=0.50,
                        abstention="TRADE", reasoning="m")
    tech = AgentResult("technical", "TechnicalExecutionAgent", 0.20, direction="neutral", confidence=0.85,
                       abstention="TRADE", reasoning="e", data={"execution": "confirmed"})
    risk = AgentResult("risk", "RiskManagerAgent", 0.0, direction="neutral", confidence=1.0,
                       abstention="TRADE" if risk_ok else "RISK_BLOCKED", reasoning="r",
                       data={"riskApproved": risk_ok, "reasons": [] if risk_ok else ["max-daily-loss"]})
    return [news, hist, macro, tech, risk]


def test_rating_for_net_buckets():
    assert rating_for_net(0.8) == "Buy"
    assert rating_for_net(0.3) == "Overweight"
    assert rating_for_net(0.0) == "Hold"
    assert rating_for_net(-0.3) == "Underweight"
    assert rating_for_net(-0.8) == "Sell"


def test_resolve_weights_confidence_not_average():
    resolved = research_manager.resolve(_bull(0.80), _bear(0.40), {"symbol": "XAUUSD"})
    assert resolved["rating"] == "Overweight"
    assert resolved["direction"] == "buy"
    assert resolved["strength"] == 0.6
    assert resolved["rationale"]
    assert len(resolved["transcript"]) == 3


def test_resolve_bear_wins():
    resolved = research_manager.resolve(_bull(0.20), _bear(0.85), {})
    assert resolved["rating"] == "Sell"
    assert resolved["direction"] == "sell"


def test_resolve_hold_when_even():
    resolved = research_manager.resolve(_bull(0.50), _bear(0.50), {})
    assert resolved["rating"] == "Hold"
    assert resolved["direction"] == "neutral"


def test_debate_nudge_applied_in_consensus():
    results = _core(direction="buy")
    risk = results[-1]
    debate = {"direction": "sell", "strength": 0.9}
    out = compute_consensus(results, risk, debate_result=debate)
    assert out["xai"]["debate"]["direction"] == "sell"
    assert out["xai"]["debate"]["strength"] == 0.9


def test_debate_never_overrides_risk_veto():
    results = _core(direction="buy", risk_ok=False)
    risk = results[-1]
    debate = {"direction": "buy", "strength": 0.9}
    out = compute_consensus(results, risk, debate_result=debate)
    assert out["direction"] == "no_trade"
    assert out["status"] == "NO_TRADE"
    assert out["riskApproved"] is False


def test_hold_debate_does_not_nudge():
    results = _core(direction="buy")
    risk = results[-1]
    hold = {"direction": "neutral", "strength": 0.0}
    out = compute_consensus(results, risk, debate_result=hold)
    assert out["xai"]["debate"]["direction"] is None


def test_bull_parser_rejects_bad_stance():
    import pytest as _pt

    with _pt.raises(Exception):
        bull_parse('{"stance": "bear", "argument": "x", "confidence": 0.5, "counters": []}', "t")


def test_bear_parser_rejects_bad_stance():
    import pytest as _pt

    with _pt.raises(Exception):
        bear_parse('{"stance": "bull", "argument": "x", "confidence": 0.5, "counters": []}', "t")


def test_bull_parser_accepts_valid():
    parsed = bull_parse('{"stance": "bull", "argument": "thesis", "confidence": 0.7, "counters": ["c1"]}', "t")
    assert parsed["stance"] == "bull"
    assert parsed["confidence"] == 0.7


def _degraded():
    return AgentResult("bull", "BullResearcherAgent", 0.10, direction="neutral",
                       confidence=0.0, abstention="PROVIDER_DEGRADED", reasoning="llm down",
                       data={})


def test_resolve_both_provider_degraded_is_unavailable():
    resolved = research_manager.resolve(_degraded(), _degraded(), {})
    assert resolved["available"] is False
    assert resolved["status"] == "unavailable"
    assert resolved["rating"] is None
    assert resolved["direction"] == "neutral"
    assert resolved["strength"] == 0.0
    assert "unavailable" in resolved["reason"].lower()
    assert "PROVIDER_DEGRADED" in resolved["reason"]
    assert resolved["bull"]["state"] == "PROVIDER_DEGRADED"
    assert resolved["bear"]["state"] == "PROVIDER_DEGRADED"


def test_resolve_none_results_is_unavailable():
    resolved = research_manager.resolve(None, None, {})
    assert resolved["available"] is False
    assert resolved["status"] == "unavailable"
    assert "MISSING" in resolved["reason"]


def test_resolve_single_side_available_is_partial():
    bull = _bull(0.80)
    bear = _degraded()
    bear.agent_id = "bear"
    resolved = research_manager.resolve(bull, bear, {})
    assert resolved["available"] is True
    assert resolved["status"] == "partial"
    assert resolved["rating"] in ("Buy", "Overweight")
    assert resolved["direction"] == "buy"
    assert resolved["bull"]["state"] == "TRADE"
    assert resolved["bear"]["state"] == "PROVIDER_DEGRADED"
    assert "unavailable" in resolved["rationale"].lower()


def test_resolve_empty_arguments_is_unavailable():
    empty = AgentResult("bull", "BullResearcherAgent", 0.10, direction="neutral",
                        confidence=0.0, abstention="TRADE", reasoning="",
                        data={"stance": "bull", "argument": "   ", "confidence": 0.0, "counters": []})
    empty_bear = AgentResult("bear", "BearResearcherAgent", 0.10, direction="neutral",
                             confidence=0.0, abstention="TRADE", reasoning="",
                             data={"stance": "bear", "argument": "", "confidence": 0.0, "counters": []})
    resolved = research_manager.resolve(empty, empty_bear, {})
    assert resolved["available"] is False
    assert resolved["status"] == "unavailable"


def test_resolved_fields_backward_compatible():
    resolved = research_manager.resolve(_bull(0.80), _bear(0.40), {})
    assert resolved["rating"] == "Overweight"
    assert resolved["direction"] == "buy"
    assert resolved["strength"] == 0.6
    assert resolved["status"] == "complete"
    assert resolved["available"] is True
    assert len(resolved["transcript"]) == 3
    assert resolved["transcript"][0]["state"] == "TRADE"


def test_debate_history_entry_persists_availability_fields():
    from app.modules.ai.decision_pipeline import DecisionPipeline  # noqa: E402
    import app.modules.ai.decision_pipeline as dp

    resolved = research_manager.resolve(_degraded(), _degraded(), {})
    pipeline = DecisionPipeline()
    col = dp.db.collection("debate_history")
    before = [r["id"] for r in col.all()]
    pipeline._persist_debate("XAUUSD", resolved)

    rows = col.find({"symbol": "XAUUSD", "status": "unavailable"})
    assert rows, "debate_history should contain the unavailable entry"
    assert rows[0]["available"] is False
    assert rows[0]["reason"]

    # Isolated test store: remove exactly the rows this test inserted so the
    # test DATA_DIR stays clean and never leaks fixture rows into live data.
    inserted = [r["id"] for r in col.all() if r["id"] not in before]
    for rid in inserted:
        col.remove(rid)

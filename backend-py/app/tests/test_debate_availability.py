"""Integration tests for bull/bear debate availability + per-symbol variance.

Covers the fixes for the audit finding that the debate silently returned an
identical "Hold / Confidence 0" for every symbol when the configured LLM
provider could not satisfy the strict ``{stance, argument, confidence,
counters}`` schema:

- Both sides provider-degraded -> ResearchManager returns an explicit
  ``unavailable`` result (never a fabricated neutral rating).
- When a strict-JSON provider responds, the debate runs through the real
  pipeline call path and yields per-symbol non-identical bull/bear cases.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test")

import asyncio  # noqa: E402

from app.modules.ai import clients  # noqa: E402
from app.modules.ai.decision_pipeline import decision_pipeline  # noqa: E402
from app.modules.ai.research_manager import ResearchManager  # noqa: E402
from app.modules.ai.agents.base import AgentResult  # noqa: E402

research_manager = ResearchManager()


class _FakeManagedProvider:
    """Drop-in for ManagedProvider: symbol-aware strict-JSON completion."""

    id = "fake-strict"

    def __init__(self, resolver):
        self._resolver = resolver

    def complete_custom(self, messages, parser=None, fallback_shape=None, temperature=0.2, max_tokens=2000):
        text = self._resolver(json.dumps(messages))
        if parser:
            return parser(text, self.id)
        return {"text": text, "model": self.id}

    def status(self):
        return {"id": self.id}


def _symbol_resolver(blob):
    is_bear = "BEAR researcher" in blob
    if "EURUSD" in blob:
        return json.dumps({
            "stance": "bear" if is_bear else "bull",
            "argument": "EURUSD: ECB dovish and soft PMI pressure" if is_bear
                        else "EURUSD: resilient US labor market caps EUR upside",
            "confidence": 0.90 if is_bear else 0.35, "counters": ["ecb", "pmi"],
        })
    return json.dumps({
        "stance": "bear" if is_bear else "bull",
        "argument": "XAUUSD: strong dollar caps upside" if is_bear
                    else "XAUUSD: safe-haven bid on rate-cut expectations",
        "confidence": 0.25 if is_bear else 0.90, "counters": ["dxy"] if is_bear else ["fed", "vix"],
    })


_MANAGER_WAS_NONE = clients.ai_provider_manager is None


def _install_fake(resolver):
    if clients.ai_provider_manager is None:
        clients.init_ai_clients()
    original = clients.ai_provider_manager.managed
    clients.ai_provider_manager.managed = [_FakeManagedProvider(resolver)] + list(original)
    # The agents bound `ai_provider_manager` at import time (before init), so
    # re-bind their module-level reference to the same (mutated) manager.
    from app.modules.ai.agents import bull_researcher_agent, bear_researcher_agent
    bull_researcher_agent.ai_provider_manager = clients.ai_provider_manager
    bear_researcher_agent.ai_provider_manager = clients.ai_provider_manager
    return original


def _restore(original):
    if _MANAGER_WAS_NONE:
        clients.ai_provider_manager = None
    else:
        clients.ai_provider_manager.managed = original


def _restore_fail_closed():
    """The full pipeline run can raise fail-closed triggers (market-data-stale /
    reconciliation-mismatch) that persist to disk and would block every later
    order test in this process. Clear what we may have raised."""
    from app.modules.risk.capital_protection import capital_protection

    for t in list(capital_protection.get_status().get("fail_closed") or []):
        capital_protection.clear_fail_closed(t)


def _restore_db_collections():
    """Clear collections the pipeline run writes into so they do not leak into
    other test modules sharing the same DATA_DIR."""
    from app.foundation.json_store import db

    for name in ("positions", "orders", "suggested_trades", "trade_reanalysis_log",
                 "mt5_safety_orders", "mt5_frozen_symbols", "mt5_reconciliation"):
        try:
            db.collection(name).clear()
        except Exception:  # noqa: BLE001 - collection may not exist
            pass


def _cleanup(original):
    _restore(original)
    _restore_fail_closed()
    _restore_db_collections()


def _degraded(agent_id="bull"):
    return AgentResult(agent_id, "Researcher", 0.10, direction="neutral",
                       confidence=0.0, abstention="PROVIDER_DEGRADED",
                       reasoning="llm down", data={})


def test_unavailable_never_fabricates_rating():
    resolved = research_manager.resolve(_degraded("bull"), _degraded("bear"), {})
    assert resolved["available"] is False
    assert resolved["status"] == "unavailable"
    assert resolved["rating"] is None
    assert resolved["net"] == 0.0
    assert resolved["strength"] == 0.0


def test_full_pipeline_with_live_provider_is_symbol_variant():
    async def run():
        original = _install_fake(_symbol_resolver)
        try:
            xau = await decision_pipeline.analyze("XAUUSD", persist=False)
            eur = await decision_pipeline.analyze("EURUSD", persist=False)
        finally:
            _cleanup(original)
        return xau, eur

    xau, eur = asyncio.run(run())

    dx, de = xau["debate"], eur["debate"]
    assert dx["status"] == "complete"
    assert dx["available"] is True
    assert de["status"] == "complete"

    assert dx["rating"] != de["rating"]
    assert dx["direction"] != de["direction"]
    assert dx["bull"]["argument"] != de["bull"]["argument"]
    assert dx["bull"]["confidence"] != de["bull"]["confidence"]

    assert dx["bull"]["confidence"] > 0
    assert de["bull"]["confidence"] > 0
    assert dx["bear"]["confidence"] > 0
    assert de["bear"]["confidence"] > 0

    assert "XAUUSD" in dx["bull"]["argument"]
    assert "EURUSD" in de["bull"]["argument"]


def test_partial_debate_when_only_one_side_responds():
    def resolver(blob):
        is_bear = "BEAR researcher" in blob
        if not is_bear:
            return json.dumps({"stance": "bull", "argument": "bull thesis",
                               "confidence": 0.7, "counters": []})
        raise clients.LLMError("fake-strict: simulated outage")

    async def run():
        original = _install_fake(resolver)
        try:
            # Inject a degraded bear result by running resolve directly with a
            # mix of live-provider (bull) and degraded (bear) results.
            from app.modules.ai.agents.bull_researcher_agent import BullResearcherAgent
            from app.modules.ai.agents.bear_researcher_agent import BearResearcherAgent
            from app.modules.ai.research_manager import research_manager as rm

            ctx = {"symbol": "XAUUSD", "core_results": [{"name": "news", "weight": 0.4}]}
            bull = await BullResearcherAgent().run(ctx)
            bear = BearResearcherAgent()
            degraded = _degraded("bear")
            resolved = rm.resolve(bull, degraded, ctx)
            return resolved
        finally:
            _cleanup(original)

    resolved = asyncio.run(run())
    assert resolved["status"] == "partial"
    assert resolved["available"] is True
    assert resolved["bull"]["state"] == "TRADE"
    assert resolved["bear"]["state"] == "PROVIDER_DEGRADED"
    assert "unavailable" in resolved["rationale"].lower()

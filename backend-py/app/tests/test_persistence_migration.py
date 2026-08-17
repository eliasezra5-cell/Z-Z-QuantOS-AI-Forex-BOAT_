"""Unit tests for the additive persistence layer + strict 80/20 consensus.

Covers: repository JSON-store fallback (no Postgres in CI), CustomAgent
encryption round-trip, news source CRUD through the repository, the strict
40/20/20/20 consensus formula, and the risk-manager VETO behaviour.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test_persist")
os.environ["POSTGRES_ENABLED"] = "false"
os.environ["DATABASE_URL"] = ""
os.environ.setdefault("CRYPTO_KEY", "quantos-test-crypto-key-0001")

from app.persistence import news_repository, custom_agent_repository, decision_repository, position_repository  # noqa: E402
from app.persistence.repository import encrypt_api_key, decrypt_api_key  # noqa: E402
from app.modules.ai.consensus_v2 import compute_consensus, CORE_WEIGHTS  # noqa: E402
from app.modules.ai.agents.base import AgentResult  # noqa: E402


def test_core_weights_are_strict_8020():
    from decimal import Decimal

    assert CORE_WEIGHTS == {
        "news": Decimal("0.40"),
        "historical": Decimal("0.20"),
        "macro": Decimal("0.20"),
        "technical": Decimal("0.20"),
    }
    assert abs(sum(CORE_WEIGHTS.values()) - Decimal("1.0")) < Decimal("1e-9")


def test_news_source_crud_through_repository():
    import asyncio

    async def scenario():
        await news_repository.remove_source("test-src-persist")
        src = await news_repository.add_source({
            "name": "Test Feed",
            "type": "rss",
            "url": "https://example.com/feed.xml",
            "priority": 5,
            "enabled": True,
        })
        assert src["name"] == "Test Feed"
        listed = await news_repository.list_sources()
        assert any(s["id"] == src["id"] for s in listed)
        updated = await news_repository.update_source(src["id"], {"priority": 42, "enabled": False})
        assert updated["priority"] == 42
        assert updated["enabled"] is False
        removed = await news_repository.remove_source(src["id"])
        assert removed is not None
        gone = await news_repository.list_sources()
        assert not any(s["id"] == src["id"] for s in gone)

    asyncio.run(scenario())


def test_custom_agent_create_list_update_remove():
    import asyncio

    async def scenario():
        created = await custom_agent_repository.create({
            "name": "Macro Reader",
            "provider_type": "paid_openai",
            "model_name": "gpt-4o-mini",
            "system_prompt": "Judge macro",
            "voting_weight": 0.15,
            "api_key": "sk-test-123",
            "enabled": True,
        })
        assert created["voting_weight"] == 0.15
        assert created["api_key_encrypted"] != "sk-test-123"

        agents = await custom_agent_repository.list()
        assert any(a["id"] == created["id"] for a in agents)

        enabled = await custom_agent_repository.enabled_agents()
        assert any(a["id"] == created["id"] for a in enabled)

        updated = await custom_agent_repository.update(created["id"], {"voting_weight": 0.20})
        assert updated["voting_weight"] == 0.20

        removed = await custom_agent_repository.remove(created["id"])
        assert removed is not None

    asyncio.run(scenario())


def test_api_key_fernet_roundtrip():
    key = "sk-live-very-secret-value"
    enc = encrypt_api_key(key)
    assert enc != key
    assert decrypt_api_key(enc) == key


def test_decision_insert_and_list():
    import asyncio
    import time

    async def scenario():
        decision = {
            "symbol": "XAUUSD",
            "direction": "buy",
            "confidence": 0.92,
            "status": "AUTO_EXECUTE",
            "riskApproved": True,
            "newsIds": ["n1", "n2"],
            "entry": 2400.5,
            "stopLoss": 2395.0,
            "takeProfit": 2420.0,
            "timestamp": int(time.time() * 1000),
        }
        doc = await decision_repository.insert(decision)
        assert doc["direction"] == "buy"
        rows = await decision_repository.list(limit=10)
        assert any(r["id"] == doc["id"] for r in rows)
        latest = await decision_repository.latest()
        assert latest is not None

    asyncio.run(scenario())


def _agent(agent_id, name, weight, direction, confidence, abstention="TRADE", data=None):
    return AgentResult(
        agent_id=agent_id, name=name, weight=weight,
        direction=direction, confidence=confidence, abstention=abstention,
        data=data or {},
    )


def test_consensus_news_40_historical_20_macro_20_technical_20():
    news = _agent("news", "NewsAnalysisAgent", 0.40, "buy", 0.80)
    hist = _agent("historical", "HistoricalPatternAgent", 0.20, "buy", 0.75)
    macro = _agent("macro", "MacroAnalysisAgent", 0.20, "neutral", 0.5, abstention="ABSTAIN")
    tech = _agent("technical", "TechnicalExecutionAgent", 0.20, "neutral", 0.9,
                  data={"execution": "confirmed"})
    risk = _agent("risk", "RiskManagerAgent", 0.0, "neutral", 1.0,
                  data={"riskApproved": True, "reasons": []})

    res = compute_consensus([news, hist, macro, tech], risk)
    assert res["direction"] == "buy"
    assert res["riskApproved"] is True
    # news(0.80) + hist(0.75) -> high confidence buy family
    assert res["confidence"] >= 0.70


def test_consensus_risk_veto_overrides_high_score():
    news = _agent("news", "NewsAnalysisAgent", 0.40, "buy", 0.95)
    hist = _agent("historical", "HistoricalPatternAgent", 0.20, "buy", 0.90)
    macro = _agent("macro", "MacroAnalysisAgent", 0.20, "buy", 0.85)
    tech = _agent("technical", "TechnicalExecutionAgent", 0.20, "neutral", 0.95,
                  data={"execution": "confirmed"})
    risk = _agent("risk", "RiskManagerAgent", 0.0, "neutral", 0.0,
                  data={"riskApproved": False, "reasons": ["spread-too-wide", "high-correlation"]})

    res = compute_consensus([news, hist, macro, tech], risk)
    assert res["riskApproved"] is False
    assert res["status"] == "NO_TRADE"
    assert res["direction"] == "no_trade"
    assert res["riskReasons"] == ["spread-too-wide", "high-correlation"]


def test_consensus_low_scores_no_trade():
    news = _agent("news", "NewsAnalysisAgent", 0.40, "sell", 0.30)
    hist = _agent("historical", "HistoricalPatternAgent", 0.20, "buy", 0.4)
    macro = _agent("macro", "MacroAnalysisAgent", 0.20, "neutral", 0.5, abstention="ABSTAIN")
    tech = _agent("technical", "TechnicalExecutionAgent", 0.20, "neutral", 0.8,
                  data={"execution": "confirmed"})
    risk = _agent("risk", "RiskManagerAgent", 0.0, "neutral", 1.0,
                  data={"riskApproved": True, "reasons": []})

    res = compute_consensus([news, hist, macro, tech], risk)
    assert res["status"] == "NO_TRADE"


def test_position_upsert_and_list_open():
    import asyncio

    async def scenario():
        pos = {
            "id": "pos-persist-test",
            "symbol": "XAUUSD",
            "side": "buy",
            "lotSize": 0.01,
            "entry": 2400.0,
            "status": "open",
            "initialConfidence": 0.95,
            "openedAt": 1700000000000,
        }
        saved = await position_repository.upsert(pos)
        assert saved["side"] == "buy"
        open_rows = await position_repository.list_open()
        assert any(r["id"] == "pos-persist-test" for r in open_rows)
        got = await position_repository.get("pos-persist-test")
        assert got is not None and got["entry"] == 2400.0
        # close it so subsequent runs stay clean
        closed = await position_repository.upsert({**pos, "status": "closed", "closedAt": 1700000001000})
        assert closed["status"] == "closed"
        open_after = await position_repository.list_open()
        assert not any(r["id"] == "pos-persist-test" for r in open_after)

    asyncio.run(scenario())

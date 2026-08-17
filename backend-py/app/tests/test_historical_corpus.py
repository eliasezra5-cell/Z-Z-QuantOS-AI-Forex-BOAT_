"""Tests for the historical pattern corpus + HistoricalPatternAgent.

Covers: seeding ``event_embeddings`` from the curated named-event catalog,
idempotent seeding, ranked cosine similarity search, and the agent returning a
real directional vote (not DATA_INSUFFICIENT) once the corpus is populated.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test_historical")
os.environ["POSTGRES_ENABLED"] = "false"
os.environ["DATABASE_URL"] = ""

from unittest import mock  # noqa: E402

from app.modules.ai.agents.historical_agent import HistoricalPatternAgent  # noqa: E402
from app.modules.historical.memory import seed_event_embeddings, named_events  # noqa: E402
from app.persistence import repository  # noqa: E402
from app.persistence.repository import EventEmbeddingRepository  # noqa: E402


def _fresh_repo():
    return EventEmbeddingRepository()


def _seed():
    return seed_event_embeddings()


def test_seed_populates_full_catalog():
    repo = _fresh_repo()
    repo.col.clear()
    with mock.patch("app.persistence.repository.event_embedding_repository", repo):
        seeded = _seed()
    assert seeded == len(named_events())
    assert repo.col.count() == len(named_events())


def test_seed_is_idempotent():
    repo = _fresh_repo()
    repo.col.clear()
    with mock.patch("app.persistence.repository.event_embedding_repository", repo):
        _seed()
        _seed()
    assert repo.col.count() == len(named_events())
    ids = [r["id"] for r in repo.col.find({})]
    assert len(set(ids)) == len(ids)


def test_seeded_events_carry_vectors_and_direction():
    repo = _fresh_repo()
    repo.col.clear()
    with mock.patch("app.persistence.repository.event_embedding_repository", repo):
        _seed()
    sample = repo.col.find({})[0]
    assert len(sample.get("vector", [])) > 0
    assert sample["direction"] in ("buy", "sell")


def test_similarity_search_ranks_by_cosine():
    repo = _fresh_repo()
    repo.col.clear()
    with mock.patch("app.persistence.repository.event_embedding_repository", repo):
        _seed()
    from app.modules.ai.memory import embed

    query = embed("Federal Reserve interest rate cuts gold rally")
    matches = asyncio.run(repo.similarity_search(query, k=5))
    assert len(matches) <= 5
    assert len(matches) > 0
    scores = [m.get("score") for m in matches]
    assert scores == sorted(scores, reverse=True)


def test_agent_returns_trade_when_corpus_populated():
    repo = _fresh_repo()
    repo.col.clear()
    with mock.patch("app.persistence.repository.event_embedding_repository", repo):
        _seed()
    agent = HistoricalPatternAgent()
    with mock.patch("app.modules.ai.agents.historical_agent.event_embedding_repository", repo):
        result = asyncio.run(agent.run({
            "symbol": "XAUUSD",
            "news": [{"title": "Fed signals dovish pivot as inflation cools"}],
        }))
    assert result.abstention == "TRADE"
    assert result.direction in ("buy", "sell")
    assert result.data["matches"] > 0


def test_agent_abstains_when_corpus_empty():
    repo = _fresh_repo()
    repo.col.clear()
    agent = HistoricalPatternAgent()
    with mock.patch("app.modules.ai.agents.historical_agent.event_embedding_repository", repo):
        result = asyncio.run(agent.run({
            "symbol": "XAUUSD",
            "news": [{"title": "Fed signals dovish pivot"}],
        }))
    assert result.abstention == "DATA_INSUFFICIENT"

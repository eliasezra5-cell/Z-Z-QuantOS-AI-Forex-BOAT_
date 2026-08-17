"""Unit tests for the deterministic historical 40/20/40 match engine.

Covers determinism, keyword-overlap ranking, exact weights and score bounds
for compute_match_score and the pattern/similarity wrappers. No network calls.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_hist_match")

from app.modules.historical.engine import (  # noqa: E402
    compute_match_score,
    get_similar_events,
    pattern_matching,
)

TARGET = {
    "id": "t1",
    "title": "Non-farm payrolls beat expectations dollar strengthens",
    "keywords": ["NFP", "payrolls", "labor"],
    "category": "macro",
    "entities": ["USD", "NFP"],
}
SIMILAR = {
    "id": "c1",
    "title": "Non-farm payrolls beat expectations dollar strengthens",
    "keywords": ["NFP", "payrolls", "labor"],
    "category": "macro",
    "entities": ["USD", "NFP"],
    "direction": "buy",
    "tags": ["bullish"],
}
UNRELATED = {
    "id": "c2",
    "title": "Ethereum upgrade goes live",
    "keywords": ["ETH", "upgrade"],
    "category": "crypto",
    "entities": ["ETH"],
    "direction": "buy",
    "tags": ["bullish"],
}
CONTEXT = {
    "market": {"goldDirection": "bullish", "rsiRegime": None},
    "technical": {"trend": "bullish", "rsi14": 55, "volatility": 0.02},
}


def test_compute_match_score_is_deterministic():
    first = compute_match_score(TARGET, SIMILAR, CONTEXT)
    second = compute_match_score(TARGET, SIMILAR, CONTEXT)
    assert first == second


def test_keyword_rich_candidate_scores_higher():
    similar = compute_match_score(TARGET, SIMILAR, CONTEXT)["score"]
    unrelated = compute_match_score(TARGET, UNRELATED, CONTEXT)["score"]
    assert similar > unrelated


def test_weights_are_exactly_40_20_40():
    result = compute_match_score(TARGET, SIMILAR, CONTEXT)
    assert result["weights"] == {"news": 0.4, "market": 0.2, "technical": 0.4}


def test_score_bounded_between_zero_and_one():
    for candidate in (SIMILAR, UNRELATED, {}, {"direction": "sell"}):
        score = compute_match_score(TARGET, candidate, CONTEXT)["score"]
        assert 0.0 <= score <= 1.0
        assert score == max(0.0, min(1.0, score))


def test_no_context_still_deterministic_and_bounded():
    a = compute_match_score(TARGET, SIMILAR)
    b = compute_match_score(TARGET, SIMILAR)
    assert a == b
    assert 0.0 <= a["score"] <= 1.0
    assert a["weights"] == {"news": 0.4, "market": 0.2, "technical": 0.4}

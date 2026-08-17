"""Tests for the AI Learning Engine extensions (Phase 2, Module 2).

Covers pattern learning (win rate by newsCategory + technicalSetup), the
win-rate boost helper, and offline mistake analysis root causes.

Run with: python3 -m pytest app/tests/test_ai_learning_phase2.py -q
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_learning_phase2_test")

from app.foundation.json_store import db  # noqa: E402
from app.modules.ai.pattern_learning import pattern_learning  # noqa: E402
from app.modules.ai.mistake_analysis import mistake_analyzer  # noqa: E402
from app.tasks.mistake_analysis import run_daily_mistake_analysis  # noqa: E402


def _reset():
    for name in ("learning_log", "pattern_win_rates", "mistake_analysis"):
        db.collection(name).clear()


def _loss(**over):
    entry = {
        "symbol": "XAUUSD",
        "direction": "buy",
        "profit": -12.5,
        "win": False,
        "newsCategory": "interest-rate",
        "setup": "fvg",
        "timestamp": int(time.time() * 1000),
        **over,
    }
    return db.collection("learning_log").insert(entry)


def _win(**over):
    return db.collection("learning_log").insert({
        "symbol": "XAUUSD",
        "direction": "sell",
        "profit": 8.0,
        "win": True,
        "newsCategory": "inflation",
        "setup": "order-block",
        "timestamp": int(time.time() * 1000),
        **over,
    })


# --------------------------------------------------------------------------- #
# Pattern learning: win rate by newsCategory + technicalSetup
# --------------------------------------------------------------------------- #
def test_pattern_compute_win_rate():
    _reset()
    _loss(newsCategory="interest-rate", setup="fvg")
    _win(newsCategory="interest-rate", setup="fvg")
    _win(newsCategory="interest-rate", setup="fvg")
    rows = pattern_learning.compute()
    fvg = next(r for r in rows if r["pattern"] == "interest-rate:fvg")
    assert fvg["sampleCount"] == 3
    assert fvg["wins"] == 2
    assert round(fvg["winRate"], 3) == round(0.6667, 3)


def test_pattern_compute_empty():
    _reset()
    assert pattern_learning.compute() == []


def test_pattern_persist_and_query():
    _reset()
    _loss(newsCategory="inflation", setup="order-block")
    _win(newsCategory="inflation", setup="order-block")
    _win(newsCategory="inflation", setup="order-block")
    stored = pattern_learning.persist()
    assert len(stored) >= 1
    hit = pattern_learning.get_win_rate("inflation", "order-block")
    assert hit["winRate"] == round(2 / 3, 4)
    assert hit["sampleCount"] == 3
    miss = pattern_learning.get_win_rate("never-seen", "nope")
    assert miss["winRate"] is None and miss["sampleCount"] == 0


# --------------------------------------------------------------------------- #
# Win-rate boost used by the AI pipeline
# --------------------------------------------------------------------------- #
def test_win_rate_boost_applies_with_enough_samples():
    _reset()
    for _ in range(5):
        _win(newsCategory="cpi", setup="bos")
    pattern_learning.persist()
    adjusted, meta = pattern_learning.win_rate_boost("cpi", "bos", base_confidence=0.80)
    assert meta["adjusted"] is True
    assert 0.0 <= adjusted <= 1.0
    assert adjusted > 0.80  # 100% historical win rate pulls confidence up


def test_win_rate_boost_skips_insufficient_samples():
    _reset()
    _win(newsCategory="cpi", setup="bos")
    pattern_learning.persist()
    adjusted, meta = pattern_learning.win_rate_boost("cpi", "bos", base_confidence=0.80)
    assert meta["adjusted"] is False
    assert "insufficient samples" in meta["reason"]
    assert adjusted == 0.80


# --------------------------------------------------------------------------- #
# Mistake analysis: offline root-cause classification
# --------------------------------------------------------------------------- #
def test_mistake_analysis_high_spread():
    _reset()
    _loss(newsCategory="interest-rate", setup="fvg", spreadAtEntry=45)
    analysis = mistake_analyzer.analyze()
    causes = {b["root_cause"]: b for b in analysis["byRootCause"]}
    assert "Ignored high spread" in causes
    assert analysis["totalLosses"] == 1


def test_mistake_analysis_against_dxy_trend():
    _reset()
    _loss(direction="sell", dxyTrend="bullish")
    analysis = mistake_analyzer.analyze()
    causes = {b["root_cause"]: b for b in analysis["byRootCause"]}
    assert "Entered against DXY trend" in causes


def test_mistake_analysis_low_confidence():
    _reset()
    _loss(confidence=0.55)
    analysis = mistake_analyzer.analyze()
    causes = {b["root_cause"]: b for b in analysis["byRootCause"]}
    assert "Low confidence entry" in causes


def test_mistake_analysis_missing_sl():
    _reset()
    _loss(confidence=0.95, stopLoss=None)
    analysis = mistake_analyzer.analyze()
    causes = {b["root_cause"]: b for b in analysis["byRootCause"]}
    assert "No stop-loss protection" in causes


def test_mistake_analysis_wins_not_counted():
    _reset()
    _win()
    _loss()
    analysis = mistake_analyzer.analyze()
    assert analysis["totalLosses"] == 1


def test_mistake_analysis_aggregates_counts():
    _reset()
    _loss(spreadAtEntry=45)
    _loss(spreadAtEntry=55)
    _loss(confidence=0.5)
    analysis = mistake_analyzer.analyze()
    by_cause = {b["root_cause"]: b for b in analysis["byRootCause"]}
    assert by_cause["Ignored high spread"]["count"] == 2
    assert by_cause["Low confidence entry"]["count"] == 1


# --------------------------------------------------------------------------- #
# Daily Celery task
# --------------------------------------------------------------------------- #
def test_daily_mistake_analysis_task_runs():
    _reset()
    _loss(newsCategory="interest-rate", setup="fvg")
    _win(newsCategory="interest-rate", setup="fvg")
    summary = run_daily_mistake_analysis()
    assert summary["task"] == "mistake-analysis-daily"
    assert summary["totalLosses"] == 1
    assert summary["patternsPersisted"] >= 1
    assert isinstance(summary["topRootCauses"], list)

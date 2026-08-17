"""Tests for the additive technical confluence score (Feature 2).

No real network: candles come from the synthetic ``generate_candles`` engine,
so both the pure module path and the HTTP endpoint run entirely offline.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_confluence_test")
os.environ["POSTGRES_ENABLED"] = "false"
os.environ["DATABASE_URL"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.modules.technical.confluence import _compute_agreement, compute_confluence  # noqa: E402
from app.modules.technical.multi_timeframe import TIMEFRAMES  # noqa: E402
from app.modules.marketdata.engine import generate_candles  # noqa: E402


def _candles_by_tf():
    return {tf: generate_candles("EURUSD", tf, 100 if tf == "W1" else 250) for tf in TIMEFRAMES}


def test_confluence_per_timeframe_ranges_and_shape():
    out = compute_confluence(_candles_by_tf(), symbol="EURUSD")
    assert out["symbol"] == "EURUSD"
    assert out["timeframes"]
    for tf in out["timeframes"]:
        assert 0 <= tf["confluence"] <= 100
        assert tf["direction"] in ("buy", "sell", "neutral")
        assert 0 <= tf["strength"] <= 1
        assert 0 <= tf["agreement"] <= 1
        assert tf["components"] >= 0
    assert 0 <= out["composite"] <= 100
    assert out["bias"] in ("bullish", "bearish", "neutral")


def test_confluence_composite_is_mean_of_timeframes():
    out = compute_confluence(_candles_by_tf(), symbol="EURUSD")
    mean = round(sum(t["confluence"] for t in out["timeframes"]) / len(out["timeframes"]))
    assert out["composite"] == mean


def test_confluence_agreement_helper():
    assert _compute_agreement("buy", ["buy", "buy", "sell"]) == pytest.approx(2 / 3)
    assert _compute_agreement("buy", ["sell", "sell"]) == 0.0
    assert _compute_agreement("sell", ["sell"]) == 1.0
    assert _compute_agreement("neutral", ["buy"]) == 0.0
    assert _compute_agreement("buy", []) == 0.0


def test_confluence_conflicting_timeframes_score_lower_than_aligned():
    # Two timeframes agreeing should out-score the same setup in conflict.
    direction = "buy"
    aligned = _compute_agreement(direction, [direction, direction, "sell"])
    conflicted = _compute_agreement(direction, ["sell", "sell", "sell"])
    assert aligned > conflicted


def test_confluence_skips_timeframes_without_enough_data():
    candles = generate_candles("EURUSD", "H1", 60)
    short = generate_candles("EURUSD", "M1", 5)
    out = compute_confluence({"H1": candles, "M1": short}, symbol="EURUSD")
    tfs = [t["timeframe"] for t in out["timeframes"]]
    assert "M1" not in tfs
    assert "H1" in tfs


def test_confluence_endpoint_returns_200():
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/api/technical/confluence/EURUSD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "EURUSD"
    assert body["timeframes"]
    assert 0 <= body["composite"] <= 100

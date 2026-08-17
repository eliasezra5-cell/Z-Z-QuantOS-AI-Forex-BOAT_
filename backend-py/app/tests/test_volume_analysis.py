"""Unit tests for additive volume analysis indicators (Batch 08)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test")

from app.modules.technical.volume_analysis import (  # noqa: E402
    cumulative_volume_delta,
    delta,
    enrich_with_volume_analysis,
    volume_analysis,
    volume_profile,
)


def _candles():
    return [
        {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 100},
        {"open": 101, "high": 103, "low": 100, "close": 100.5, "volume": 150},
        {"open": 100.5, "high": 104, "low": 100, "close": 103.5, "volume": 200},
        {"open": 103.5, "high": 105, "low": 102, "close": 104, "volume": 250},
        {"open": 104, "high": 106, "low": 103, "close": 105.5, "volume": 300},
    ]


def test_delta_length_matches_candles():
    out = delta(_candles())
    assert len(out) == 5


def test_delta_uses_explicit_buy_sell_volume():
    candles = [{"high": 10, "low": 9, "close": 9.5, "buyVolume": 80, "sellVolume": 30}]
    assert delta(candles)[0] == 50


def test_cvd_accumulates():
    res = cumulative_volume_delta(_candles())
    assert len(res["cvd"]) == 5
    assert res["cvd"][-1] == round(sum(res["delta"]), 4)


def test_volume_profile_returns_poc():
    prof = volume_profile(_candles(), bins=10)
    assert prof["poc"] is not None
    assert prof["valueAreaHigh"] is not None
    assert prof["valueAreaLow"] is not None
    assert prof["valueAreaLow"] <= prof["valueAreaHigh"]


def test_volume_profile_levels_sorted():
    prof = volume_profile(_candles(), bins=10)
    prices = [lv["price"] for lv in prof["levels"]]
    assert prices == sorted(prices)


def test_volume_analysis_bundle():
    res = volume_analysis(_candles())
    assert "delta" in res and "cvd" in res and "profile" in res
    assert len(res["cvdSeries"]) == 5


def test_enrich_is_additive():
    ind = {"rsi14": 50}
    out = enrich_with_volume_analysis(ind, _candles())
    assert out["rsi14"] == 50
    assert "volumeAnalysis" in out


def test_empty_candles_are_safe():
    prof = volume_profile([])
    assert prof["poc"] is None

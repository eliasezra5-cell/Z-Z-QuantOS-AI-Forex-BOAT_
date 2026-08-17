"""Unit tests for economic surprise normalization + gold impact (extended).

Covers surprise_normalization z-scoring, event scaling, gold_impact direction
heuristics and the ai_impact_analysis gold/surprise surface. No network calls.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_econ_extended")

import math  # noqa: E402
import statistics  # noqa: E402

from app.modules.economic.engine import (  # noqa: E402
    EVENTS,
    ai_impact_analysis,
    gold_impact,
    surprise_normalization,
)

CPI = {"id": "cpi", "name": "Consumer Price Index", "currency": "USD", "country": "US", "impact": 3}
NFP = {"id": "nfp", "name": "Non-Farm Payrolls", "currency": "USD", "country": "US", "impact": 3}


def test_z_score_matches_manual_computation():
    hist = [0.05, -0.02, 0.03, 0.01, -0.01]
    actual, forecast = 3.3, 3.2
    surprise = (actual - forecast) / abs(forecast)
    mean = statistics.mean(hist)
    std = statistics.pstdev(hist)
    expected_z = (surprise - mean) / std
    result = surprise_normalization(CPI, actual, forecast, hist_events=hist)
    assert result["zScore"] == round(expected_z, 4)
    assert result["dispersion"] == round(std / abs(mean), 4)


def test_std_dev_zero_falls_back_to_one():
    hist = [0.1, 0.1, 0.1]
    result = surprise_normalization(CPI, 3.3, 3.2, hist_events=hist)
    assert result["zScore"] == round(((3.3 - 3.2) / 3.2) - 0.1, 4)
    assert result["dispersion"] == 0


def test_high_impact_event_scales_up():
    low_event = {"id": "ppi", "name": "PPI", "currency": "USD", "impact": 1}
    high = surprise_normalization(CPI, 3.3, 3.2)
    low = surprise_normalization(low_event, 3.3, 3.2)
    assert high["eventScale"] == 1.0
    assert low["eventScale"] == 0.3
    assert high["normalizedImpact"] > low["normalizedImpact"]


def test_regime_adjustment_applies_for_risk_on_off():
    norm = surprise_normalization(CPI, 3.3, 3.2, market_regime="risk_off")
    assert norm["regimeAdjustment"] == 0.7


def test_gold_impact_cpi_beat_is_bearish():
    out = gold_impact(CPI, 3.4, 3.2)
    assert out["goldDirection"] == "bearish"
    assert out["goldImpact"] < 0
    assert out["magnitude"] > 0


def test_gold_impact_nfp_miss_is_bullish():
    out = gold_impact(NFP, 170, 185)
    assert out["goldDirection"] == "bullish"
    assert out["goldImpact"] > 0


def test_gold_impact_geopolitics_is_bullish():
    geo = {"id": "geo-test", "name": "Conflict escalation", "currency": "USD", "impact": 3, "category": "geopolitics"}
    out = gold_impact(geo, 100, 90)
    assert out["goldDirection"] == "bullish"
    assert out["goldImpact"] > 0


def test_ai_impact_includes_zscore_and_gold_fields():
    out = ai_impact_analysis(CPI, 3.4, 3.2)
    assert "zScore" in out
    assert "goldImpact" in out
    assert out["goldImpact"]["goldDirection"] == "bearish"
    for key in ("surprise", "volatilityExpectation", "direction", "confidence", "surprisePct", "expectedVolatility", "impactScore", "normalizedImpact"):
        assert key in out


def test_seeded_event_uses_gold_aware_analysis():
    ev = EVENTS[0]
    ai = ai_impact_analysis(ev, 3.4, 3.2)
    assert "goldImpact" in ai
    assert math.isfinite(ai["goldImpact"]["goldImpact"])

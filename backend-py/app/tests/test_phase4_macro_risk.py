"""Tests for Phase 4 (Batch 11+14): regime detector, yield curve, cross-asset analysis, Kelly + structure sizing."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_phase4_test")

from app.modules.macro.engine import cross_asset_analysis, detect_regime, get_macro_snapshot, yield_curve_shape  # noqa: E402
from app.modules.risk.deterministic import PositionSizer  # noqa: E402


# ---- Batch 11: regime ----
def test_regime_labels_are_valid():
    for _ in range(20):
        reg = detect_regime()
        assert reg["regime"] in ("risk_on", "risk_off", "transitional", "crisis")
        assert -1.0 <= reg["score"] <= 1.0
        assert isinstance(reg["factors"], dict)


def test_regime_crisis_on_high_recession():
    snapshot = get_macro_snapshot()
    snapshot["indicators"] = {**snapshot["indicators"], "recessionProbability": 60, "vix": 40}
    reg = detect_regime(snapshot)
    assert reg["regime"] == "crisis"


def test_regime_risk_on_low_vol():
    snapshot = get_macro_snapshot()
    snapshot["indicators"] = {**snapshot["indicators"], "recessionProbability": 10, "vix": 12, "marketBreadth": 80}
    snapshot["riskOn"] = True
    reg = detect_regime(snapshot)
    assert reg["regime"] == "risk_on"


# ---- Batch 11: yield curve ----
def test_yield_curve_shapes():
    snapshot = get_macro_snapshot()
    snapshot["bondYields"] = {"us10y": 4.0, "us2y": 4.5}
    assert yield_curve_shape(snapshot)["shape"] == "inverted"
    snapshot["bondYields"] = {"us10y": 4.5, "us2y": 4.0}
    assert yield_curve_shape(snapshot)["shape"] == "normal"
    snapshot["bondYields"] = {"us10y": 4.2, "us2y": 4.1}
    assert yield_curve_shape(snapshot)["shape"] == "flat"


# ---- Batch 11: cross-asset dollar/oil/bond ----
def test_cross_asset_analysis_structure():
    ca = cross_asset_analysis()
    assert set(ca.keys()) >= {"dollar", "oil", "bonds", "macroBias", "biasScore", "alignsWithRegime"}
    assert ca["dollar"]["trend"] in ("rising", "falling", "flat")
    assert ca["oil"]["bias"] in ("bullish", "bearish", "neutral")
    assert ca["macroBias"] in ("risk_on", "risk_off", "neutral")
    assert isinstance(ca["alignsWithRegime"], bool)


def test_cross_asset_rising_dollar_is_risk_off():
    snapshot = get_macro_snapshot()
    snapshot["dollarIndex"] = [100.0] * 10 + [104.0] * 10
    snapshot["bondYields"] = {"us10y": 4.0, "us2y": 4.5}
    ca = cross_asset_analysis(snapshot)
    assert ca["dollar"]["trend"] == "rising"
    assert ca["macroBias"] == "risk_off"


def test_cross_asset_falling_dollar_is_risk_on():
    snapshot = get_macro_snapshot()
    snapshot["dollarIndex"] = [104.0] * 10 + [100.0] * 10
    snapshot["bondYields"] = {"us10y": 4.5, "us2y": 4.0}
    ca = cross_asset_analysis(snapshot)
    assert ca["dollar"]["trend"] == "falling"
    assert ca["macroBias"] == "risk_on"


def test_macro_snapshot_has_cross_asset():
    assert "crossAsset" in get_macro_snapshot()


# ---- Batch 14: Kelly + structure sizing ----
def test_kelly_criterion_bounded():
    kelly = PositionSizer.kelly_criterion(win_rate=0.6, avg_win=100, avg_loss=50, equity=10000, fraction=0.5)
    assert 0.0 <= kelly <= 0.25


def test_kelly_zero_without_edge():
    kelly = PositionSizer.kelly_criterion(win_rate=0.3, avg_win=50, avg_loss=100, equity=10000)
    assert kelly == 0.0


def test_kelly_guard_avg_loss_nonpositive():
    kelly = PositionSizer.kelly_criterion(win_rate=0.8, avg_win=50, avg_loss=0, equity=10000)
    assert kelly == 0.01


def test_structure_based_sizing():
    vol = PositionSizer.structure_based(equity=10000, risk_percent=1.0, structure_pips=50, symbol="XAUUSD")
    assert vol > 0
    assert isinstance(vol, float)


def test_size_dispatch_kelly():
    vol = PositionSizer.size("kelly_criterion", {"winRate": 0.55, "avgWin": 80, "avgLoss": 60, "equity": 10000})
    assert vol > 0


def test_size_dispatch_structure():
    vol = PositionSizer.size("structure_based", {"equity": 10000, "riskPercent": 1.0, "structurePips": 40, "symbol": "XAUUSD"})
    assert vol > 0

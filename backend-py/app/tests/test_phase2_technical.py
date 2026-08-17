"""Tests for Phase 2 (Batch 07/08/09): Williams %R, Volume MA, confluence levels, SMC guards/metadata, parallel agents."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_phase2_test")

import pytest  # noqa: E402

from app.modules.technical.indicators import calculate_all_indicators, volume_ma, williams_r  # noqa: E402
from app.modules.technical.price_action import _confluence_levels, analyze_price_action  # noqa: E402
from app.modules.technical.smc import Confirmation, analyze_smc, smc_metadata  # noqa: E402


def _candles(n=60, step=1.0):
    out = []
    for i in range(n):
        price = 100.0 + i * step
        out.append({
            "open": price - 0.1,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": 1000 + (i % 7) * 100,
            "time": (1700000000 + i * 3600) * 1000,
        })
    return out


# ---- Batch 08: Williams %R + Volume MA ----
def test_williams_r_warmup_and_range():
    out = williams_r(_candles())
    assert out[0] is None
    assert out[12] is None
    assert out[13] is not None
    assert all(-100 <= v <= 0 for v in out if v is not None)


def test_williams_r_extremes():
    candles = _candles(20)
    lowest_low = min(c["low"] for c in candles[-14:])
    candles[-1] = {**candles[-1], "close": lowest_low}
    out = williams_r(candles, 14)
    assert out[-1] == -100.0


def test_volume_ma_length_and_warmup():
    candles = _candles()
    vma = volume_ma(candles, 20)
    assert vma[19] is not None
    assert all(v is None for v in vma[:19])


def test_calculate_all_indicators_includes_new_fields():
    ind = calculate_all_indicators(_candles(60))
    assert "williamsR14" in ind
    assert ind["williamsR14"] is not None
    assert "volumeMa20" in ind
    assert ind["volumeMa20"] is not None


# ---- Batch 08: confluence support/resistance ----
def test_confluence_levels_sources_present():
    candles = _candles()
    price = candles[-1]["close"]
    levels = _confluence_levels(candles, price)
    sources = {lv["source"] for lv in levels}
    assert "roundNumber" in sources
    assert "pivot" in sources
    assert "bollinger" in sources
    assert "volumeProfile" in sources


def test_confluence_levels_include_round_number():
    candles = _candles()
    price = candles[-1]["close"]
    levels = _confluence_levels(candles, price)
    rounds = [lv for lv in levels if lv["source"] == "roundNumber"]
    assert rounds and all(abs(lv["price"] - round(lv["price"])) < 1e-9 for lv in rounds)


def test_price_action_has_confluence_levels():
    pa = analyze_price_action(_candles(60))
    assert "confluenceLevels" in pa
    assert isinstance(pa["confluenceLevels"], list)


# ---- Batch 09: Confirmation enum + guards + deterministic metadata ----
def test_confirmation_enum_values():
    assert Confirmation("confirmed") == "confirmed"
    assert Confirmation("wait_for_retest").value == "wait_for_retest"
    assert Confirmation.NO_VALID_ENTRY.value == "no_valid_entry"


def test_analyze_smc_metadata_present():
    smc = analyze_smc(_candles(60))
    md = smc["metadata"]
    assert md["warmUp"]["met"] is True
    assert md["repaintGuard"]["usesOnlyClosedCandles"] is True
    assert md["backtestable"] is True
    assert "generatedAt" in md
    assert "freshness" in md and "lastCandleAgeSeconds" in md["freshness"]
    assert "timeframeConflict" in md


def test_analyze_smc_warmup_not_met():
    smc = analyze_smc(_candles(20))
    assert smc["metadata"]["warmUp"]["met"] is False


def test_analyze_smc_confirmation_is_enum():
    smc = analyze_smc(_candles(60))
    try:
        Confirmation(smc["confirmation"]["confirmation"])
    except ValueError:
        pytest.fail("confirmation value not a valid Confirmation enum member")


def test_smc_metadata_conflict_detection():
    md = smc_metadata(_candles(60), "bearish", [], {"direction": "up", "type": "BOS", "index": 1, "price": 1.0}, None)
    assert md["timeframeConflict"]["detected"] is True


# ---- Batch 07: EFX/EAX expected-move fields ----
def test_expected_move_has_efx_eax():
    from app.modules.ai.decision_center import build_context, expected_move_distribution

    context = build_context("EURUSD")
    em = expected_move_distribution("EURUSD", context)
    assert "efx" in em
    assert "eax" in em
    assert em["efx"] is not None and em["eax"] is not None
    assert em["eax"] > 0


def test_analyze_symbol_async_parallel():
    import asyncio

    from app.modules.ai.decision_center import analyze_symbol_async

    decision = asyncio.run(analyze_symbol_async("EURUSD"))
    assert decision["symbol"] == "EURUSD"
    assert decision["consensus"]["direction"] in ("buy", "sell", "neutral")
    assert len(decision["agents"]) == 7
    assert "expectedMove" in decision

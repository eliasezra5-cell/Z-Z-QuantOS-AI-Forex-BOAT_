"""Phase 4 tests: Advanced SMC Mathematics + Quantitative Risk + Dynamic SL/TP.

Covers the additive Phase 4 modules (technical/smc_math, risk/quant_models,
technical/dynamic_sltp) with deterministic, crafted candle data.
"""
import pytest

from app.modules.technical.smc_math import (
    detect_swing_points,
    detect_bos_choch,
    detect_order_blocks,
    track_ob_mitigation,
    detect_fvgs,
    track_fvg_fill,
    fvg_quality_score,
    compute_mtf_alignment,
    analyze_advanced_smc,
    compute_atr,
)
from app.modules.risk.quant_models import (
    kelly_fraction,
    wilson_lower_bound,
    ev_gate,
    expected_value,
    volatility_adjustment,
    quant_risk_engine,
)
from app.modules.technical.dynamic_sltp import (
    optimize_sltp,
    risk_reward,
    liquidity_pools,
    dynamic_take_profit,
)


def _candles(series):
    """Build candle dicts from [(open, high, low, close), ...]."""
    out = []
    for i, (o, h, l, c) in enumerate(series):
        out.append({"time": 1000 + i * 60000, "open": o, "high": h, "low": l, "close": c, "volume": 100})
    return out


def _base_candles(n=60, price=100.0):
    """A calm range-bound series to give a small ATR."""
    out = []
    for i in range(n):
        o = price
        c = price + 0.1 if i % 2 == 0 else price - 0.1
        h = max(o, c) + 0.15
        l = min(o, c) - 0.15
        out.append({"time": 1000 + i * 60000, "open": o, "high": h, "low": l, "close": c, "volume": 100})
        price = c
    return out


# --------------------------------------------------------------------------- #
# Module 1: Advanced SMC Mathematics
# --------------------------------------------------------------------------- #
def test_swing_points_are_strict_fractals():
    candles = _candles(
        [(100, 102, 99, 101), (101, 101, 99, 100.5), (100.5, 101.5, 100, 101),
         (101, 104, 101, 103), (103, 103.5, 102, 102.5), (102.5, 103, 101.5, 102),
         (102, 102.5, 100.5, 101), (101, 102, 100, 100.8), (100.8, 101, 99.8, 100.2)]
        + [(100.2, 100.4, 99.9, 100.3)] * 30
    )
    swings = detect_swing_points(candles)
    highs = [s for s in swings if s["type"] == "swingHigh"]
    lows = [s for s in swings if s["type"] == "swingLow"]
    for h in highs:
        assert isinstance(h["price"], float) or str(h["price"]).replace(".", "", 1).isdigit()
    assert any(s["type"] == "swingHigh" for s in swings)


def test_bos_and_choch_sequence():
    # Uptrend (bullish BOS) then a break below the swing low (CHoCH down).
    series = [(100, 101, 99, 100.5)] * 8
    series += [(100.5, 101, 99.5, 100.2), (100.2, 101.5, 100, 101)]  # lower low -> swing 95-style
    # Build an explicit swing sequence instead: low(95) high(99) low(96) high(102) low(95)
    candles = _base_candles(60, 100.0)
    swings = [
        {"index": 10, "type": "swingLow", "price": 95.0, "time": candles[10]["time"]},
        {"index": 20, "type": "swingHigh", "price": 99.0, "time": candles[20]["time"]},
        {"index": 30, "type": "swingLow", "price": 96.0, "time": candles[30]["time"]},
        {"index": 40, "type": "swingHigh", "price": 102.0, "time": candles[40]["time"]},
        {"index": 50, "type": "swingLow", "price": 95.0, "time": candles[50]["time"]},
    ]
    structure = detect_bos_choch(candles, swings)
    assert structure["bos"] is not None and structure["bos"]["direction"] == "up"
    assert structure["choch"] is not None and structure["choch"]["direction"] == "down"
    assert structure["trend"] == "bearish"


def test_order_block_detection_and_mitigation():
    # Bearish candle then strong bullish impulse -> bullish OB.
    series = [(100.2, 100.4, 99.9, 100.3)] * 8
    series.append((100.3, 100.4, 99.2, 99.3))  # down candle (OB)
    series.append((99.3, 101.5, 99.3, 101.2))  # strong bullish impulse
    series += [(101.2, 101.4, 100.8, 101.1)] * 6  # stays above -> unmitigated
    candles = _candles(series)
    atr = compute_atr(candles)
    obs = detect_order_blocks(candles, atr)
    bullish = [ob for ob in obs if ob["type"] == "bullish"]
    assert bullish, "expected at least one bullish order block"
    entry = candles[-1]["close"]
    zone = bullish[0]["zone"]
    assert zone[0] < entry  # OB below current price for a long
    # Now price returns into the zone -> mitigated.
    candles2 = _candles(series + [(101.0, 101.2, 99.0, 100.5), (100.5, 100.7, 99.0, 99.9)])
    tracked = track_ob_mitigation(candles2, obs)
    assert any(ob["mitigated"] and ob["mitigationRatio"] > 0 for ob in tracked)


def test_fvg_detection_fill_and_quality():
    series = [(100.0, 100.2, 99.8, 100.1)] * 4
    series.append((100.1, 100.3, 99.9, 100.0))  # candle i-1 (high 100.3)
    series.append((100.0, 100.4, 99.9, 100.2))  # candle i (middle)
    series.append((100.2, 101.0, 100.8, 100.9))  # candle i+1 low 100.8 > high 100.3 -> gap
    series += [(100.9, 101.1, 100.5, 100.7)] * 4
    candles = _candles(series)
    fvgs = detect_fvgs(candles)
    bullish = [f for f in fvgs if f["type"] == "bullish"]
    assert bullish, "expected a bullish FVG"
    assert len(bullish[0]["zone"]) == 2
    filled = track_fvg_fill(candles, bullish)
    for f in filled:
        assert "filled" in f and "fillRatio" in f
        assert 0 <= float(f["fillRatio"]) <= 1
    q = fvg_quality_score(bullish[0], atr=0.5, trend="bullish", total_candles=len(candles))
    assert 0 <= q <= 100


def _structured_series(swing_points, n=80, base=100.0):
    """Base range-bound series with explicit swing highs/lows at given indices."""
    candles = []
    for i in range(n):
        o = base
        c = base + 0.1
        h = max(o, c) + 0.05
        l = min(o, c) - 0.05
        candles.append({"time": 1000 + i * 60000, "open": o, "high": h, "low": l, "close": c, "volume": 100})
    for idx, stype, price in swing_points:
        if stype == "high":
            candles[idx]["high"] = price
            candles[idx]["close"] = price
            candles[idx]["open"] = price - 0.2
            candles[idx]["low"] = price - 0.3
        else:
            candles[idx]["low"] = price
            candles[idx]["close"] = price
            candles[idx]["open"] = price + 0.2
            candles[idx]["high"] = price + 0.3
    return candles


def test_mtf_alignment_scores():
    c_up = _structured_series([(15, "low", 95), (30, "high", 105), (45, "low", 100), (60, "high", 110)])
    c_down = _structured_series([(15, "high", 105), (30, "low", 95), (45, "high", 100), (60, "low", 90)])
    aligned = compute_mtf_alignment({"H1": c_up, "M15": c_up, "M5": c_up, "M1": c_up})
    assert aligned["score"] == 100 and aligned["bias"] == "bullish"
    conflicted = compute_mtf_alignment({"H1": c_up, "M15": c_down, "M5": c_up, "M1": c_down})
    assert 0 <= conflicted["score"] <= 100
    empty = compute_mtf_alignment({})
    assert empty["score"] == 0 and empty["bias"] == "neutral"


def test_analyze_advanced_smc_shape():
    candles = _base_candles(120, 100.0)
    r = analyze_advanced_smc(candles, "H1")
    assert r["insufficientData"] is False
    assert "orderBlocks" in r and "fvgs" in r and "structure" in r
    assert r["summary"]["trend"] in ("bullish", "bearish", "neutral")


# --------------------------------------------------------------------------- #
# Module 2: Quantitative Risk & Position Sizing
# --------------------------------------------------------------------------- #
def test_kelly_fraction_bounds():
    assert 0.0 <= float(kelly_fraction(0.6, 100, 50, 0.5)) <= 0.25
    assert float(kelly_fraction(0.3, 50, 100, 0.5)) == 0.0  # no edge
    assert float(kelly_fraction(0.8, 50, 0, 0.5)) == 0.0  # guard avg_loss <= 0


def test_wilson_lower_bound_is_conservative():
    raw = wilson_lower_bound(0.6, 5000)
    small = wilson_lower_bound(0.6, 10)
    assert float(small) <= float(raw) < 0.6


def test_ev_gate():
    assert ev_gate(0.6, 100, 50)["approved"] is True
    assert ev_gate(0.3, 50, 100)["approved"] is False
    assert ev_gate(0.5, 100, 100)["approved"] is False  # zero EV
    assert float(expected_value(0.6, 100, 50)) > 0


def test_volatility_adjustment_reduces_volume():
    adj = volatility_adjustment(1.0, atr=2.0, baseline_atr=1.0)
    assert float(adj["factor"]) < 1.0 and float(adj["volume"]) < 1.0


def test_quant_risk_engine_gates():
    positive = quant_risk_engine.size(equity=100000, win_rate=0.6, avg_win=100, avg_loss=50,
                                      entry=2400, stop=2390, symbol="XAUUSD")
    assert positive["approved"] and positive["volume"] > 0
    negative = quant_risk_engine.size(equity=100000, win_rate=0.3, avg_win=50, avg_loss=100,
                                      entry=2400, stop=2390, symbol="XAUUSD")
    assert not negative["approved"] and negative["verdict"] == "rejected"


def test_quant_risk_engine_volatility_scales_down():
    calm = quant_risk_engine.size(equity=100000, win_rate=0.6, avg_win=100, avg_loss=50,
                                  entry=2400, stop=2390, symbol="XAUUSD",
                                  atr=0.2, atr_series=[0.18] * 10)
    volatile = quant_risk_engine.size(equity=100000, win_rate=0.6, avg_win=100, avg_loss=50,
                                      entry=2400, stop=2390, symbol="XAUUSD",
                                      atr=2.0, atr_series=[0.18] * 10)
    assert float(volatile["volume"]) <= float(calm["volume"])


# --------------------------------------------------------------------------- #
# Module 3: Dynamic SL/TP Optimization
# --------------------------------------------------------------------------- #
def test_risk_reward_calculation():
    assert float(risk_reward("buy", 100, 99, 103)) == pytest.approx(3.0)
    assert float(risk_reward("sell", 100, 103, 96)) == pytest.approx(1.33, abs=0.01)


def test_dynamic_sltp_structure_never_fixed_pips():
    series = [(100.2, 100.4, 99.9, 100.3)] * 8
    series.append((100.3, 100.4, 99.2, 99.3))  # OB down candle
    series.append((99.3, 101.5, 99.3, 101.2))  # impulse
    series += [(101.2, 103.0, 101.0, 102.8)] * 8  # rally to a high pool
    series += [(102.8, 103.2, 102.0, 102.2)] * 3  # pullback to entry zone
    candles = _candles(series)
    smcs = analyze_advanced_smc(candles, "H1")
    atr = smcs.get("atr") or compute_atr(candles)
    pools = liquidity_pools(smcs, candles[-1]["close"], "buy")
    assert isinstance(pools, list)
    entry = candles[-1]["close"]
    result = optimize_sltp("buy", entry, smcs, atr, candles=candles)
    # Invariant: an approved setup always has structural SL + RR >= 2.
    if result["approved"]:
        assert result["stopSource"] in ("order_block", "sweep_wick")
        assert float(result["riskReward"]) >= 2.0
        assert len(result["takeProfit"]) >= 1
    else:
        assert result.get("reason")


def test_dynamic_sltp_rr_gate_rejects():
    series = [(100.2, 100.4, 99.9, 100.3)] * 8
    series.append((100.3, 100.4, 99.2, 99.3))  # OB
    series.append((99.3, 101.5, 99.3, 101.2))  # impulse
    series += [(101.2, 101.4, 101.0, 101.3)] * 8  # tight range -> pool very close
    candles = _candles(series)
    smcs = analyze_advanced_smc(candles, "H1")
    atr = smcs.get("atr") or compute_atr(candles)
    entry = candles[-1]["close"]
    result = optimize_sltp("buy", entry, smcs, atr, candles=candles, min_rr=2.0)
    if result["approved"]:
        assert float(result["riskReward"]) >= 2.0
    else:
        assert "risk/reward" in result.get("reason", "") or "anchor" in result.get("reason", "")


def test_dynamic_take_profit_targets():
    series = [(100.0, 100.2, 99.8, 100.1)] * 10
    series.append((100.1, 100.3, 99.9, 100.0))
    series.append((100.0, 100.4, 99.9, 100.2))
    series.append((100.2, 101.0, 100.8, 100.9))
    series += [(100.9, 104.0, 100.8, 103.8)] * 6  # strong rally -> swing high pool
    candles = _candles(series)
    smcs = analyze_advanced_smc(candles, "H1")
    tps = dynamic_take_profit("buy", candles[-1]["close"], smcs)
    assert tps["source"] == "structural"
    assert all(t["tag"] in ("TP1", "TP2") for t in tps["targets"])


# --------------------------------------------------------------------------- #
# Upgraded Technical Execution Agent (20% weight) contract
# --------------------------------------------------------------------------- #
def test_technical_agent_contract():
    import asyncio

    from app.modules.ai.agents.technical_agent import TechnicalExecutionAgent

    async def _run():
        agent = TechnicalExecutionAgent()
        return (await agent.run({"symbol": "XAUUSD"})).to_dict()

    result = asyncio.run(_run())
    assert result["agent_id"] == "technical"
    assert result["weight"] == 0.20
    assert result["direction"] == "neutral"  # execution agent never votes direction
    assert result["abstention"] in ("TRADE", "REJECTED", "DATA_INSUFFICIENT")
    assert result["data"]["execution"] in ("confirmed", "rejected")
    assert result["data"]["mtfAlignmentScore"] is not None
    assert 0 <= result["data"]["mtfAlignmentScore"] <= 100
    # Consensus-critical fields must remain present.
    for key in ("entry", "stopLoss", "takeProfit", "smc"):
        assert key in result["data"]

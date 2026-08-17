"""Tests for the Backtesting Engine extensions (Phase 2, Module 3).

Covers the look-ahead-safe TradeSimulator (spread/slippage/commission) and
year-based walk-forward analysis.

Run with: python3 -m pytest app/tests/test_backtest_phase2.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_backtest_phase2_test")

from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402

from app.modules.backtest.trade_simulator import TradeSimulator, simulate  # noqa: E402
from app.modules.backtest.walk_forward_analysis import (  # noqa: E402
    split_by_year,
    build_signals,
    walk_forward_analysis,
    _year_of,
)


def _bars(n, start_year=2020, step_ms=3600000, start=100.0, step=0.05):
    bars = []
    base_t = int(__import__("datetime").datetime(start_year, 1, 1, 0, 0, tzinfo=__import__("datetime").timezone.utc).timestamp() * 1000)
    price = start
    for i in range(n):
        o = price
        c = price + step
        bars.append({
            "time": base_t + i * step_ms,
            "open": o,
            "high": c + 0.05,
            "low": o - 0.05,
            "close": c,
            "volume": 1000,
        })
        price = c
    return bars


# --------------------------------------------------------------------------- #
# TradeSimulator: spread / slippage / commission
# --------------------------------------------------------------------------- #
def test_simulator_applies_spread_and_slippage_on_entry():
    bars = _bars(10)
    sim = TradeSimulator("TEST", spread=Decimal("0.10"), slippage=Decimal("0.05"),
                         commission_per_lot=Decimal("1.0"), volume=Decimal("1"))
    sim.step(bars[0], "flat")
    sim.step(bars[1], "buy")
    entry = sim.position["entryPrice"]
    expected = Decimal(str(bars[1]["close"])) + Decimal("0.10") / 2 + Decimal("0.05")
    assert entry == round(expected, 5)


def test_simulator_deducts_commission_on_close():
    bars = _bars(5, start=100.0, step=0.0)
    sim = TradeSimulator("TEST", spread=Decimal("0"), slippage=Decimal("0"),
                         commission_per_lot=Decimal("10.0"), volume=Decimal("1"))
    sim.step(bars[0], "flat")
    sim.step(bars[1], "buy")
    closes = sim.step(bars[2], "flat")  # exits at close (no SL/TP hit)
    assert len(closes) == 1
    assert closes[0]["commission"] == 10.0
    assert sim.trades[0]["profit"] == -10.0  # flat market -> only commission


def test_simulator_exits_on_stop_loss_and_take_profit():
    bars = [
        {"time": 1_600_000_000_000, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        {"time": 1_600_000_3600_000, "open": 100, "high": 100, "low": 99.5, "close": 100, "volume": 1000},
        {"time": 1_600_000_7200_000, "open": 100, "high": 100, "low": 98, "close": 99, "volume": 1000},
    ]
    sim = TradeSimulator("TEST", spread=Decimal("0"), slippage=Decimal("0"),
                         commission_per_lot=Decimal("0"), volume=Decimal("1"))
    sim.step(bars[0], "flat")
    sim.step(bars[1], "buy")  # entry at 100
    closes = sim.step(bars[2], "flat")
    assert len(closes) == 1
    assert closes[0]["reason"] == "SL"


def test_simulator_no_future_access():
    bars = _bars(20)
    signals = {5: "buy", 15: "flat"}
    sim = simulate(signals, bars, symbol="TEST", spread=Decimal("0.0001"), commission_per_lot=Decimal("0"))
    # Trade must have been entered at index 5, closed at or after 5.
    assert len(sim.trades) >= 1
    assert all(t["entryIndex"] == 5 for t in sim.trades)
    assert all(t["exitIndex"] >= 5 for t in sim.trades)


def test_simulate_rejects_out_of_range_signal_index():
    bars = _bars(10)
    with pytest.raises(ValueError):
        simulate({50: "buy"}, bars, symbol="TEST")


def test_simulate_requires_time_field():
    bars = _bars(10)
    for b in bars:
        b.pop("time")
    with pytest.raises(ValueError):
        simulate({1: "buy"}, bars, symbol="TEST")


def test_simulator_results_shape():
    bars = _bars(30)
    sim = simulate({3: "buy", 10: "sell"}, bars, symbol="TEST", initial_capital=Decimal("100000"))
    res = sim.results()
    for key in ("initialCapital", "finalCapital", "netProfit", "returnPct", "totalTrades", "winRate", "profitFactor", "maxDrawdown", "equityCurve", "trades"):
        assert key in res
    assert res["initialCapital"] == 100000.0


# --------------------------------------------------------------------------- #
# Walk-forward analysis
# --------------------------------------------------------------------------- #
def test_split_by_year():
    bars = _bars(2000, start_year=2020)  # ~83 days at H1
    buckets = split_by_year(bars)
    assert buckets[0][0] == 2020
    assert all(y == 2020 for y, _ in buckets)


def test_split_by_year_multi_year():
    bars = _bars(9000, start_year=2020)  # 9000 H1 bars spans into 2021
    buckets = split_by_year(bars)
    years = [y for y, _ in buckets]
    assert 2020 in years and 2021 in years


def test_year_of_returns_year():
    import datetime as dt
    ms = int(dt.datetime(2021, 6, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    assert _year_of(ms) == 2021
    assert _year_of(None) is None


def test_build_signals_deterministic():
    bars = _bars(200)
    s1 = build_signals(bars, "trend-follow")
    s2 = build_signals(bars, "trend-follow")
    assert s1 == s2


def test_walk_forward_insufficient_years():
    bars = _bars(8760, start_year=2020)  # only ~2 years
    res = walk_forward_analysis(bars, strategy="trend-follow", train_years=3)
    assert "error" in res
    assert res["error"] == "insufficient years"


def test_walk_forward_runs_windows():
    # ~5 years of H1 bars (45,000 bars) -> at least train(3)+test(1) windows
    bars = _bars(45000, start_year=2020)
    res = walk_forward_analysis(bars, strategy="trend-follow", train_years=3,
                                symbol="TEST", pip=Decimal("0.01"))
    assert "windows" in res
    assert len(res["windows"]) >= 1
    assert res["verdict"] in ("robust", "overfit", "unprofitable")
    first = res["windows"][0]
    assert first["testYear"] >= 2023
    assert set(first["test"].keys()) >= {"netProfit", "returnPct", "winRate", "profitFactor", "maxDrawdown", "totalTrades"}

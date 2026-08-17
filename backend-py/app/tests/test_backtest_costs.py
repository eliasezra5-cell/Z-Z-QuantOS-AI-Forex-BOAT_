"""Tests for backtest execution costs, gap simulation and regime-stratified CV.

Run with: python3 -m pytest app/tests/test_backtest_costs.py -q
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_backtest_costs")

from app.modules.backtest.engine import run_backtest, simulate_gap  # noqa: E402
from app.modules.backtest.advanced import regime_separated_cv  # noqa: E402
from app.modules.marketdata.engine import generate_candles  # noqa: E402


def _rising_candles(n, start=100.0, step=0.1):
    candles = []
    price = start
    base_t = 1_700_000_000_000
    for i in range(n):
        o = price
        c = price + step
        candles.append({
            "time": base_t + i * 3600000,
            "open": o,
            "high": c + 0.05,
            "low": o - 0.05,
            "close": c,
            "volume": 1000,
        })
        price = c
    return candles


def test_costs_reduce_equity():
    # BTCUSD has no yahoo mapping -> generate_candles is always synthetic, so
    # both runs share an identical, pre-generated candle series. Mocking the
    # candle source keeps the two runs byte-for-byte identical even when
    # background market-data threads consume the global RNG concurrently
    # (which would otherwise break random.seed() determinism).
    #
    # slippage is intentionally omitted here: it shifts the effective entry
    # (and therefore the derived SL/TP levels), which legitimately changes the
    # trade path. commission + swap only ever reduce profit on an identical
    # trade path, so the two runs open the exact same trades and the costs
    # strictly reduce the final capital.
    candles = generate_candles("BTCUSD", "H1", 400)
    base_params = {"symbol": "BTCUSD", "strategy": "trend-follow", "candles": 400}
    costly_params = {
        "symbol": "BTCUSD",
        "strategy": "trend-follow",
        "candles": 400,
        "commissionPerLot": 5.0,
        "swapPerLotPerDay": 0.1,
    }
    with mock.patch("app.modules.backtest.engine.generate_candles", return_value=candles):
        base = run_backtest(base_params)
        costly = run_backtest(costly_params)
    assert base["totalTrades"] == costly["totalTrades"]
    assert costly["finalCapital"] < base["finalCapital"]
    assert costly["costs"]["commissionPerLot"] == 5.0
    assert costly["costs"]["swapPerLotPerDay"] == 0.1


def test_simulate_gap_records_gap_filled():
    candles = _rising_candles(61)
    entry_bar = candles[-1]
    gap_open = round(entry_bar["close"] * 0.94, 5)
    candles.append({
        "time": entry_bar["time"] + 3600000,
        "open": gap_open,
        "high": gap_open + 0.05,
        "low": gap_open - 1.0,
        "close": gap_open + 0.3,
        "volume": 1000,
    })
    res = simulate_gap(candles, 0.01)
    gaps = res.get("gaps") or []
    gap_filled = [g for g in gaps if g.get("type") == "gapFilled"]
    assert len(gap_filled) >= 1
    assert any(g.get("trigger") == "SL" for g in gap_filled)
    assert gap_filled[0]["fillPrice"] == gap_open


def test_simulate_gap_no_gap_no_event():
    candles = _rising_candles(65)
    res = simulate_gap(candles, 0.05)
    assert (res.get("gaps") or []) == []


def test_regime_cv_stratified():
    labels = (["A"] * 10) + (["B"] * 10) + (["C"] * 10)
    data = ([{"return": 5.0}] * 10) + ([{"return": 3.0}] * 10) + ([{"return": -2.0}] * 10)
    res = regime_separated_cv(data, labels, k=5)
    assert res["n_splits"] == 5
    assert len(res["splits"]) == 5
    assert res["stratified"] is True
    assert "verdict" in res
    for s in res["splits"]:
        assert set(s["test_regimes"]) == {"A", "B", "C"}
        assert set(s["train_regimes"]) == {"A", "B", "C"}
        assert all(v >= 1 for v in s["test_regime_counts"].values())
        assert s["metrics"]["testRegimeCount"] == 3


def test_regime_cv_mismatched_labels():
    try:
        regime_separated_cv([1, 2, 3], ["A"])
    except ValueError:
        return
    raise AssertionError("expected ValueError on label/data length mismatch")


def test_run_backtest_defaults_unchanged():
    res = run_backtest({"symbol": "EURUSD", "strategy": "trend-follow", "candles": 200})
    for key in ("finalCapital", "netProfit", "totalTrades", "winRate", "equityCurve", "trades"):
        assert key in res
    assert res.get("gaps") == []
    assert res["costs"]["commissionPerLot"] == 0.0
    assert res["costs"]["slippagePips"] == 0.0

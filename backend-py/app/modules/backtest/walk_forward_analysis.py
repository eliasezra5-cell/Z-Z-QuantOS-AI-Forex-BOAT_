"""Walk-Forward Analysis (Phase 2, Module 3) — additive.

Chronological walk-forward that splits a historical candle series into calendar
years, trains on the first N years and tests on the following year, then rolls
the window forward. This prevents look-ahead bias and detects overfitting the
same way the existing ``backtest.advanced.walk_forward`` does, but operates on
real timestamps so the train/test split is time-based rather than index-based.

The analysis uses the existing strategy signals and the additive
``TradeSimulator`` so spread, slippage and commission are applied on the
test period exactly as they would be in live trading.
"""
from datetime import datetime, timezone
from decimal import Decimal

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from .engine import per_bar_indicators, signal_for
from .trade_simulator import TradeSimulator, _dec


def _year_of(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).year
    except (TypeError, ValueError, OSError):
        return None


def split_by_year(candles):
    """Group candles into chronological year buckets (list of (year, candles))."""
    buckets = {}
    order = []
    for c in candles or []:
        year = _year_of(c.get("time"))
        if year is None:
            continue
        if year not in buckets:
            buckets[year] = []
            order.append(year)
        buckets[year].append(c)
    return [(y, buckets[y]) for y in sorted(order)]


def build_signals(candles, strategy, warmup=60):
    """Deterministic per-bar signals using ONLY bars up to index ``i``."""
    inds = per_bar_indicators(candles)
    signals = {}
    for i in range(warmup, len(candles)):
        sig = signal_for(strategy, candles, i, inds)
        if sig in ("buy", "sell"):
            signals[i] = sig
    return signals


def walk_forward_analysis(candles, strategy="trend-follow", train_years=3,
                          symbol="XAUUSD", pip=Decimal("0.01"), **sim_kwargs):
    """Train on the first ``train_years`` years, test on the following year.

    Returns per-window results plus a verdict: ``robust`` when the average test
    net profit is positive and fewer than half the windows overfit.
    """
    sim_kwargs.setdefault("spread", _dec(sim_kwargs.get("spread", "0.0001")))
    sim_kwargs.setdefault("commission_per_lot", _dec(sim_kwargs.get("commission_per_lot", "0")))
    sim_kwargs.setdefault("slippage", _dec(sim_kwargs.get("slippage", "0")))
    sim_kwargs.setdefault("pip", _dec(pip))

    year_buckets = split_by_year(candles)
    if len(year_buckets) < train_years + 1:
        return {
            "error": "insufficient years",
            "years": [y for y, _ in year_buckets],
            "required_years": train_years + 1,
        }

    windows = []
    for test_pos in range(train_years, len(year_buckets)):
        train_years_list = [c for y, c in year_buckets[test_pos - train_years:test_pos]]
        train_candles = [c for chunk in train_years_list for c in chunk]
        test_year, test_candles = year_buckets[test_pos]

        # --- Train on years 1..N (signals derived from train data only) ---
        train_signals = build_signals(train_candles, strategy)
        train_sim = TradeSimulator(symbol, initial_capital=_dec(sim_kwargs.get("initial_capital", "100000")), **sim_kwargs)
        for i, bar in enumerate(train_candles):
            train_sim.step(bar, train_signals.get(i, "flat"))
        train_sim.forced_close(train_candles[-1], "END")
        train_result = train_sim.results()

        # --- Test on year N+1 (signals from test data only, rolling) ---
        # Simulate warmup on test data so indicators are valid without any
        # train-period look-ahead; entries only start after the warmup.
        test_signals = build_signals(test_candles, strategy)
        test_sim = TradeSimulator(symbol, initial_capital=_dec(sim_kwargs.get("initial_capital", "100000")), **sim_kwargs)
        for i, bar in enumerate(test_candles):
            test_sim.step(bar, test_signals.get(i, "flat"))
        test_sim.forced_close(test_candles[-1], "END")
        test_result = test_sim.results()

        overfit = train_result["netProfit"] > 0 and test_result["netProfit"] < 0
        windows.append({
            "testYear": test_year,
            "trainYears": [y for y, _ in year_buckets[test_pos - train_years:test_pos]],
            "train": {k: train_result[k] for k in ("netProfit", "returnPct", "winRate", "profitFactor", "maxDrawdown", "totalTrades")},
            "test": {k: test_result[k] for k in ("netProfit", "returnPct", "winRate", "profitFactor", "maxDrawdown", "totalTrades")},
            "overfit_signal": overfit,
        })

    avg_test = sum(_dec(w["test"]["netProfit"]) for w in windows) / _dec(len(windows))
    overfit_count = sum(1 for w in windows if w["overfit_signal"])
    robust = avg_test > 0 and overfit_count < len(windows) / 2
    result = {
        "strategy": strategy,
        "trainYears": train_years,
        "windows": windows,
        "average_test_net_profit": float(avg_test),
        "overfit_windows": overfit_count,
        "curve_fitting_detected": overfit_count > 0,
        "verdict": "robust" if robust else ("overfit" if overfit_count >= len(windows) / 2 else "unprofitable"),
    }
    event_bus.emit("backtest:walk-forward", {"strategy": strategy, "verdict": result["verdict"]})
    return result


def init_walk_forward_analysis():
    logger.info("Walk-forward analysis engine initialized (year-based, look-ahead safe)")
    return walk_forward_analysis

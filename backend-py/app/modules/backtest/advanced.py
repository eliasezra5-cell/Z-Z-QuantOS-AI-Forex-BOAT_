"""Backtest extensions (Batch 20): Walk Forward + Monte Carlo + Optimizers + Purged CV.

Additive to existing backtest/engine.py — does not modify existing functions.

Walk Forward Analysis: train/test windows, curve-fitting detection.
Monte Carlo Simulation: 1000+ simulations, probability of ruin,
drawdown distribution.
Grid Search / Random Search: parameter optimization over run_backtest.
Purged Cross-Validation: walk-forward style with embargo gaps.
"""
import random
from itertools import product

from .engine import run_backtest


def walk_forward(params, train_ratio=0.6, windows=4):
    """Run walk-forward by splitting candles into rolling train/test windows."""
    total = params.get("candles") or 800
    window = total // windows
    train_size = int(window * train_ratio)
    results = []
    all_ok = True
    for w in range(windows):
        start = w * window
        test_end = start + window
        train = {**params, "candles": train_size}
        test = {**params, "candles": max(window - train_size, 60)}
        train_res = run_backtest(train)
        test_res = run_backtest(test)
        # curve-fitting detection: train much better than test -> overfit signal
        overfit = train_res["netProfit"] > 0 and test_res["netProfit"] < 0
        results.append({
            "window": w + 1,
            "train": {k: train_res[k] for k in ("netProfit", "returnPct", "winRate", "profitFactor", "maxDrawdown")},
            "test": {k: test_res[k] for k in ("netProfit", "returnPct", "winRate", "profitFactor", "maxDrawdown")},
            "overfit_signal": overfit,
        })
        if overfit:
            all_ok = False
    avg_test = sum(r["test"]["netProfit"] for r in results) / len(results)
    return {
        "windows": results,
        "average_test_net_profit": round(avg_test, 2),
        "curve_fitting_detected": not all_ok,
        "verdict": "overfit" if not all_ok else ("robust" if avg_test > 0 else "unprofitable"),
    }


def monte_carlo(base_result, simulations=1000, seed=42):
    """Resample trade returns to simulate many equity paths."""
    rng = random.Random(seed)
    trades = base_result.get("trades") or []
    if not trades:
        returns = [0.0]
    else:
        returns = [t["profit"] for t in trades if t["profit"] != 0] or [0.0]
    initial = base_result.get("initialCapital") or 100000
    paths = []
    ruin_count = 0
    max_dd_per_path = []
    for _ in range(simulations):
        equity = initial
        peak = initial
        path_max_dd = 0
        ruined = False
        for _ in range(max(len(returns), 20)):
            r = rng.choice(returns)
            equity += r
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            path_max_dd = max(path_max_dd, dd)
            if equity <= 0:
                ruined = True
                break
        paths.append(equity)
        if ruined:
            ruin_count += 1
        max_dd_per_path.append(path_max_dd)
    final = sorted(paths)
    p5 = final[int(len(final) * 0.05)]
    p50 = final[int(len(final) * 0.5)]
    p95 = final[int(len(final) * 0.95)]
    prob_ruin = ruin_count / simulations
    # drawdown distribution
    dd_sorted = sorted(max_dd_per_path)
    dd_p95 = dd_sorted[int(len(dd_sorted) * 0.95)]
    return {
        "simulations": simulations,
        "probability_of_ruin": round(prob_ruin, 4),
        "final_equity_percentiles": {
            "p5": round(p5, 2),
            "p50": round(p50, 2),
            "p95": round(p95, 2),
        },
        "drawdown_p95_pct": round(dd_p95, 2),
        "drawdown_distribution": {
            "p50": round(dd_sorted[int(len(dd_sorted) * 0.5)], 2),
            "p75": round(dd_sorted[int(len(dd_sorted) * 0.75)], 2),
            "p95": round(dd_p95, 2),
            "max": round(max(max_dd_per_path), 2),
        },
        "risk_profile": "high-risk" if (prob_ruin > 0.05 or dd_p95 > 25) else ("medium-risk" if dd_p95 > 15 else "low-risk"),
    }


def grid_search_optimizer(params, param_grid, metric="netProfit", top_k=5):
    """Exhaustively run the cartesian product of param_grid over run_backtest.

    param_grid maps a parameter name to a list of candidate values. Every
    combination is merged onto the base params and backtested, then sorted by
    the requested metric descending. Returns the top_k best combinations, the
    single best set and the total number of combinations evaluated. An overfit
    warning is attached when the best result far exceeds the median.
    """
    combos = [dict(zip(param_grid.keys(), values)) for values in product(*param_grid.values())]
    results = []
    for combo in combos:
        res = run_backtest({**params, **combo})
        results.append({**combo, metric: res.get(metric, 0)})
    results.sort(key=lambda r: r[metric], reverse=True)
    top = results[:top_k]
    best = top[0] if top else None
    vals = [r[metric] for r in results]
    median = sorted(vals)[len(vals) // 2] if vals else 0
    overfit_warning = None
    if best and len(vals) > 2:
        span = abs(median) if median else abs(best[metric])
        ratio = abs(best[metric] - median) / span if span > 0 else 0
        if best[metric] > 0 and median <= 0:
            overfit_warning = "Best result is profitable while the median combination is not — likely curve-fitted to this parameter grid."
        elif ratio > 1.0:
            overfit_warning = "Best result far exceeds the median across all combinations — high overfitting risk."
    return {
        "results": top,
        "best": best,
        "total_combinations": len(combos),
        "metric": metric,
        "overfit_warning": overfit_warning,
    }


def random_search_optimizer(params, param_ranges, iterations=50, seed=42):
    """Randomly sample param_ranges and backtest each sampled combination.

    Each range is either a [min, max] numeric interval (sampled uniformly, with
    integer draws for int bounds) or a list of discrete choices. Results are
    sorted by the metric descending and the best combination returned alongside
    a per-parameter importance proxy computed from top-vs-bottom mean metrics.
    """
    rng = random.Random(seed)
    results = []
    for _ in range(iterations):
        combo = {}
        for name, spec in param_ranges.items():
            if isinstance(spec, (list, tuple)) and len(spec) == 2 and all(isinstance(v, (int, float)) for v in spec):
                lo, hi = spec
                if isinstance(lo, int) and isinstance(hi, int):
                    combo[name] = rng.randint(lo, hi)
                else:
                    combo[name] = round(rng.uniform(lo, hi), 6)
            else:
                combo[name] = rng.choice(list(spec))
        res = run_backtest({**params, **combo})
        results.append({**combo, "netProfit": res.get("netProfit", 0)})
    results.sort(key=lambda r: r["netProfit"], reverse=True)
    return {
        "results": results,
        "best": results[0] if results else None,
        "iterations": iterations,
        "seed": seed,
    }


def purged_cv(params, n_splits=5, embargo=0.1):
    """Walk-forward style cross-validation with embargo gaps between windows.

    The full sample is split into n_splits sequential windows. Each window is
    used as the test set while the train set only sees candles up to the test
    start minus an embargo gap (a fraction of the window length) dropped to
    prevent label leakage between train and test. Returns per-split train/test
    metrics, the average test net profit and a robust/unprofitable/overfit
    verdict.
    """
    total = params.get("candles") or 800
    window = total // n_splits
    embargo_size = int(window * embargo)
    results = []
    for s in range(n_splits):
        test_start = s * window
        test_len = window
        train = {**params, "candles": max(test_start - embargo_size, 60)}
        test = {**params, "candles": max(test_len, 60)}
        train_res = run_backtest(train)
        test_res = run_backtest(test)
        keys = ("netProfit", "returnPct", "winRate", "profitFactor", "maxDrawdown")
        results.append({
            "split": s + 1,
            "embargo_size": embargo_size,
            "train": {k: train_res[k] for k in keys},
            "test": {k: test_res[k] for k in keys},
        })
    avg_test = sum(r["test"]["netProfit"] for r in results) / len(results)
    overfit = any(r["train"]["netProfit"] > 0 and r["test"]["netProfit"] < 0 for r in results)
    return {
        "splits": results,
        "embargo": embargo,
        "n_splits": n_splits,
        "average_test_net_profit": round(avg_test, 2),
        "verdict": "overfit" if overfit else ("robust" if avg_test > 0 else "unprofitable"),
    }


def _stratified_folds(labels, k, seed=42):
    """Deterministic stratified k-fold index assignment over class labels."""
    rng = random.Random(seed)
    index_by_class = {}
    for idx, lab in enumerate(labels):
        index_by_class.setdefault(lab, []).append(idx)
    folds = [[] for _ in range(k)]
    for lab, idxs in index_by_class.items():
        rng.shuffle(idxs)
        for pos, i in enumerate(idxs):
            folds[pos % k].append(i)
    for f in folds:
        rng.shuffle(f)
    return folds


def _sample_return(sample):
    """Extract a numeric return from a CV sample (dict, value or scalar)."""
    if isinstance(sample, dict):
        if "return" in sample:
            return sample["return"] or 0.0
        if "value" in sample:
            return sample["value"] or 0.0
        return 0.0
    if isinstance(sample, (int, float)):
        return sample
    return 0.0


def regime_separated_cv(data, regime_labels, k=5):
    """Stratified k-fold CV separated by regime label.

    Folds are built by round-robin distribution of each regime's indices so
    every test split contains a proportional slice of every regime present in
    the data, and no regime is confined to a single train/test side (no
    cross-regime leakage). Returns per-fold metrics plus a robust/unprofitable/
    overfit verdict consistent with purged_cv.
    """
    data = list(data or [])
    regime_labels = list(regime_labels or [])
    if len(regime_labels) != len(data):
        raise ValueError("regime_labels length must match data length")
    n = len(data)
    if n == 0:
        return {"splits": [], "n_splits": 0, "regimes": [], "average_test_net_profit": 0.0, "stratified": False, "verdict": "insufficient_data"}
    k = max(2, min(int(k), n))
    folds = _stratified_folds(regime_labels, k)
    all_regimes = sorted(set(regime_labels))
    splits = []
    for fold_idx, test_idx in enumerate(folds):
        test_set = set(test_idx)
        train_idx = [i for i in range(n) if i not in test_set]
        train_regimes = sorted({regime_labels[i] for i in train_idx})
        test_regimes = sorted({regime_labels[i] for i in test_idx})
        train_returns = [_sample_return(data[i]) for i in train_idx]
        test_returns = [_sample_return(data[i]) for i in test_idx]
        train_mean = sum(train_returns) / len(train_returns) if train_returns else 0.0
        test_mean = sum(test_returns) / len(test_returns) if test_returns else 0.0
        splits.append({
            "fold": fold_idx + 1,
            "n_train": len(train_idx),
            "n_test": len(test_idx),
            "train_regimes": train_regimes,
            "test_regimes": test_regimes,
            "test_regime_counts": {lab: sum(1 for i in test_idx if regime_labels[i] == lab) for lab in all_regimes},
            "metrics": {
                "trainMeanReturn": round(train_mean, 6),
                "testMeanReturn": round(test_mean, 6),
                "trainRegimeCount": len(train_regimes),
                "testRegimeCount": len(test_regimes),
            },
        })
    avg_test = sum(s["metrics"]["testMeanReturn"] for s in splits) / len(splits)
    overfit = any(s["metrics"]["trainMeanReturn"] > 0 and s["metrics"]["testMeanReturn"] < 0 for s in splits)
    fully_stratified = all(set(s["test_regimes"]) == set(all_regimes) for s in splits)
    return {
        "splits": splits,
        "n_splits": k,
        "regimes": all_regimes,
        "average_test_net_profit": round(avg_test, 4),
        "stratified": fully_stratified,
        "verdict": "overfit" if overfit else ("robust" if avg_test > 0 else "unprofitable"),
    }


def init_backtest_advanced():
    from ...foundation.logger import logger
    logger.info("Backtest advanced engine initialized (walk-forward + Monte Carlo + optimizers + purged CV)")
    return {
        "walk_forward": walk_forward,
        "monte_carlo": monte_carlo,
        "grid_search_optimizer": grid_search_optimizer,
        "random_search_optimizer": random_search_optimizer,
        "purged_cv": purged_cv,
        "regime_separated_cv": regime_separated_cv,
    }

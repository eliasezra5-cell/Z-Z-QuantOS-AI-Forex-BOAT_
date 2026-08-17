"""Institutional Quantitative Risk Models (Phase 4, Module 2 — additive).

Replaces naive fixed-percent lot sizing with three institutional gates, all
computed with ``Decimal``:

  1. Fractional Kelly Criterion (Half-Kelly by default) — optimal risk
     fraction ``f* = (p - q/b) / 2`` capped at 25% of equity to prevent
     over-leveraging.
  2. Volatility-Adjusted Sizing — the lot is scaled down when forecast ATR is
     abnormally high relative to its recent baseline (optional Wilson
     confidence adjustment on the win rate).
  3. Expected Value (EV) Gate — ``EV = p*AvgWin - q*AvgLoss``; when EV < 0 the
     trade is rejected outright.

scipy is used only for the Wilson score interval on the win rate (conservative
edge estimation); every sizing/EV decision is computed in Decimal.
"""
from decimal import Decimal, ROUND_HALF_UP

import numpy as np

from ...foundation.logger import logger
from ..marketdata.instrument_specs import instrument_specs

MAX_KELLY_FRACTION = Decimal("0.25")  # hard cap: never risk > 25% of equity
DEFAULT_FRACTION = Decimal("0.5")  # Half-Kelly
VOL_REFERENCE_PERCENTILE = 50  # baseline = median ATR over the sample


def _D(value, default=Decimal("0")):
    try:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal(str(default))


def _q(value, places=4):
    return _D(value).quantize(Decimal("1." + "0" * places), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Kelly criterion (fractional)
# --------------------------------------------------------------------------- #
def kelly_fraction(win_rate, avg_win, avg_loss, fraction=DEFAULT_FRACTION):
    """Return the (fractional) Kelly fraction in [0, 0.25].

    ``f = fraction * (p - q / b)`` with ``b = avg_win / avg_loss``. Half-Kelly
    is the default (``fraction=0.5``) to avoid over-leveraging from estimation
    error in the win rate.
    """
    p = max(Decimal("0"), min(Decimal("1"), _D(win_rate)))
    avg_win = _D(avg_win)
    avg_loss = _D(avg_loss)
    if avg_loss <= 0 or avg_win <= 0:
        return Decimal("0")
    b = avg_win / avg_loss
    q = Decimal("1") - p
    kelly = p - q / b if b > 0 else Decimal("0")
    kelly = max(Decimal("0"), kelly) * _D(fraction)
    return min(kelly, MAX_KELLY_FRACTION)


def wilson_lower_bound(win_rate, n_samples, z=1.96):
    """Conservative (lower) estimate of the win rate via the Wilson interval.

    Returns a value in [0, 1]; small sample sizes pull the estimate toward 0.5,
    which naturally reduces position size when the win rate is uncertain.
    """
    p = float(max(0.0, min(1.0, float(win_rate))))
    n = max(int(n_samples), 1)
    if n == 1:
        return Decimal(str(round(p, 4)))
    try:
        denom = 1 + z * z / n
        center = p + z * z / (2 * n)
        margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
        lower = max(0.0, (center - margin) / denom)
        return _D(lower)
    except Exception:  # noqa: BLE001 - degrade to the raw rate
        return _D(p)


# --------------------------------------------------------------------------- #
# Volatility-adjusted sizing
# --------------------------------------------------------------------------- #
def atr_reference_baseline(atr_series, percentile=VOL_REFERENCE_PERCENTILE):
    """Median (or chosen-percentile) ATR over the recent sample, as Decimal."""
    if not atr_series:
        return Decimal("0")
    arr = np.asarray([float(a) for a in atr_series], dtype=float)
    if arr.size == 0:
        return Decimal("0")
    baseline = float(np.percentile(arr, percentile))
    return _D(baseline)


def volatility_adjustment(volume, atr, baseline_atr, max_reduction=Decimal("0.60")):
    """Scale the lot down when forecast ATR is above the baseline.

    factor = min(1, baseline / atr). ``max_reduction`` bounds how much volume
    can be cut (default keeps at least 40% of the position). Returns the
    adjusted volume and the applied factor.
    """
    volume = _D(volume)
    atr = _D(atr)
    baseline = _D(baseline_atr)
    if volume <= 0 or atr <= 0 or baseline <= 0:
        return {"volume": volume, "factor": Decimal("1")}
    factor = min(Decimal("1"), baseline / atr)
    factor = max(factor, Decimal("1") - max_reduction)
    return {"volume": _q(volume * factor, 8), "factor": _q(factor, 4)}


def expected_value(win_rate, avg_win, avg_loss):
    """EV = p*AvgWin - q*AvgLoss. Returns the Decimal EV."""
    p = max(Decimal("0"), min(Decimal("1"), _D(win_rate)))
    q = Decimal("1") - p
    return _D(avg_win) * p - _D(avg_loss) * q


def ev_gate(win_rate, avg_win, avg_loss):
    """Expected-value gate: reject when EV < 0 (no edge)."""
    ev = expected_value(win_rate, avg_win, avg_loss)
    return {"approved": ev > 0, "ev": _q(ev), "edge": "positive" if ev > 0 else ("zero" if ev == 0 else "negative")}


# --------------------------------------------------------------------------- #
# Orchestration engine
# --------------------------------------------------------------------------- #
class QuantRiskEngine:
    """Combines Kelly sizing, volatility adjustment and the EV gate."""

    def size(self, equity, win_rate, avg_win, avg_loss, entry, stop, symbol="XAUUSD",
             fraction=DEFAULT_FRACTION, atr=None, atr_series=None, n_samples=None,
             use_wilson=True, max_reduction=Decimal("0.60")):
        """Full quantitative sizing pipeline.

        Steps:
          1. EV gate — reject (volume 0) when EV < 0.
          2. Kelly fraction (Half-Kelly default; Wilson-lowered win rate when
             ``n_samples`` is provided).
          3. Risk money = equity * kelly fraction; convert to lot volume.
          4. Volatility adjustment when ``atr`` and ``atr_series`` are given.
        """
        equity = _D(equity)
        entry = _D(entry)
        stop = _D(stop)

        gate = ev_gate(win_rate, avg_win, avg_loss)
        if not gate["approved"]:
            verdict_reason = f"no positive edge (EV={gate['ev']}, {gate['edge']})"
            return {
                "volume": instrument_specs.normalize_volume(symbol, 0.0),
                "approved": False,
                "verdict": "rejected",
                "reason": verdict_reason,
                "ev": gate["ev"],
                "kellyFraction": Decimal("0"),
                "volatilityFactor": Decimal("1"),
            }

        p = _D(win_rate)
        if use_wilson and n_samples:
            p = wilson_lower_bound(float(win_rate), n_samples)

        fraction = _D(fraction)
        kelly = kelly_fraction(p, avg_win, avg_loss, fraction)
        if kelly <= 0:
            return {
                "volume": instrument_specs.normalize_volume(symbol, 0.0),
                "approved": False,
                "verdict": "rejected",
                "reason": "no positive Kelly edge",
                "ev": gate["ev"],
                "kellyFraction": Decimal("0"),
                "volatilityFactor": Decimal("1"),
            }

        risk_money = equity * kelly
        if risk_money <= 0:
            return {"volume": instrument_specs.normalize_volume(symbol, 0.0), "approved": False,
                    "verdict": "rejected", "reason": "zero risk budget", "ev": gate["ev"],
                    "kellyFraction": kelly, "volatilityFactor": Decimal("1")}

        pip_value = instrument_specs.pip_value_per_lot(symbol)
        pips = instrument_specs.pips_between(symbol, float(entry), float(stop))
        base_volume = Decimal("0")
        if pip_value > 0 and pips > 0:
            base_volume = _D(risk_money / _D(pip_value * pips))
        base_volume = _D(instrument_specs.normalize_volume(symbol, float(base_volume)))

        adj = {"volume": base_volume, "factor": Decimal("1")}
        if atr is not None and atr_series:
            baseline = atr_reference_baseline(atr_series)
            adj = volatility_adjustment(base_volume, atr, baseline, max_reduction=max_reduction)

        volume = _D(instrument_specs.normalize_volume(symbol, float(adj["volume"])))
        return {
            "volume": volume,
            "approved": volume > 0,
            "verdict": "approved" if volume > 0 else "rejected",
            "reason": "institutional quant sizing",
            "ev": gate["ev"],
            "kellyFraction": _q(kelly),
            "kellyPercent": _q(kelly * 100, 2),
            "riskMoney": _q(risk_money, 2),
            "volatilityFactor": adj["factor"],
            "atrBaseline": _q(atr_reference_baseline(atr_series), 6) if atr_series else None,
        }


quant_risk_engine = QuantRiskEngine()


def init_quant_risk_engine():
    logger.info("Quantitative risk engine initialized (Kelly, volatility-adjusted sizing, EV gate)")
    return quant_risk_engine

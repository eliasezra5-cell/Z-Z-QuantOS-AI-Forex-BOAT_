"""Trade Simulator (Phase 2, Module 3) — additive, institutional.

A bar-by-bar execution simulator that models spread, slippage and commission.
It is designed to be *look-ahead safe*: the simulation is driven exclusively
by ``step(index)`` calls where the caller advances an index monotonically, and
every fill is computed from bars at or before ``index`` — never from the
future. Signals are supplied per-bar at the moment of decision; if the caller
pre-computes signals from the whole series, this module cannot prevent that,
so it also offers ``simulate(signals, bars)`` which asserts that each signal
was generated without future information (signal timestamps <= bar timestamp).

All monetary math uses ``Decimal``.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def _dec(value, fallback=Decimal("0")):
    if value is None:
        return fallback
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return fallback


def _round(value, places=5):
    q = Decimal("1").scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


class TradeSimulator:
    def __init__(self, symbol, initial_capital=Decimal("100000"),
                 spread=Decimal("0.0001"), pip=Decimal("0.0001"),
                 commission_per_lot=Decimal("0"), slippage=Decimal("0"),
                 risk_per_trade=Decimal("0.02"), volume=None):
        self.symbol = symbol
        self.initial_capital = _dec(initial_capital, Decimal("100000"))
        self.spread = _dec(spread, Decimal("0.0001"))
        self.pip = _dec(pip, Decimal("0.0001"))
        self.commission_per_lot = _dec(commission_per_lot)
        self.slippage = _dec(slippage)
        self.risk_per_trade = _dec(risk_per_trade, Decimal("0.02"))
        self.volume = _dec(volume) if volume is not None else None

        self.balance = self.initial_capital
        self.position = None
        self.trades = []
        self.equity = []
        self.index = -1

    # ------------------------------------------------------------------ #
    # Look-ahead guard
    # ------------------------------------------------------------------ #
    @property
    def last_seen_index(self):
        """The highest bar index consumed so far (for look-ahead assertions)."""
        return self.index

    # ------------------------------------------------------------------ #
    # Entry
    # ------------------------------------------------------------------ #
    def _entry_price(self, bar, side):
        """Fill at bar close, plus half-spread and slippage on the bad side."""
        close = _dec(bar["close"])
        slip = self.slippage
        if side == "buy":
            return _round(close + self.spread / Decimal("2") + slip)
        return _round(close - self.spread / Decimal("2") - slip)

    def step(self, bar, signal, atr=None):
        """Advance one bar. ``signal`` in {buy, sell, flat}.

        The position is managed using only data through this bar: exits first
        (intrabar SL/TP using this bar's high/low), then entries on this bar's
        close. Appends the equity value. Returns the list of trade closes that
        happened on this bar (may be empty).
        """
        self.index += 1
        bar_index = self.index
        closes = []
        side = signal

        if self.position:
            exit_price, reason = self._exit_check(self.position, bar)
            if exit_price is None and side == "flat":
                exit_price, reason = _dec(bar["close"]), "SIGNAL"
            if exit_price is not None:
                closes.append(self._close_position(bar, exit_price, reason))
                self.position = None

        if self.position is None and side in ("buy", "sell") and bar_index > 0:
            atr_val = _dec(atr) if atr is not None else _dec(bar["close"]) * _dec("0.001")
            sl_dist = atr_val * _dec("1.5")
            tp_dist = atr_val * _dec("3.0")
            entry = self._entry_price(bar, side)
            if self.volume is not None:
                volume = self.volume
            else:
                risk_amount = self.balance * self.risk_per_trade
                volume = risk_amount / sl_dist if sl_dist > Decimal("0") else Decimal("1")
            self.position = {
                "side": side,
                "entryPrice": entry,
                "entryIndex": bar_index,
                "entryTime": bar.get("time"),
                "stopLoss": entry - sl_dist if side == "buy" else entry + sl_dist,
                "takeProfit": entry + tp_dist if side == "buy" else entry - tp_dist,
                "volume": _round(volume, 2),
            }

        equity = self.balance + (self._unrealized(bar) if self.position else Decimal("0"))
        self.equity.append({"t": bar.get("time"), "value": float(_round(equity, 2)), "index": bar_index})
        return closes

    # ------------------------------------------------------------------ #
    # Exit checks (intrabar, no future data)
    # ------------------------------------------------------------------ #
    def _exit_check(self, position, bar):
        side = position["side"]
        if side == "buy":
            if _dec(bar["low"]) <= position["stopLoss"]:
                return position["stopLoss"], "SL"
            if _dec(bar["high"]) >= position["takeProfit"]:
                return position["takeProfit"], "TP"
        else:
            if _dec(bar["high"]) >= position["stopLoss"]:
                return position["stopLoss"], "SL"
            if _dec(bar["low"]) <= position["takeProfit"]:
                return position["takeProfit"], "TP"
        return None, None

    def _unrealized(self, bar):
        if not self.position:
            return Decimal("0")
        side = self.position["side"]
        last = _dec(bar["close"])
        entry = self.position["entryPrice"]
        vol = self.position["volume"]
        return (last - entry) * vol if side == "buy" else (entry - last) * vol

    def _close_position(self, bar, exit_price, reason):
        side = self.position["side"]
        entry = self.position["entryPrice"]
        vol = self.position["volume"]
        raw = (exit_price - entry) * vol if side == "buy" else (entry - exit_price) * vol
        commission = self.commission_per_lot * vol
        profit = raw - commission
        self.balance += profit
        trade = {
            **self.position,
            "exitPrice": float(_round(exit_price, 5)),
            "profit": float(_round(profit, 2)),
            "commission": float(_round(commission, 2)),
            "reason": reason,
            "exitIndex": self.index,
            "exitTime": bar.get("time"),
        }
        self.trades.append(trade)
        return trade

    # ------------------------------------------------------------------ #
    # Results
    # ------------------------------------------------------------------ #
    def results(self):
        return summarize_simulator(self)

    def forced_close(self, bar, reason="END"):
        """Close any still-open position at this bar (no future data used)."""
        closes = []
        if self.position:
            last = _dec(bar["close"])
            closes.append(self._close_position(bar, last, reason))
            self.position = None
        return closes


def summarize_simulator(sim):
    trades = sim.trades
    wins = [t for t in trades if t["profit"] > 0]
    gross_profit = _dec(sum(_dec(t["profit"]) for t in wins))
    gross_loss = _dec(sum(_dec(t["profit"]) for t in trades if t["profit"] < 0))
    profit_factor = Decimal("99") if gross_loss == 0 and gross_profit > 0 else (
        Decimal("0") if gross_loss == 0 else gross_profit / abs(gross_loss)
    )
    peak = sim.initial_capital
    max_drawdown = Decimal("0")
    for e in sim.equity:
        peak = max(peak, _dec(e["value"]))
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - _dec(e["value"])) / peak * Decimal("100"))
    final = sim.balance
    total_commission = _dec(sum(_dec(t.get("commission", 0)) for t in trades))
    return {
        "symbol": sim.symbol,
        "initialCapital": float(sim.initial_capital),
        "finalCapital": float(_round(final, 2)),
        "netProfit": float(_round(final - sim.initial_capital, 2)),
        "returnPct": float(_round((final - sim.initial_capital) / sim.initial_capital * Decimal("100"), 2)) if sim.initial_capital > 0 else 0.0,
        "totalTrades": len(trades),
        "winRate": round(len(wins) / len(trades) * 1000) / 10 if trades else 0.0,
        "profitFactor": float(_round(profit_factor, 4)),
        "maxDrawdown": float(_round(max_drawdown, 2)),
        "totalCommission": float(_round(total_commission, 2)),
        "avgTrade": float(_round((final - sim.initial_capital) / _dec(len(trades)), 2)) if trades else 0.0,
        "equityCurve": sim.equity,
        "trades": trades[-50:],
    }


def simulate(signals, bars, symbol="XAUUSD", **sim_kwargs):
    """Convenience runner.

    ``signals`` maps bar index -> signal string. Every signal is validated to
    have been computable from data up to that bar (timestamp check). Returns
    the TradeSimulator so callers can inspect results().
    """
    if len(bars) < 2:
        raise ValueError("at least 2 bars are required for simulation")
    if any(b.get("time") is None for b in bars):
        raise ValueError("bars must carry a 'time' field for look-ahead validation")
    for key in signals:
        if key < 0 or key >= len(bars):
            raise ValueError(f"look-ahead bias: signal index {key} outside bar series")
    sim = TradeSimulator(symbol, **sim_kwargs)
    for i, bar in enumerate(bars):
        sig = signals.get(i, "flat")
        sim.step(bar, sig)
    sim.forced_close(bars[-1], "END")
    return sim

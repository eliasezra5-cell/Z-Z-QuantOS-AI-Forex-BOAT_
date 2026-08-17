"""Deterministic Risk Engine additions (Batch 14).

Dynamic position sizing (fixed_percent, fixed_amount, atr_based, kelly,
structure_based), dynamic SL/TP calculators with priority chains, and a
deterministic risk score engine (<0.3 reject, 0.3-0.6 reduce, >0.6 approve).

Existing risk/engine.py is left untouched — these are additive helpers.
"""
from ..marketdata.instrument_specs import instrument_specs

SL_PRIORITY = ["order_block", "fvg", "swing", "liquidity", "atr", "fixed"]
TP_PRIORITY = ["liquidity", "structure", "risk_reward", "multi_target"]

SL_BUFFER_MULTIPLIER = 1.02  # tiny buffer beyond chosen level


class PositionSizer:
    """Compute order volume from risk parameters."""

    @staticmethod
    def fixed_percent(equity, risk_percent, entry, stop, symbol):
        risk_money = equity * (risk_percent / 100.0)
        return PositionSizer._from_risk_money(risk_money, entry, stop, symbol)

    @staticmethod
    def fixed_amount(risk_money, entry, stop, symbol):
        return PositionSizer._from_risk_money(risk_money, entry, stop, symbol)

    @staticmethod
    def _from_risk_money(risk_money, entry, stop, symbol):
        pip_value = instrument_specs.pip_value_per_lot(symbol)
        pips = instrument_specs.pips_between(symbol, entry, stop)
        if pip_value <= 0 or pips <= 0:
            return instrument_specs.normalize_volume(symbol, 0.01)
        volume = risk_money / (pips * pip_value)
        return instrument_specs.normalize_volume(symbol, volume)

    @staticmethod
    def atr_based(equity, risk_percent, atr, atr_multiplier, symbol):
        spec = instrument_specs.get_spec(symbol)
        risk_money = equity * (risk_percent / 100.0)
        stop_dist = atr * atr_multiplier
        if stop_dist <= 0:
            return instrument_specs.normalize_volume(symbol, 0.01)
        pip_value = instrument_specs.pip_value_per_lot(symbol)
        pips = stop_dist / instrument_specs.pip_size(symbol)
        volume = risk_money / (pips * pip_value)
        return instrument_specs.normalize_volume(symbol, volume)

    @staticmethod
    def kelly_criterion(win_rate, avg_win, avg_loss, equity, fraction=0.25, symbol="XAUUSD"):
        if avg_loss <= 0:
            return instrument_specs.normalize_volume(symbol, 0.01)
        b = avg_win / avg_loss
        p = max(0.0, min(1.0, win_rate))
        q = 1 - p
        kelly = p - q / b if b > 0 else 0
        kelly = max(0.0, min(0.25, kelly * fraction))
        return kelly

    @staticmethod
    def structure_based(equity, risk_percent, structure_pips, symbol):
        risk_money = equity * (risk_percent / 100.0)
        pip_value = instrument_specs.pip_value_per_lot(symbol)
        if structure_pips <= 0 or pip_value <= 0:
            return instrument_specs.normalize_volume(symbol, 0.01)
        volume = risk_money / (structure_pips * pip_value)
        return instrument_specs.normalize_volume(symbol, volume)

    @staticmethod
    def size(method, ctx):
        """Dispatch sizing by method name. ctx holds inputs."""
        equity = ctx.get("equity") or 0
        entry = ctx.get("entry")
        stop = ctx.get("stop")
        symbol = ctx.get("symbol") or "XAUUSD"
        if method == "fixed_amount":
            return PositionSizer.fixed_amount(ctx.get("riskAmount") or 0, entry, stop, symbol)
        if method == "atr_based":
            return PositionSizer.atr_based(equity, ctx.get("riskPercent") or 1, ctx.get("atr") or 0, ctx.get("atrMultiplier") or 2, symbol)
        if method == "kelly_criterion":
            return PositionSizer.kelly_criterion(ctx.get("winRate") or 0.5, ctx.get("avgWin") or 0, ctx.get("avgLoss") or 0, equity, ctx.get("fraction") or 0.25, symbol)
        if method == "structure_based":
            return PositionSizer.structure_based(equity, ctx.get("riskPercent") or 1, ctx.get("structurePips") or 0, symbol)
        return PositionSizer.fixed_percent(equity, ctx.get("riskPercent") or 1, entry, stop, symbol)


class DynamicSLTPCalculator:
    """SL/TP calculators following the priority chains from the prompt."""

    @staticmethod
    def _with_buffer(price, sl, side):
        """For buy: lower SL by buffer; for sell: raise SL by buffer."""
        if side == "buy":
            return price - (price - sl) * SL_BUFFER_MULTIPLIER if price > sl else sl
        return price + (sl - price) * SL_BUFFER_MULTIPLIER if sl > price else sl

    @staticmethod
    def stop_loss(side, entry, levels):
        """levels: dict with order_block, fvg, swing, liquidity, atr, fixed (prices).
        Returns chosen stop, source, and the chain attempted in order."""
        chain = []
        for key in SL_PRIORITY:
            val = levels.get(key)
            if val is None:
                continue
            chain.append(key)
            # For a buy, SL must be below entry; for sell, above entry.
            valid = (side == "buy" and val < entry) or (side == "sell" and val > entry)
            if not valid:
                continue
            sl = DynamicSLTPCalculator._with_buffer(entry, val, side)
            return {"stop": sl, "source": key, "chain": chain}
        # last resort: ATR or fixed distance
        if levels.get("atr") is not None:
            dist = levels["atr"]
            sl = entry - dist if side == "buy" else entry + dist
            chain.append("atr")
            return {"stop": sl, "source": "atr", "chain": chain}
        dist = levels.get("fixed") or 0.0
        sl = entry - dist if side == "buy" else entry + dist
        chain.append("fixed")
        return {"stop": sl, "source": "fixed", "chain": chain}

    @staticmethod
    def take_profit(side, entry, stop, levels):
        """levels: liquidity, structure (price), rr (number). Returns tp(s)."""
        chain = []
        risk = abs(entry - stop)
        # 1. Liquidity target
        if levels.get("liquidity") is not None:
            liq = levels["liquidity"]
            valid = (side == "buy" and liq > entry) or (side == "sell" and liq < entry)
            if valid:
                chain.append("liquidity")
                return {"targets": [{"price": liq, "percent": 100}], "source": "liquidity", "chain": chain}
        # 2. Next structural target
        if levels.get("structure") is not None:
            st = levels["structure"]
            valid = (side == "buy" and st > entry) or (side == "sell" and st < entry)
            if valid:
                chain.append("structure")
                return {"targets": [{"price": st, "percent": 100}], "source": "structure", "chain": chain}
        # 3. Risk:reward based
        rr = levels.get("rr") or 2.0
        chain.append("risk_reward")
        if levels.get("multi_target"):
            chain.append("multi_target")
            tp1 = entry + risk * 1.0 if side == "buy" else entry - risk * 1.0
            tp2 = entry + risk * 2.0 if side == "buy" else entry - risk * 2.0
            tp3 = entry + risk * 3.0 if side == "buy" else entry - risk * 3.0
            return {
                "targets": [
                    {"price": tp1, "percent": 30, "tag": "TP1"},
                    {"price": tp2, "percent": 30, "tag": "TP2"},
                    {"price": tp3, "percent": 40, "tag": "TP3"},
                ],
                "source": "multi_target",
                "chain": chain,
            }
        tp = entry + risk * rr if side == "buy" else entry - risk * rr
        return {"targets": [{"price": tp, "percent": 100}], "source": "risk_reward", "chain": chain}


class RiskScoreEngine:
    """Deterministic risk score in [0,1] -> reject/reduce/approve."""

    DIMENSIONS = [
        "per_trade", "per_symbol", "correlated_symbol", "account",
        "strategy", "event", "overnight_weekend", "gap", "liquidity",
        "spread", "slippage", "currency_conversion", "broker", "provider_degradation",
    ]

    def score(self, context):
        """context: dict with per-dimension risk in [0,1]. Returns verdict.
        Higher weighted risk -> reject; lower risk -> approve."""
        dims = context.get("dimensions") or {}
        weights = {
            "per_trade": 0.20, "per_symbol": 0.10, "correlated_symbol": 0.08,
            "account": 0.12, "strategy": 0.05, "event": 0.08, "overnight_weekend": 0.06,
            "gap": 0.06, "liquidity": 0.06, "spread": 0.06, "slippage": 0.05,
            "currency_conversion": 0.02, "broker": 0.03, "provider_degradation": 0.03,
        }
        total = 0.0
        wsum = 0.0
        for dim, w in weights.items():
            val = dims.get(dim)
            if val is None:
                continue
            total += float(val) * w
            wsum += w
        overall = total / wsum if wsum > 0 else 0.0
        overall = max(0.0, min(1.0, overall))
        if overall < 0.3:
            verdict = "approve"
        elif overall <= 0.6:
            verdict = "reduce"
        else:
            verdict = "reject"
        return {
            "score": round(overall, 4),
            "verdict": verdict,
            "dimensions": {d: dims.get(d) for d in self.DIMENSIONS},
        }


position_sizer = PositionSizer()
sltp_calculator = DynamicSLTPCalculator()
risk_score_engine = RiskScoreEngine()


def init_position_sizing():
    from ...foundation.logger import logger
    logger.info("Deterministic risk engine initialized (sizing, SL/TP chain, risk score)")
    return {"sizer": position_sizer, "sltp": sltp_calculator, "risk_score": risk_score_engine}

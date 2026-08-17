"""Backtest engine mirroring the Node backtest/engine.js."""
from ...foundation.logger import logger  # noqa: F401
from ..marketdata.engine import generate_candles, get_instrument
from ..technical.indicators import ema, rsi, macd, bollinger, atr, donchian
from ..technical.smc import analyze_smc

STRATEGIES = ["trend-follow", "rsi-mean-reversion", "bollinger-reversion", "macd-cross", "breakout-donchian", "smc-liquidity"]


def per_bar_indicators(candles):
    closes = [c["close"] for c in candles]
    return {
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "rsi14": rsi(closes, 14),
        "bollinger": bollinger(closes),
        "macd": macd(closes),
        "donchian": donchian(candles),
        "atr14": atr(candles, 14),
    }


def signal_for(strategy, candles, i, inds):
    if strategy == "trend-follow":
        s = inds["ema20"][i]
        l = inds["ema50"][i]
        if s is None or l is None:
            return "flat"
        return "buy" if s > l else ("sell" if s < l else "flat")
    if strategy == "rsi-mean-reversion":
        r = inds["rsi14"][i]
        if r is None:
            return "flat"
        return "buy" if r < 30 else ("sell" if r > 70 else "flat")
    if strategy == "bollinger-reversion":
        price = candles[i]["close"]
        up = inds["bollinger"]["upper"][i]
        lo = inds["bollinger"]["lower"][i]
        if up is None or lo is None:
            return "flat"
        return "buy" if price < lo else ("sell" if price > up else "flat")
    if strategy == "macd-cross":
        line = inds["macd"]["line"]
        sig = inds["macd"]["signal"]
        if i < 1 or line[i] is None or line[i - 1] is None or sig[i] is None or sig[i - 1] is None:
            return "flat"
        if line[i] > sig[i] and line[i - 1] <= sig[i - 1]:
            return "buy"
        if line[i] < sig[i] and line[i - 1] >= sig[i - 1]:
            return "sell"
        return "flat"
    if strategy == "breakout-donchian":
        dc = inds["donchian"]
        if i < 1 or dc["upper"][i] is None or dc["upper"][i - 1] is None:
            return "flat"
        if candles[i]["close"] > dc["upper"][i - 1]:
            return "buy"
        if candles[i]["close"] < dc["lower"][i - 1]:
            return "sell"
        return "flat"
    if strategy == "smc-liquidity":
        window = candles[max(0, i - 60): i + 1]
        smc = analyze_smc(window)
        liquidity = smc.get("liquidity") or []
        if not liquidity:
            return "flat"
        target = liquidity[0]
        if not target:
            return "flat"
        return "buy" if target["type"] == "buy-side" else ("sell" if target["type"] == "sell-side" else "flat")
    return "flat"


def run_backtest(params):
    symbol = params.get("symbol") or "EURUSD"
    strategy = params.get("strategy") or "trend-follow"
    timeframe = params.get("timeframe") or "H1"
    count = params.get("candles") or 500
    candles = generate_candles(symbol, timeframe, count)
    return _backtest_loop(candles, params, symbol, strategy, timeframe)


def _backtest_loop(candles, params, symbol, strategy, timeframe):
    """Shared backtest loop over a candle series.

    Additive execution-cost modeling (all zero by default so existing callers
    are unchanged):
      * commissionPerLot  - deducted per lot on every close
      * swapPerLotPerDay  - deducted per lot per day held (fractional days)
      * slippagePips      - worsens the entry fill price by slippage_pips pips
      * gapPct            - when a candle opens gapping more than gapPct from the
                            previous close, a stop/target sitting inside the gap
                            fills at the gap open price and a "gapFilled" event
                            is recorded in the result's "gaps" array
    """
    initial_capital = params.get("initialCapital") or 100000
    risk_per_trade = params.get("riskPerTrade", 0.02)
    if risk_per_trade is None:
        risk_per_trade = 0.02
    spread = params.get("spread", 0.0001)
    if spread is None:
        spread = 0.0001
    commission_per_lot = params.get("commissionPerLot") or 0.0
    swap_per_lot_per_day = params.get("swapPerLotPerDay") or 0.0
    slippage_pips = params.get("slippagePips") or 0.0
    gap_pct = params.get("gapPct") or None
    pip = get_instrument(symbol)["pip"]

    inds = per_bar_indicators(candles)
    warmup = 60

    balance = initial_capital
    trades = []
    equity = []
    gaps = []
    position = None

    for i in range(warmup, len(candles)):
        if position:
            exit = False
            exit_price = None
            reason = ""
            atr_val = inds["atr14"][i] if inds["atr14"][i] else candles[i]["close"] * 0.001
            side = position["side"]
            open_price = candles[i]["open"]
            prev_close = candles[i - 1]["close"] if i > 0 else open_price
            gap_ratio = (open_price - prev_close) / prev_close if prev_close else 0.0
            is_gap = gap_pct and gap_pct > 0 and abs(gap_ratio) > gap_pct
            gap_sl = open_price <= position["stopLoss"] if side == "buy" else open_price >= position["stopLoss"]
            gap_tp = open_price >= position["takeProfit"] if side == "buy" else open_price <= position["takeProfit"]
            if is_gap and (gap_sl or gap_tp):
                exit = True
                exit_price = open_price
                reason = "SL-GAP" if gap_sl else "TP-GAP"
                gaps.append({
                    "type": "gapFilled",
                    "symbol": symbol,
                    "index": i,
                    "time": candles[i]["time"],
                    "side": side,
                    "trigger": "SL" if gap_sl else "TP",
                    "gapPct": round(gap_ratio * 100, 4),
                    "openPrice": round(open_price * 100000) / 100000,
                    "fillPrice": round(open_price * 100000) / 100000,
                })
            elif side == "buy":
                if candles[i]["low"] <= position["stopLoss"]:
                    exit, exit_price, reason = True, position["stopLoss"], "SL"
                elif candles[i]["high"] >= position["takeProfit"]:
                    exit, exit_price, reason = True, position["takeProfit"], "TP"
            else:
                if candles[i]["high"] >= position["stopLoss"]:
                    exit, exit_price, reason = True, position["stopLoss"], "SL"
                elif candles[i]["low"] <= position["takeProfit"]:
                    exit, exit_price, reason = True, position["takeProfit"], "TP"
            if not exit and signal_for(strategy, candles, i, inds) == "flat":
                exit, exit_price, reason = True, candles[i]["close"], "SIGNAL"
            if exit:
                raw_profit = (exit_price - position["entryPrice"]) * position["volume"] if side == "buy" else (position["entryPrice"] - exit_price) * position["volume"]
                days_held = max(0.0, (candles[i]["time"] - position["entryTime"]) / 86400000.0)
                swap = swap_per_lot_per_day * position["volume"] * days_held
                commission = commission_per_lot * position["volume"]
                profit = raw_profit - swap - commission
                balance += profit
                trades.append({
                    **position,
                    "exitPrice": round(exit_price * 100000) / 100000,
                    "profit": round(profit * 100) / 100,
                    "reason": reason,
                    "exitTime": candles[i]["time"],
                    "exitIndex": i,
                    "commission": round(commission * 100) / 100,
                    "swap": round(swap * 100) / 100,
                    "gapFilled": reason in ("SL-GAP", "TP-GAP"),
                })
                position = None

        if not position and i < len(candles) - 1:
            signal = signal_for(strategy, candles, i, inds)
            if signal != "flat":
                price = candles[i]["close"]
                atr_val = inds["atr14"][i] if inds["atr14"][i] else price * 0.001
                risk_amount = balance * risk_per_trade
                sl_dist = atr_val * 1.5
                tp_dist = atr_val * 3
                volume = risk_amount / sl_dist
                slippage = slippage_pips * pip
                entry = price + spread / 2 + slippage if signal == "buy" else price - spread / 2 - slippage
                position = {
                    "symbol": symbol,
                    "side": signal,
                    "entryPrice": round(entry * 100000) / 100000,
                    "stopLoss": entry - sl_dist if signal == "buy" else entry + sl_dist,
                    "takeProfit": entry + tp_dist if signal == "buy" else entry - tp_dist,
                    "volume": round(volume * 100) / 100,
                    "entryTime": candles[i]["time"],
                    "entryIndex": i,
                    "strategy": strategy,
                }

        equity.append({"t": candles[i]["time"], "value": round(balance * 100) / 100})

    if position:
        last = candles[-1]
        side = position["side"]
        raw_profit = (last["close"] - position["entryPrice"]) * position["volume"] if side == "buy" else (position["entryPrice"] - last["close"]) * position["volume"]
        days_held = max(0.0, (last["time"] - position["entryTime"]) / 86400000.0)
        swap = swap_per_lot_per_day * position["volume"] * days_held
        commission = commission_per_lot * position["volume"]
        profit = raw_profit - swap - commission
        balance += profit
        trades.append({
            **position,
            "exitPrice": round(last["close"] * 100000) / 100000,
            "profit": round(profit * 100) / 100,
            "reason": "END",
            "exitTime": last["time"],
            "exitIndex": len(candles) - 1,
            "commission": round(commission * 100) / 100,
            "swap": round(swap * 100) / 100,
            "gapFilled": False,
        })

    result = summarize(symbol, strategy, timeframe, initial_capital, balance, trades, equity)
    result["gaps"] = gaps
    result["costs"] = {
        "commissionPerLot": commission_per_lot,
        "swapPerLotPerDay": swap_per_lot_per_day,
        "slippagePips": slippage_pips,
        "gapPct": gap_pct,
    }
    return result


def simulate_gap(candles, gap_pct, **kwargs):
    """Run a backtest over the given candles with gap simulation enabled.

    When a candle opens with a gap (relative to the previous close) larger than
    `gap_pct`, any stop or target sitting inside the gap fills at the gap open
    price instead of the ordered level, and a "gapFilled" event is appended to
    the result's "gaps" array. Optional kwargs mirror run_backtest params.
    """
    candles = list(candles or [])
    symbol = kwargs.get("symbol") or "EURUSD"
    strategy = kwargs.get("strategy") or "trend-follow"
    timeframe = kwargs.get("timeframe") or "H1"
    initial_capital = kwargs.get("initialCapital") or 100000
    params = {
        **kwargs,
        "symbol": symbol,
        "strategy": strategy,
        "timeframe": timeframe,
        "gapPct": gap_pct,
    }
    if len(candles) < 2:
        result = summarize(symbol, strategy, timeframe, initial_capital, initial_capital, [], [])
        result["gaps"] = []
        result["costs"] = {"commissionPerLot": 0.0, "swapPerLotPerDay": 0.0, "slippagePips": 0.0, "gapPct": gap_pct}
        return result
    return _backtest_loop(candles, params, symbol, strategy, timeframe)


def summarize(symbol, strategy, timeframe, initial, final, trades, equity):
    wins = [t for t in trades if t["profit"] > 0]
    gross_profit = sum(t["profit"] for t in wins)
    gross_loss = sum(t["profit"] for t in trades if t["profit"] < 0)
    profit_factor = 99 if gross_loss == 0 and gross_profit > 0 else (0 if gross_loss == 0 else round(gross_profit / abs(gross_loss) * 100) / 100)
    peak = initial
    max_drawdown = 0
    for e in equity:
        peak = max(peak, e["value"])
        max_drawdown = max(max_drawdown, (peak - e["value"]) / peak * 100)
    return {
        "symbol": symbol,
        "strategy": strategy,
        "timeframe": timeframe,
        "initialCapital": initial,
        "finalCapital": round(final * 100) / 100,
        "netProfit": round((final - initial) * 100) / 100,
        "returnPct": round((final - initial) / initial * 10000) / 100,
        "totalTrades": len(trades),
        "winRate": round((len(wins) / len(trades)) * 1000) / 10 if trades else 0,
        "profitFactor": profit_factor,
        "maxDrawdown": round(max_drawdown * 100) / 100,
        "avgTrade": round((final - initial) / len(trades) * 100) / 100 if trades else 0,
        "equityCurve": equity,
        "trades": trades[-50:],
    }


def compare_strategies(params):
    symbol = params.get("symbol") or "EURUSD"
    timeframe = params.get("timeframe") or "H1"
    results = []
    for s in STRATEGIES:
        r = run_backtest({"symbol": symbol, "strategy": s, "timeframe": timeframe, "initialCapital": params.get("initialCapital"), "spread": params.get("spread")})
        results.append({k: r[k] for k in ("netProfit", "returnPct", "winRate", "profitFactor", "maxDrawdown", "totalTrades")} | {"strategy": s})
    return sorted(results, key=lambda r: r["netProfit"], reverse=True)

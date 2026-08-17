"""Dynamic SL/TP Optimization (Phase 4, Module 3 — additive).

Replaces fixed-pip stops with structural levels computed in Decimal:

  - Stop Loss    : below/above the Order Block or the Liquidity Sweep wick,
                   plus an ``ATR * 0.5`` buffer. Never fixed pips.
  - Take Profit  : TP1 at the next Liquidity Pool; TP2 at the next unmitigated
                   Order Block.
  - R/R Gate     : if the structural risk/reward is below 1:2 the setup is
                   returned as ``rejected`` so the Technical Execution Agent
                   never carries a sub-1:2 trade.

The optimizer is a pure function over candle data + an ``analyze_advanced_smc``
result, so it is backtestable and fully deterministic.
"""
from decimal import Decimal, ROUND_HALF_UP

from ...foundation.logger import logger
from ..risk.quant_models import _D, _q

SL_BUFFER_ATR = Decimal("0.5")  # buffer = ATR * 0.5 beyond the structural level
MIN_RR = Decimal("2.0")  # minimum risk/reward 1:2


# --------------------------------------------------------------------------- #
# Liquidity pools from swing structure
# --------------------------------------------------------------------------- #
def liquidity_pools(smcs, entry, side, limit=6):
    """Buy-side pools (swing highs above) for longs, sell-side pools (swing
    lows below) for shorts, sorted by distance to entry."""
    entry = _D(entry)
    pools = []
    for s in smcs.get("swings") or []:
        price = _D(s.get("price"))
        if side == "buy" and s.get("type") == "swingHigh" and price > entry:
            pools.append({"price": price, "index": s.get("index")})
        elif side == "sell" and s.get("type") == "swingLow" and price < entry:
            pools.append({"price": price, "index": s.get("index")})
    pools.sort(key=lambda p: abs(p["price"] - entry))
    return pools[:limit]


def next_liquidity_pool(smcs, entry, side):
    """The nearest liquidity pool in the trade direction (TP1 anchor)."""
    pools = liquidity_pools(smcs, entry, side, limit=1)
    return pools[0] if pools else None


# --------------------------------------------------------------------------- #
# Liquidity sweep wicks (SL anchor)
# --------------------------------------------------------------------------- #
def _find_sweep_wick(candles, swing, entry, side):
    """Return the wick low/high of a swept swing if price pierced and closed back."""
    index = int(swing.get("index", 0))
    level = _D(swing.get("price"))
    wick = None
    pierced = False
    for i in range(index + 1, len(candles)):
        c = candles[i]
        c_low, c_high, c_close = _D(c["low"]), _D(c["high"]), _D(c["close"])
        if side == "buy":  # a sell-side swing low swept: wick < level, then close above
            if not pierced and c_low < level:
                pierced = True
                wick = c_low
            if pierced and c_close > level:
                return {"wick": wick, "level": level, "index": i}
        else:  # a buy-side swing high swept: wick > level, then close below
            if not pierced and c_high > level:
                pierced = True
                wick = c_high
            if pierced and c_close < level:
                return {"wick": wick, "level": level, "index": i}
    return None


def sweep_wicks(candles, smcs, entry, side, limit=4):
    """All valid liquidity sweep wicks on the trade side of entry, nearest first."""
    entry = _D(entry)
    side_type = "swingLow" if side == "buy" else "swingHigh"
    wicks = []
    for s in smcs.get("swings") or []:
        if s.get("type") != side_type:
            continue
        if (side == "buy" and _D(s.get("price")) >= entry) or (side == "sell" and _D(s.get("price")) <= entry):
            continue
        found = _find_sweep_wick(candles, s, entry, side)
        if found:
            wicks.append(found)
    wicks.sort(key=lambda w: abs(_D(w["wick"]) - entry))
    return wicks[:limit]


# --------------------------------------------------------------------------- #
# Dynamic stop loss
# --------------------------------------------------------------------------- #
def dynamic_stop_loss(side, entry, smcs, atr, candles=None):
    """Structural SL: OB or liquidity sweep wick + ATR*0.5 buffer (never fixed).

    For a buy the stop sits below the lowest structural level; for a sell above
    the highest. Returns None when no structural anchor exists on that side.
    """
    entry = _D(entry)
    atr = _D(atr)
    buffer = atr * SL_BUFFER_ATR
    if side == "buy":
        anchors = []
        for ob in smcs.get("orderBlocks") or []:
            if ob.get("type") != "bullish" or ob.get("mitigated"):
                continue
            zone = ob.get("zone") or []
            if len(zone) == 2 and _D(zone[0]) < entry:
                anchors.append({"price": _D(zone[0]), "source": "order_block", "detail": ob.get("index")})
        for w in sweep_wicks(candles or [], smcs, entry, side):
            anchors.append({"price": _D(w["wick"]), "source": "sweep_wick", "detail": w.get("index")})
        if anchors:
            anchor = max(anchors, key=lambda a: a["price"])  # nearest to entry
            stop = anchor["price"] - buffer
            if stop < entry:
                return {"stop": _q(stop), "source": anchor["source"], "anchor": anchor["price"],
                        "buffer": _q(buffer), "chain": [a["source"] for a in anchors]}
    else:  # sell
        anchors = []
        for ob in smcs.get("orderBlocks") or []:
            if ob.get("type") != "bearish" or ob.get("mitigated"):
                continue
            zone = ob.get("zone") or []
            if len(zone) == 2 and _D(zone[1]) > entry:
                anchors.append({"price": _D(zone[1]), "source": "order_block", "detail": ob.get("index")})
        for w in sweep_wicks(candles or [], smcs, entry, side):
            anchors.append({"price": _D(w["wick"]), "source": "sweep_wick", "detail": w.get("index")})
        if anchors:
            anchor = min(anchors, key=lambda a: a["price"])  # nearest to entry
            stop = anchor["price"] + buffer
            if stop > entry:
                return {"stop": _q(stop), "source": anchor["source"], "anchor": anchor["price"],
                        "buffer": _q(buffer), "chain": [a["source"] for a in anchors]}
    return None


# --------------------------------------------------------------------------- #
# Dynamic take profit
# --------------------------------------------------------------------------- #
def next_unmitigated_ob(smcs, entry, side):
    """Nearest unmitigated OB on the profit side of entry (TP2 anchor)."""
    entry = _D(entry)
    best = None
    for ob in smcs.get("orderBlocks") or []:
        if ob.get("mitigated"):
            continue
        zone = ob.get("zone") or []
        if len(zone) != 2:
            continue
        price = _D(ob.get("price") or (zone[0] + zone[1]) / Decimal("2"))
        if side == "buy" and price > entry:
            if best is None or price < best["price"]:
                best = {"price": price, "index": ob.get("index"), "type": ob.get("type")}
        elif side == "sell" and price < entry:
            if best is None or price > best["price"]:
                best = {"price": price, "index": ob.get("index"), "type": ob.get("type")}
    return best


def dynamic_take_profit(side, entry, smcs):
    """TP1 at the next liquidity pool, TP2 at the next unmitigated OB."""
    entry = _D(entry)
    tp1 = next_liquidity_pool(smcs, entry, side)
    tp2 = next_unmitigated_ob(smcs, entry, side)
    targets = []
    if tp1:
        targets.append({"price": _q(tp1["price"]), "tag": "TP1", "source": "liquidity_pool", "index": tp1.get("index")})
    if tp2:
        targets.append({"price": _q(tp2["price"]), "tag": "TP2", "source": "unmitigated_order_block", "index": tp2.get("index")})
    # Order targets nearest-to-farthest for the trade direction.
    targets.sort(key=lambda t: t["price"] if side == "buy" else -t["price"])
    return {"targets": targets, "source": "structural", "tp1": targets[0] if targets else None}


# --------------------------------------------------------------------------- #
# Risk/reward gate + orchestration
# --------------------------------------------------------------------------- #
def risk_reward(side, entry, stop, target):
    """RR = distance to target / distance to stop. Returns Decimal RR (>=0)."""
    entry, stop, target = _D(entry), _D(stop), _D(target)
    risk = abs(entry - stop)
    if risk <= 0:
        return Decimal("0")
    return _q(abs(target - entry) / risk, 2)


def _candidate_targets(side, entry, smcs):
    """All structural targets on the profit side of entry, nearest-first.

    Combines liquidity pools (TP1 anchors) and unmitigated order blocks
    (TP2 anchors) into one ordered ladder so the optimizer can walk outward
    until the 1:2 risk/reward gate is satisfied.
    """
    entry = _D(entry)
    candidates = []
    for p in liquidity_pools(smcs, entry, side, limit=8):
        candidates.append({"price": _D(p["price"]), "source": "liquidity_pool", "index": p.get("index")})
    for ob in smcs.get("orderBlocks") or []:
        if ob.get("mitigated"):
            continue
        zone = ob.get("zone") or []
        if len(zone) != 2:
            continue
        price = _D(ob.get("price") or (zone[0] + zone[1]) / Decimal("2"))
        if (side == "buy" and price > entry) or (side == "sell" and price < entry):
            candidates.append({"price": price, "source": "unmitigated_order_block", "index": ob.get("index")})
    if side == "buy":
        candidates.sort(key=lambda t: t["price"])
    else:
        candidates.sort(key=lambda t: -t["price"])
    return candidates


def optimize_sltp(side, entry, smcs, atr, candles=None, min_rr=MIN_RR):
    """Full dynamic SL/TP optimization with a guaranteed 1:2 R/R walk-out.

    - SL stays structural (Order Block / liquidity-sweep wick + ATR buffer).
    - Structural targets are walked outward (nearest liquidity pools and
      unmitigated order blocks) and the nearest target that satisfies the
      ``min_rr`` gate becomes TP1, so an approved setup always has
      reward >= 2x risk. TP2 is the next structural target beyond TP1.
    - Side ordering is enforced:
          BUY  -> SL < Entry < TP1
          SELL -> TP1 < Entry < SL
    Returns ``approved: False`` with a reason when no structural SL, no
    target, or no target within the R/R gate exists.
    """
    entry = _D(entry)
    sl = dynamic_stop_loss(side, entry, smcs, atr, candles=candles)
    if sl is None:
        return {"approved": False, "side": side, "reason": "no structural SL anchor (OB/sweep)"}

    targets = _candidate_targets(side, entry, smcs)
    if not targets:
        return {"approved": False, "side": side, "reason": "no structural TP anchor (liquidity pool / OB)",
                "stopLoss": sl["stop"]}

    # Walk nearest -> farthest until the risk/reward gate is met.
    chosen = None
    best_rr = Decimal("0")
    for t in targets:
        rr = risk_reward(side, entry, sl["stop"], t["price"])
        if rr > best_rr:
            best_rr = rr
        if rr >= _D(min_rr):
            chosen = {"target": t, "rr": rr}
            break

    if chosen is None:
        return {
            "approved": False,
            "side": side,
            "entry": entry,
            "stopLoss": sl["stop"],
            "stopSource": sl["source"],
            "stopAnchor": sl.get("anchor"),
            "buffer": sl.get("buffer"),
            "takeProfit": [_q(t["price"]) for t in targets],
            "takeProfitDetail": targets,
            "riskReward": _q(best_rr, 2),
            "minRiskReward": _q(_D(min_rr)),
            "reason": f"risk/reward {_q(best_rr, 2)} < {min_rr} (1:2 minimum)",
        }

    tp1 = chosen["target"]
    tp2 = None
    for t in targets:
        if side == "buy" and t["price"] > tp1["price"]:
            tp2 = t
            break
        if side == "sell" and t["price"] < tp1["price"]:
            tp2 = t
            break

    take_profits = [_q(tp1["price"])]
    take_profit_detail = [dict(tp1, tag="TP1")]
    if tp2 is not None:
        take_profits.append(_q(tp2["price"]))
        take_profit_detail.append(dict(tp2, tag="TP2"))

    # Side-ordering guard: structural levels must sit on the correct side.
    valid_side = (side == "buy" and sl["stop"] < entry < tp1["price"]) or \
                 (side == "sell" and tp1["price"] < entry < sl["stop"])
    if not valid_side:
        return {
            "approved": False,
            "side": side,
            "entry": entry,
            "stopLoss": sl["stop"],
            "takeProfit": take_profits,
            "takeProfitDetail": take_profit_detail,
            "riskReward": chosen["rr"],
            "minRiskReward": _q(_D(min_rr)),
            "reason": "structural levels violate side ordering (SL/TP on wrong side of entry)",
        }

    return {
        "approved": True,
        "side": side,
        "entry": entry,
        "stopLoss": sl["stop"],
        "stopSource": sl["source"],
        "stopAnchor": sl.get("anchor"),
        "buffer": sl.get("buffer"),
        "takeProfit": take_profits,
        "takeProfitDetail": take_profit_detail,
        "riskReward": chosen["rr"],
        "minRiskReward": _q(_D(min_rr)),
        "reason": "approved",
    }


def init_dynamic_sltp():
    logger.info("Dynamic SL/TP optimizer initialized (OB/sweep SL, liquidity/OB TP, 1:2 RR gate)")
    return optimize_sltp
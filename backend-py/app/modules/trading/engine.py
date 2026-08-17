"""Trading engine mirroring the Node trading/engine.js.

Fail-closed safety gates are enforced on every order:
  stale market feed, MT5 disconnect (live), duplicate idempotency key,
  reconciliation freeze, mock data in production, duplicate-news trades.
"""
import threading
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...foundation.feature_flags import feature_flags
from ...config import settings
from ..marketdata.engine import get_quote, get_instrument, get_live_quote  # noqa: F401
from ..risk.engine import risk_engine
from ..portfolio.service import portfolio_service

# Sources that only ever appear in simulation/testing and must never reach
# production execution.
MOCK_SOURCES = ("simulator", "mock", "demo")

# Estimated slippage as a fraction of the live spread (institutional estimate,
# matches the backtest engine's per-pip slippage cost model).
SLIPPAGE_SPREAD_FRACTION = 0.25


def _estimate_execution_costs(quote, instrument):
    """Live spread + estimated slippage for one fill (additive, never raises).

    Reuses the backtest cost model: entry worsens by ``slippage_pips * pip`` on
    top of half the spread. All values are estimates derived from the real quote.
    """
    spread = float((quote or {}).get("spread") or 0.0)
    pip = float((instrument or {}).get("pip") or 0.0001)
    spread_pips = (spread / pip) if pip else spread
    slippage_pips = max(0.1, spread_pips * SLIPPAGE_SPREAD_FRACTION)
    slippage = slippage_pips * pip
    half_spread = spread / 2
    return {
        "spread": round(spread, 5),
        "spreadPips": round(spread_pips, 2),
        "halfSpread": round(half_spread, 5),
        "estimatedSlippagePips": round(slippage_pips, 2),
        "estimatedSlippage": round(slippage, 5),
        "estimatedCostPerUnit": round(half_spread + slippage, 5),
    }


def _live_fill_tracking(costs, quote, instrument, price, volume, side):
    """Per-fill execution-quality fields (additive, never raises).

    Records the fill price the execution model expected (fair-value mid adjusted
    by the estimated cost-per-unit) against the price the order actually filled
    at, plus the realized spread cost and slippage. With a live broker feed the
    ``actualFillPrice`` can be replaced by the broker-reported fill price; in
    simulation the fill is recorded at the touch price.
    """
    bid = float((quote or {}).get("bid") or 0.0)
    ask = float((quote or {}).get("ask") or 0.0)
    mid = (bid + ask) / 2 if bid and ask else float(price)
    cost_per_unit = float(costs.get("estimatedCostPerUnit") or 0.0)
    expected = mid + cost_per_unit if side == "buy" else mid - cost_per_unit
    actual = float(price)
    slippage = abs(actual - expected)
    pip = float((instrument or {}).get("pip") or 0.0001)
    return {
        "expectedFillPrice": round(expected * 100000) / 100000,
        "actualFillPrice": round(actual * 100000) / 100000,
        "spreadCost": round((float(costs.get("spread") or 0.0) * float(volume or 0.0)) * 100) / 100,
        "actualSlippage": round(slippage * 100000) / 100000,
        "actualSlippagePips": round((slippage / pip) * 100) / 100,
    }


class TradingEngine:
    def __init__(self):
        self.col = db.collection("positions")
        self.order_col = db.collection("orders")
        self.news_traded = db.collection("news_traded")
        self.mode = "manual"
        self.listeners = []

    def set_mode(self, mode):
        self.mode = "auto" if mode == "auto" else "manual"
        event_bus.emit("trading:mode", {"mode": self.mode})
        logger.info(f"Trading mode set to {self.mode}")
        return self.mode

    def _safety_checks(self, order):
        """Fail-closed pre-trade gates. Returns (ok, reason)."""
        symbol = order.get("symbol")
        source = (order.get("source") or "manual").lower()

        # Manual/admin orders bypass the stale market-data gate so a human can
        # always manage risk even if the tick feed is momentarily stale.
        manual_sources = ("manual", "admin", "web-terminal", "mt5-manual", "system")
        live = get_live_quote(symbol)
        if source not in manual_sources and live and int(time.time() * 1000) - live["fetchedAt"] > settings.STALE_DATA_THRESHOLD_SECONDS * 1000:
            return False, "stale-market-data"

        from ..risk.capital_guard import capital_guard  # lazy: avoids circular import
        quote = get_quote(symbol)
        inst = get_instrument(symbol)
        spread_pips = (quote["spread"] / inst["pip"]) if inst.get("pip") else quote["spread"]
        ok, why = capital_guard.fail_closed_gate(order, spread_pips)
        if not ok:
            return False, why

        if settings.MT5_ENABLED == "live":
            from ..mt5.adapter import mt5_state  # lazy: avoids circular import
            if not mt5_state.connected:
                return False, "mt5-disconnected"

        from ..execution.mt5_safety import mt5_safety  # lazy: keeps import graph acyclic
        if mt5_safety.is_frozen(symbol):
            return False, "execution-frozen"

        source = order.get("source") or "manual"
        if settings.ENVIRONMENT == "production" and source in MOCK_SOURCES:
            return False, "mock-data-in-production"

        fingerprint = order.get("newsFingerprint")
        if fingerprint and self.news_traded.find_one({"fingerprint": fingerprint}):
            return False, "duplicate-news-trade"

        return True, ""

    def place_order(self, order):
        symbol = order["symbol"]
        ok, reason = self._safety_checks(order)
        if not ok:
            order_record = self.order_col.insert({
                "symbol": symbol,
                "side": order.get("side"),
                "type": order.get("type") or "market",
                "volume": order.get("volume") or 0.1,
                "status": "rejected",
                "rejectReason": reason,
                "timestamp": int(time.time() * 1000),
                "comment": order.get("comment") or "manual",
                "confidence": order.get("confidence"),
                "source": order.get("source") or "manual",
                "idempotency_key": order.get("idempotency_key"),
            })
            event_bus.emit("order:rejected", {"order": order_record, "violations": [reason]})
            logger.warn(f"Order blocked by safety gate: {reason} ({symbol})")
            return {"status": "rejected", "order": order_record, "violations": [reason]}

        quote = get_quote(symbol)
        instrument = get_instrument(symbol)
        entry_price = order.get("price") or (quote["ask"] if order.get("side") == "buy" else quote["bid"])
        volume = order.get("volume") or 0.1
        price = entry_price
        sl = order.get("stopLoss")
        tp = order.get("takeProfit")
        costs = _estimate_execution_costs(quote, instrument)

        # Manual orders from the UI always require a stop loss (and, when the
        # take-profit rule is enabled, a take profit) before execution.
        manual_sources = ("manual", "web-terminal", "mt5-manual")
        if (order.get("source") or "manual").lower() in manual_sources:
            sl_rule = next((r for r in risk_engine.get_settings() if r["id"] == "stop_loss_required"), None)
            tp_rule = next((r for r in risk_engine.get_settings() if r["id"] == "take_profit_required"), None)
            violations = []
            if sl_rule and sl_rule.get("enabled") and sl is None:
                violations.append("Stop loss required")
            if tp_rule and tp_rule.get("enabled") and tp is None:
                violations.append("Take profit required")
            if violations:
                order_record = self.order_col.insert({
                    "symbol": symbol,
                    "side": order.get("side"),
                    "type": order.get("type") or "market",
                    "volume": volume,
                    "status": "rejected",
                    "rejectReason": "; ".join(violations),
                    "timestamp": int(time.time() * 1000),
                    "comment": order.get("comment") or "manual",
                    "source": order.get("source") or "manual",
                })
                event_bus.emit("order:rejected", {"order": order_record, "violations": violations})
                return {"status": "rejected", "order": order_record, "violations": violations}

        from ..marketdata.instrument_specs import instrument_specs  # lazy: additive buffer
        _, sl, tp, min_dist, adjusted = instrument_specs.enforce_stop_levels(symbol, order.get("side"), entry_price, sl, tp)
        if adjusted:
            logger.info(f"Stops buffer applied for {symbol}: {adjusted} (min_dist={min_dist})")

        notional = price * volume
        risk_amount = abs(price - sl) * volume if sl else 0

        from ..execution.mt5_safety import mt5_safety  # lazy import
        envelope = mt5_safety.build_order(order)
        dup = mt5_safety.duplicate_check(envelope)
        if dup["duplicate"]:
            order_record = self.order_col.insert({
                "symbol": symbol,
                "side": order.get("side"),
                "type": order.get("type") or "market",
                "volume": volume,
                "status": "rejected",
                "rejectReason": "duplicate-order",
                "timestamp": int(time.time() * 1000),
                "comment": order.get("comment") or "manual",
                "source": order.get("source") or "manual",
                "idempotency_key": envelope.get("idempotency_key"),
            })
            event_bus.emit("order:rejected", {"order": order_record, "violations": ["duplicate-order"]})
            return {"status": "rejected", "order": order_record, "violations": ["duplicate-order"]}

        portfolio = portfolio_service.get()
        protection = portfolio.get("capitalProtection")
        if protection and protection.get("haltTrading"):
            event_bus.emit("order:rejected", {"order": {"symbol": symbol, "side": order.get("side")}, "violations": [protection["reason"]]})
            logger.warn(f"Order rejected: capital protection halt active ({protection['reason']})")
            return {"status": "rejected", "violations": [protection["reason"]], "protection": protection}

        if portfolio.get("equity", 0) > 0 and notional > portfolio["equity"] * 100:
            return {"status": "rejected", "violations": [f"Notional {notional:.2f} exceeds equity limit"]}

        open_same = self.col.find({"symbol": symbol, "status": "open"})
        correlated_positions = len(open_same)
        risk_check = risk_engine.evaluate_trade(
            {
                "riskAmount": risk_amount,
                "notionalPct": (notional / portfolio["equity"]) * 100 if portfolio.get("equity", 0) > 0 else 0,
                "stopLoss": sl,
                "takeProfit": tp,
                "symbol": symbol,
                "correlatedPositions": correlated_positions,
            },
            portfolio,
        )
        if not risk_check["approved"]:
            order_record = self.order_col.insert({
                "symbol": symbol,
                "side": order.get("side"),
                "type": order.get("type") or "market",
                "volume": volume,
                "price": round(price * 100000) / 100000,
                "stopLoss": sl,
                "takeProfit": tp,
                "riskAmount": round(risk_amount * 100) / 100,
                "status": "rejected",
                "rejectReason": "; ".join(risk_check["violations"]),
                "timestamp": int(time.time() * 1000),
                "comment": order.get("comment") or "manual",
                "confidence": order.get("confidence"),
                "source": order.get("source") or "manual",
            })
            event_bus.emit("order:rejected", {"order": order_record, "violations": risk_check["violations"]})
            return {"status": "rejected", "order": order_record, "violations": risk_check["violations"]}

        # ---- Risk Debate Team + Portfolio Gate (Feature 3, additive) ----
        # Deterministic checks above are the source of truth; this gate runs
        # last and can only REDUCE volume or REJECT the order.
        from ..risk.debate.portfolio_gate import run_portfolio_gate  # lazy: keeps import graph acyclic
        spread_pips = (quote["spread"] / instrument["pip"]) if instrument.get("pip") else quote["spread"]
        gate_context = {
            "symbol": symbol,
            "side": order.get("side"),
            "volume": volume,
            "price": price,
            "riskAmount": risk_amount,
            "stopLoss": sl,
            "takeProfit": tp,
            "confidence": order.get("confidence"),
            "source": order.get("source") or "manual",
        }
        gate_portfolio = {**portfolio, "openPositions": correlated_positions}
        gate = run_portfolio_gate(gate_context, portfolio=gate_portfolio)
        if not gate["approved"]:
            order_record = self.order_col.insert({
                "symbol": symbol,
                "side": order.get("side"),
                "type": order.get("type") or "market",
                "volume": volume,
                "price": round(price * 100000) / 100000,
                "stopLoss": sl,
                "takeProfit": tp,
                "riskAmount": round(risk_amount * 100) / 100,
                "status": "rejected",
                "rejectReason": f"risk-debate:{gate['verdict']} — {gate.get('reason', '')}",
                "riskDebate": gate.get("record"),
                "timestamp": int(time.time() * 1000),
                "comment": order.get("comment") or "manual",
                "confidence": order.get("confidence"),
                "source": order.get("source") or "manual",
            })
            event_bus.emit("order:rejected", {"order": order_record, "violations": [gate.get("reason", "risk-debate-reject")]})
            event_bus.emit("risk:debate", {"gate": gate.get("record"), "timestamp": int(time.time() * 1000)})
            logger.warn(f"Order blocked by risk debate gate ({symbol}): {gate.get('reason')}")
            return {"status": "rejected", "order": order_record, "violations": [gate.get("reason", "risk-debate-reject")]}

        gate_record = gate.get("record")
        if gate["verdict"] == "reduce":
            volume = float(gate["maxVolume"])
            logger.info(f"Risk debate reduced {symbol} order to {volume} ({gate.get('reason')})")

        fill_tracking = _live_fill_tracking(costs, quote, instrument, price, volume, order.get("side"))
        order_record = self.order_col.insert({
            "symbol": symbol,
            "side": order.get("side"),
            "type": order.get("type") or "market",
            "volume": volume,
            "price": round(price * 100000) / 100000,
            "stopLoss": sl,
            "takeProfit": tp,
            "riskAmount": round(risk_amount * 100) / 100,
            "status": "filled",
            "filledAt": int(time.time() * 1000),
            "timestamp": int(time.time() * 1000),
            "comment": order.get("comment") or "manual",
            "confidence": order.get("confidence"),
            "source": order.get("source") or "manual",
            "riskDebate": gate_record,
            "spread": costs["spread"],
            "spreadPips": costs["spreadPips"],
            "estimatedSlippagePips": costs["estimatedSlippagePips"],
            "estimatedSlippage": costs["estimatedSlippage"],
            "estimatedCostPerUnit": costs["estimatedCostPerUnit"],
            "expectedFillPrice": fill_tracking["expectedFillPrice"],
            "actualFillPrice": fill_tracking["actualFillPrice"],
            "spreadCost": fill_tracking["spreadCost"],
            "actualSlippage": fill_tracking["actualSlippage"],
            "actualSlippagePips": fill_tracking["actualSlippagePips"],
        })
        position = self.col.insert({
            "symbol": symbol,
            "side": order.get("side"),
            "volume": volume,
            "entryPrice": round(price * 100000) / 100000,
            "stopLoss": sl,
            "takeProfit": tp,
            "profit": 0,
            "status": "open",
            "openedAt": int(time.time() * 1000),
            "orderId": order_record["id"],
            "confidence": order.get("confidence"),
            "source": order.get("source") or "manual",
            "spread": costs["spread"],
            "spreadPips": costs["spreadPips"],
            "currentSpread": costs["spread"],
            "currentSpreadPips": costs["spreadPips"],
            "estimatedSlippagePips": costs["estimatedSlippagePips"],
            "estimatedSlippage": costs["estimatedSlippage"],
            "estimatedCostPerUnit": costs["estimatedCostPerUnit"],
            "expectedFillPrice": fill_tracking["expectedFillPrice"],
            "actualFillPrice": fill_tracking["actualFillPrice"],
            "spreadCost": fill_tracking["spreadCost"],
            "actualSlippage": fill_tracking["actualSlippage"],
            "actualSlippagePips": fill_tracking["actualSlippagePips"],
        })

        mt5_safety.record(envelope, "filled", {"orderId": order_record["id"], "positionId": position["id"]})
        execution_delay = int(time.time() * 1000) - envelope.get("submitted_at", int(time.time() * 1000))
        from ..observability.init import record_mt5_execution_delay  # lazy import
        record_mt5_execution_delay(max(0, execution_delay), symbol=symbol, side=order.get("side"))
        fingerprint = order.get("newsFingerprint")
        if fingerprint:
            self.news_traded.insert({"fingerprint": fingerprint, "orderId": order_record["id"], "symbol": symbol, "tradedAt": int(time.time() * 1000)})

        event_bus.emit("trade:opened", {"position": position})
        logger.info(f"Order filled: {order.get('side', '').upper()} {volume} {symbol} @ {price:.5f}")
        return {"status": "filled", "order": order_record, "position": position}

    def close_position(self, position_id, reason="manual", price=None):
        position = self.col.find_one({"id": position_id})
        if not position:
            return None
        if position.get("status") != "open":
            logger.info(f"Position {position_id} already closed — close action is idempotent")
            return {"status": "already-closed", "position": position}
        quote = get_quote(position["symbol"])
        exit_price = price or (quote["bid"] if position["side"] == "buy" else quote["ask"])
        profit = (exit_price - position["entryPrice"]) * position["volume"] if position["side"] == "buy" else (position["entryPrice"] - exit_price) * position["volume"]
        updated = self.col.update(position_id, {
            "status": "closed",
            "exitPrice": round(exit_price * 100000) / 100000,
            "profit": round(profit * 100) / 100,
            "closedAt": int(time.time() * 1000),
            "closeReason": reason,
        })
        event_bus.emit("trade:closed", {"position": updated})
        logger.info(f"Position closed: {position['symbol']} {reason} pnl={profit:.2f}")
        return updated

    def modify_position(self, position_id, patch):
        position = self.col.find_one({"id": position_id})
        if not position:
            return None
        updated = self.col.update(position_id, {**patch, "modifiedAt": int(time.time() * 1000)})
        event_bus.emit("trade:modified", {"position": updated})
        return updated

    def partial_close(self, position_id, percent, price=None):
        position = self.col.find_one({"id": position_id})
        if not position:
            return None
        close_vol = position["volume"] * percent
        quote = get_quote(position["symbol"])
        exit_price = price or (quote["bid"] if position["side"] == "buy" else quote["ask"])
        profit = (exit_price - position["entryPrice"]) * close_vol if position["side"] == "buy" else (position["entryPrice"] - exit_price) * close_vol
        remaining = position["volume"] - close_vol
        closed = self.col.insert({
            **position,
            "id": None,
            "volume": round(close_vol * 100) / 100,
            "exitPrice": round(exit_price * 100000) / 100000,
            "profit": round(profit * 100) / 100,
            "status": "closed",
            "closedAt": int(time.time() * 1000),
            "closeReason": "partial",
        })
        self.col.update(position_id, {"volume": round(remaining * 100) / 100, "partial": True})
        event_bus.emit("trade:partial-close", {"position": position, "closed": closed})
        return {"remaining": self.col.find_one({"id": position_id}), "closed": closed}

    def reverse_position(self, position_id):
        position = self.col.find_one({"id": position_id})
        if not position:
            return None
        if position.get("status") != "open":
            return {"status": "position-not-open", "position": position}
        # Safety: the original position must be confirmed closed BEFORE the
        # opposite order is placed (no overlap, no phantom hedging).
        closed = self.close_position(position_id, "reverse-wait")
        if not closed or closed.get("status") != "closed":
            return {"status": "rejected", "violations": ["close-not-confirmed"], "position": position}
        quote = get_quote(position["symbol"])
        current = quote["bid"] if position["side"] == "buy" else quote["ask"]
        new_side = "sell" if position["side"] == "buy" else "buy"
        stop_loss = None
        take_profit = None
        if position.get("stopLoss") is not None:
            sl_dist = abs(position["entryPrice"] - position["stopLoss"])
            stop_loss = current - sl_dist if new_side == "buy" else current + sl_dist
        if position.get("takeProfit") is not None:
            tp_dist = abs(position["takeProfit"] - position["entryPrice"])
            take_profit = current + tp_dist if new_side == "buy" else current - tp_dist
        reverse = self.place_order({
            "symbol": position["symbol"],
            "side": new_side,
            "volume": position["volume"],
            "stopLoss": round(stop_loss * 100000) / 100000 if stop_loss else None,
            "takeProfit": round(take_profit * 100000) / 100000 if take_profit else None,
            "comment": "reverse-trade",
            "source": "system",
        })
        if reverse["status"] == "rejected":
            return {"status": "rejected", "violations": reverse["violations"], "position": position, "closed": closed}
        return {**reverse, "reversedFrom": position_id, "closedPosition": closed}

    def dynamic_reanalysis(self):
        positions = self.col.find({"status": "open"})
        analyzed = []
        for p in positions:
            if p.get("source") != "ai-decision" and p.get("confidence") is None:
                continue
            quote = get_quote(p["symbol"])
            current = quote["bid"] if p["side"] == "buy" else quote["ask"]
            unrealized = (current - p["entryPrice"]) * p["volume"] if p["side"] == "buy" else (p["entryPrice"] - current) * p["volume"]
            pnl_pct = (unrealized / (p["entryPrice"] * p["volume"]) * 100) if p["entryPrice"] > 0 else 0
            action = "hold"
            reason = ""
            if p.get("takeProfit") is not None and ((p["side"] == "buy" and current >= p["takeProfit"] * 0.9) or (p["side"] == "sell" and current <= p["takeProfit"] * 1.1)):
                action = "modify-tp"
                reason = "Price approaching take profit, tightening target"
            elif p.get("stopLoss") is not None and ((p["side"] == "buy" and current <= p["stopLoss"] * 1.01) or (p["side"] == "sell" and current >= p["stopLoss"] * 1.01)):
                action = "modify-sl"
                reason = "Price approaching stop loss, protecting capital"
            elif pnl_pct > 0.4:
                action = "partial-close"
                reason = f"Taking partial profit at {pnl_pct:.2f}% gain"
            analyzed.append({"positionId": p["id"], "symbol": p["symbol"], "side": p["side"], "current": current, "unrealized": round(unrealized * 100) / 100, "pnlPct": round(pnl_pct * 100) / 100, "action": action, "reason": reason})
        event_bus.emit("trading:reanalysis", {"analyzed": analyzed, "timestamp": int(time.time() * 1000)})
        return analyzed

    def monitor_open_positions(self):
        positions = self.col.find({"status": "open"})
        for p in positions:
            quote = get_quote(p["symbol"])
            current = quote["bid"] if p["side"] == "buy" else quote["ask"]
            profit = round(((current - p["entryPrice"]) * p["volume"]) * 100) / 100 if p["side"] == "buy" else round(((p["entryPrice"] - current) * p["volume"]) * 100) / 100
            patch = {"profit": profit}
            live_costs = _estimate_execution_costs(quote, get_instrument(p["symbol"]))
            patch["currentSpread"] = live_costs["spread"]
            patch["currentSpreadPips"] = live_costs["spreadPips"]
            self.col.update(p["id"], patch)
            if p.get("stopLoss") is not None and ((p["side"] == "buy" and current <= p["stopLoss"]) or (p["side"] == "sell" and current >= p["stopLoss"])):
                self.close_position(p["id"], "stop-loss", p["stopLoss"])
            if p.get("takeProfit") is not None and ((p["side"] == "buy" and current >= p["takeProfit"]) or (p["side"] == "sell" and current <= p["takeProfit"])):
                self.close_position(p["id"], "take-profit", p["takeProfit"])

    def get_open_positions(self):
        return self.col.find({"status": "open"})

    def get_orders(self, params=None):
        params = params or {}
        orders = self.order_col.find({})
        if params.get("status"):
            orders = [o for o in orders if o["status"] == params["status"]]
        orders = sorted(orders, key=lambda o: o["timestamp"], reverse=True)
        return orders[: int(params.get("limit", "50"))]


trading_engine = TradingEngine()


def init_trading_engine():
    def _monitor_loop():
        while True:
            time.sleep(1.5)
            try:
                trading_engine.monitor_open_positions()
            except Exception:
                pass

    def _reanalysis_loop():
        while True:
            time.sleep(30)
            try:
                if feature_flags.get("trading.dynamicReanalysis"):
                    trading_engine.dynamic_reanalysis()
            except Exception:
                pass

    threading.Thread(target=_monitor_loop, daemon=True).start()
    threading.Thread(target=_reanalysis_loop, daemon=True).start()

    logger.info("Trading engine initialized")
    return trading_engine

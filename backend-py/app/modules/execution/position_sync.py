"""Repository-backed execution extension (additive).

Syncs open positions through the repository layer and re-evaluates them when a
new AI decision (or contradicting news) arrives: if the fresh consensus for a
symbol drops below the 70% auto-close threshold, or an opposite-news action
orders a close, the position is closed through the existing auto-trade
controller (no change to the original execution pipeline).

Also wires the approval trigger: when a suggested trade is accepted via
``auto_trade_controller.approve_suggested`` (``suggested:trade-approved``), the
accepted trade is routed to ``trading_engine.place_order`` so it still passes
the full fail-closed safety + risk-engine + portfolio-gate chain (no bypass).
"""
import asyncio
import threading
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...persistence import position_repository
from .auto_controller import auto_trade_controller
from .thesis import opposite_news_engine, thesis_manager


class RepositoryPositionSync:
    def __init__(self):
        self._lock = threading.Lock()

    # ---- Repository-backed persistence --------------------------------- #
    def upsert_position(self, position):
        """Persist/refresh a position through the repository layer."""
        try:
            return asyncio.run(position_repository.upsert(position))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(position_repository.upsert(position))

    def list_open_positions(self):
        try:
            return asyncio.run(position_repository.list_open())
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(position_repository.list_open())

    def sync_from_mt5(self, mt5_positions):
        """Persist every MT5 position snapshot through the repository."""
        synced = []
        for pos in mt5_positions or []:
            synced.append(self.upsert_position(pos))
        return synced

    # ---- Auto-close below 70% on opposite news / low confidence --------- #
    def evaluate_open_positions(self, decision=None, news=None):
        """Re-run the auto-close gates for every open position."""
        actions = []
        for position in self.list_open_positions():
            result = self._evaluate_one(position, decision, news)
            if result:
                actions.append({"position_id": position.get("id"), **result})
        return actions

    def _evaluate_one(self, position, decision=None, news=None):
        symbol = position.get("symbol") or "XAUUSD"
        pos_side = (position.get("side") or position.get("direction") or "buy").lower()

        if decision and decision.get("symbol") == symbol:
            direction = (decision.get("direction") or "no_trade").lower()
            confidence = decision.get("confidence")
            if isinstance(confidence, dict):
                confidence = confidence.get("score")
            if confidence is None:
                confidence = 0.0

            # Opposite-direction consensus below the 70% gate -> auto-close.
            opposite = {"buy": "sell", "sell": "buy"}.get(pos_side)
            if direction == opposite and float(confidence) < 0.70:
                verdict = auto_trade_controller.evaluate_open_trade(
                    position, float(confidence), initial_confidence=position.get("initialConfidence")
                )
                auto_trade_controller.record_reanalysis(
                    position, decision, verdict["action"], verdict.get("reason", "opposite-news low confidence")
                )
                self.upsert_position({**position, "status": "closed", "closedAt": int(time.time() * 1000)})
                event_bus.emit("position:auto-closed", {"position": position, "decision": decision, "verdict": verdict})
                return {"action": verdict["action"], "reason": verdict.get("reason", "opposite-direction confidence < 0.70")}

        if news and news.get("relevant") and news.get("contradictionSeverity", 0) >= 0.5:
            thesis = thesis_manager.get_thesis(position.get("id"))
            if thesis is None:
                return None
            action = opposite_news_engine.evaluate(position, news, thesis, context={"pnlPct": position.get("profitPct") or 0})
            if action.get("action") in ("CLOSE", "REVERSE", "PARTIAL_CLOSE"):
                auto_trade_controller.record_reanalysis(
                    position, {"news": news}, action["action"], action.get("reason", "opposite-news")
                )
                if action.get("action") in ("CLOSE", "REVERSE"):
                    self.upsert_position({**position, "status": "closed", "closedAt": int(time.time() * 1000)})
                event_bus.emit("position:opposite-news-action", {"position": position, "action": action})
                return {"action": action["action"], "reason": action.get("reason", "opposite-news")}
        return None


def _execute_accepted_suggestion(trade_id):
    """Execute an accepted suggested trade through the risk-gated engine.

    Runs in a daemon thread so the async event bus is never blocked. The order
    goes through ``trading_engine.place_order`` — the full fail-closed safety,
    risk-engine and portfolio-gate chain. Nothing is bypassed; a rejection is
    recorded on the suggestion so the state is always visible.
    """
    from ..trading.engine import trading_engine  # lazy import avoids cycles

    row = auto_trade_controller.col.find_one({"id": trade_id})
    if not row or row.get("status") != "accepted":
        return
    side = str(row.get("side") or "").lower()
    if side not in ("buy", "sell"):
        return
    order = {
        "symbol": row.get("symbol"),
        "side": side,
        "volume": row.get("lotSize") or 0.1,
        "stopLoss": row.get("stopLoss"),
        "takeProfit": row.get("takeProfit"),
        "comment": "suggested-approval",
        "source": "ai-decision",
        "confidence": row.get("confidence"),
    }
    try:
        result = trading_engine.place_order(order)
    except Exception as exc:  # noqa: BLE001 - a failure must never crash the bus
        logger.warn(f"Suggested-trade execution failed for {trade_id}: {exc}")
        auto_trade_controller.col.update(trade_id, {"executionStatus": "error", "executionError": str(exc)})
        return
    patch = {"executionStatus": result.get("status")}
    if result.get("status") == "filled":
        patch["status"] = "executed"
        patch["orderId"] = (result.get("order") or {}).get("id")
        patch["executedAt"] = int(time.time() * 1000)
    else:
        patch["rejectReason"] = "; ".join(result.get("violations") or []) or result.get("status")
    auto_trade_controller.col.update(trade_id, patch)
    event_bus.emit("suggested:trade-executed", {"trade_id": trade_id, "result": result})


position_sync = RepositoryPositionSync()


def init_position_sync():
    def _on_decision(event):
        decision = event.get("decision") or {}
        threading.Thread(
            target=position_sync.evaluate_open_positions, args=(decision, None), daemon=True
        ).start()

    def _on_news(event):
        item = event.get("item") or event.get("payload") or {}
        threading.Thread(
            target=position_sync.evaluate_open_positions, args=(None, item), daemon=True
        ).start()

    def _on_suggestion_approved(event):
        payload = event.get("payload") or event
        trade_id = payload.get("trade_id")
        if not trade_id:
            return
        threading.Thread(target=_execute_accepted_suggestion, args=(trade_id,), daemon=True).start()

    event_bus.on("ai:decision", _on_decision)
    event_bus.on("news:processed", _on_news)
    event_bus.on("suggested:trade-approved", _on_suggestion_approved)
    logger.info("Repository position sync initialized (auto-close <70% on opposite news)")
    return position_sync

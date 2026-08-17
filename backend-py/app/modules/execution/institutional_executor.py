"""Institutional Execution Engine (additive).

Bridges the new 5-agent decision pipeline (``consensus_v2``, float confidence,
``AUTO_EXECUTE`` / ``SUGGESTED`` / ``NO_TRADE`` statuses) to real MT5
fulfillment. The legacy executors expect ``decision["confidence"]`` as a dict
``{"score": ...}``; the new pipeline emits a float, so they can never fire.
This module handles the new format without touching any existing code.

Gates (per Module 4 of the institutional spec):
  - >= 90% (``AUTO_EXECUTE``) -> market order via MT5 with a Decimal-calculated
    lot size, SL and TP (only when an auto-execution trading mode is active).
  - 70-89% (``SUGGESTED``)    -> recorded as a suggested trade for approval.
  - < 70% (``NO_TRADE``)      -> ignored (logged for transparency).

Every financial value (equity, risk %, lot, SL, TP, price) is computed with
``Decimal`` (NO FLOATS) and the resulting position is persisted through the
repository layer (PostgreSQL NUMERIC when Postgres is enabled).
"""
import asyncio
import threading
import time
import uuid
from decimal import Decimal, ROUND_HALF_UP

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.distributed_event_bus import distributed_event_bus
from ...persistence import position_repository
from ..marketdata.engine import get_quote, generate_candles
from ..marketdata.instrument_specs import instrument_specs
from ..portfolio.service import portfolio_service
from ..risk.deterministic import position_sizer
from ..mt5.adapter import _place_order
from .modes import trading_modes, AUTO_EXECUTION_MODES
from .auto_controller import auto_trade_controller

AUTO_EXECUTE_STATUS = "AUTO_EXECUTE"
SUGGESTED_STATUS = "SUGGESTED"
NO_TRADE_STATUS = "NO_TRADE"


def _dec(value, default=None):
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal(str(default)) if default is not None else None


class InstitutionalExecutor:
    def __init__(self):
        self.stats = {"executed": 0, "suggested": 0, "skipped": 0}

    # ------------------------------------------------------------------ #
    # Pipeline format detection
    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_new_pipeline(decision):
        """The new pipeline emits confidence as a float (not a dict)."""
        confidence = decision.get("confidence")
        return confidence is not None and not isinstance(confidence, dict)

    # ------------------------------------------------------------------ #
    # Decimal lot sizing (NO FLOATS)
    # ------------------------------------------------------------------ #
    def _lot_size(self, decision, entry, stop):
        symbol = decision.get("symbol", "XAUUSD")
        if entry is None or stop is None:
            return Decimal("0.01")
        equity = _dec(portfolio_service.get().get("equity"), Decimal("10000"))
        profile = trading_modes.get_profile()
        risk_pct = Decimal(str(profile.get("risk_per_trade", 1.0)))
        if equity <= Decimal("0") or risk_pct <= Decimal("0"):
            return Decimal("0.01")
        risk_money = equity * risk_pct / Decimal("100")
        pip_value = Decimal(str(instrument_specs.pip_value_per_lot(symbol)))
        pips = Decimal(str(instrument_specs.pips_between(symbol, float(entry), float(stop))))
        if pip_value <= Decimal("0") or pips <= Decimal("0"):
            return Decimal("0.01")
        volume = (risk_money / (pips * pip_value)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return max(Decimal("0.01"), volume)

    # ------------------------------------------------------------------ #
    # MT5 market order execution
    # ------------------------------------------------------------------ #
    async def _execute_market_order(self, decision, entry, stop, tp):
        symbol = decision.get("symbol", "XAUUSD")
        side = str(decision.get("direction") or "").lower()
        quote = get_quote(symbol)
        price = _dec(quote.get("ask") if side == "buy" else quote.get("bid"), Decimal("0"))
        lot = self._lot_size(decision, entry, stop)

        order = {
            "symbol": symbol,
            "side": side,
            "type": "market",
            "volume": float(lot),
            "price": float(price),
            "stopLoss": float(stop) if stop is not None else None,
            "takeProfit": float(tp) if tp is not None else None,
            "comment": "institutional-ai",
            "source": "ai-decision",
            "decision_id": decision.get("id"),
            "idempotency_key": f"ai-{decision.get('id') or uuid.uuid4().hex[:12]}",
        }
        try:
            placed = await _place_order(order)
        except Exception as exc:  # noqa: BLE001 - MT5 must never crash the loop
            logger.error(f"Institutional MT5 order failed for {symbol}: {exc}")
            event_bus.emit("institutional:execution-error", {"symbol": symbol, "error": str(exc)})
            return {"status": "error", "error": str(exc)}

        position = {
            "id": f"pos-{decision.get('id') or uuid.uuid4().hex[:12]}",
            "symbol": symbol,
            "side": side,
            "lotSize": lot,
            "entry": entry,
            "stopLoss": stop,
            "takeProfit": tp,
            "currentPrice": price,
            "profit": None,
            "status": "open",
            "initialConfidence": decision.get("confidence"),
            "newsIds": decision.get("newsIds") or [],
            "mt5Ticket": (placed or {}).get("ticket") or (placed or {}).get("mt5Ticket"),
            "openedAt": int(time.time() * 1000),
        }
        try:
            await position_repository.upsert(position)
        except Exception as exc:  # noqa: BLE001 - persistence failure must not hide execution
            logger.warn(f"Institutional position persist failed: {exc}")

        self.stats["executed"] += 1
        event_bus.emit("institutional:order-placed", {"decision": decision, "order": order, "placed": placed})
        try:
            distributed_event_bus.publish("institutional:order-placed", {"decision": decision, "order": order})
        except Exception:  # noqa: BLE001
            pass
        logger.info(f"Institutional executor placed {side.upper()} {symbol} lot={lot} "
                    f"sl={stop} tp={tp} (decision {decision.get('id')})")
        return {"status": "placed", "order": order, "result": placed, "position": position}

    # ------------------------------------------------------------------ #
    # Suggestion recording (legacy-compatible shape)
    # ------------------------------------------------------------------ #
    def _record_suggestion(self, decision):
        symbol = decision.get("symbol", "XAUUSD")
        direction = str(decision.get("direction") or "hold")
        confidence = _dec(decision.get("confidence"), Decimal("0"))
        legacy = {
            "symbol": symbol,
            "confidence": {"score": float(confidence)},
            "recommendation": {"direction": direction, "action": "recommend"},
            "id": decision.get("id"),
            "xai": decision.get("xai") or {},
        }
        try:
            row = auto_trade_controller.create_suggested_trade(legacy)
            self.stats["suggested"] += 1
            event_bus.emit("institutional:suggestion", {"decision": decision, "suggested": row})
            return row
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"Institutional suggestion recording failed: {exc}")
            return None

    # ------------------------------------------------------------------ #
    # Decision handler
    # ------------------------------------------------------------------ #
    def handle(self, decision):
        if not decision or not self._is_new_pipeline(decision):
            self.stats["skipped"] += 1
            return {"status": "skipped", "reason": "legacy-format"}

        status = str(decision.get("status") or "NO_TRADE").upper()
        if status == NO_TRADE_STATUS or decision.get("riskApproved") is False:
            self.stats["skipped"] += 1
            return {"status": "skipped", "reason": status}

        symbol = decision.get("symbol", "XAUUSD")
        direction = str(decision.get("direction") or "").lower()
        entry = _dec(decision.get("entry"))
        stop = _dec(decision.get("stopLoss"))
        tp = _dec(decision.get("takeProfit"))

        if direction not in ("buy", "sell"):
            self.stats["skipped"] += 1
            return {"status": "skipped", "reason": "no-direction"}

        # Technical execution must have confirmed an entry (SL present).
        if status == AUTO_EXECUTE_STATUS:
            if stop is None:
                stop = self._fallback_stop(symbol, direction, entry)
            if entry is None or stop is None:
                self.stats["skipped"] += 1
                return {"status": "skipped", "reason": "no-execution-levels"}
            mode = trading_modes.get_mode()
            if mode in AUTO_EXECUTION_MODES:
                try:
                    return asyncio.run(self._execute_market_order(decision, entry, stop, tp))
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    try:
                        return loop.run_until_complete(self._execute_market_order(decision, entry, stop, tp))
                    finally:
                        loop.close()
            # Auto mode off: degrade to a suggestion for manual approval.
            return {"status": "suggested", "reason": f"auto-mode-off({mode})", "suggested": self._record_suggestion(decision)}

        if status == SUGGESTED_STATUS:
            return {"status": "suggested", "suggested": self._record_suggestion(decision)}

        self.stats["skipped"] += 1
        return {"status": "skipped", "reason": status}

    # ------------------------------------------------------------------ #
    # Fallback SL via ATR when the pipeline produced no stop level
    # ------------------------------------------------------------------ #
    @staticmethod
    def _fallback_stop(symbol, direction, entry):
        try:
            candles = generate_candles(symbol, "H1", 20)
            atr = _dec(candles[-1]["high"] - candles[-1]["low"], Decimal("1"))
        except Exception:  # noqa: BLE001
            atr = Decimal("1")
        # A flat candle (high == low, e.g. an inactive session bar) or any
        # non-positive range would otherwise produce a zero-distance stop
        # equal to entry. Fall back to the default ATR so the SL is always
        # a real distance away from the entry price.
        if atr is None or atr <= Decimal("0"):
            atr = Decimal("1")
        return entry - atr * Decimal("1.5") if direction == "buy" else entry + atr * Decimal("1.5")

    # ------------------------------------------------------------------ #
    # Event wiring
    # ------------------------------------------------------------------ #
    def _on_decision(self, event):
        decision = (event.get("payload") or {}).get("decision") or {}
        threading.Thread(target=self.handle, args=(decision,), daemon=True).start()

    def status(self):
        return dict(self.stats)


institutional_executor = InstitutionalExecutor()


def init_institutional_executor():
    event_bus.on("AIDecisionMade", institutional_executor._on_decision)
    logger.info("Institutional execution engine initialized (>=90% auto-execute, 70-89% suggestion, <70% NO_TRADE)")
    return institutional_executor

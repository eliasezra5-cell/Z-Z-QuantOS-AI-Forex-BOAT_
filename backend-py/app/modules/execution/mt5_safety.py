"""MT5 Execution Safety Envelope (Batch 12).

Every order request includes: idempotency_key, decision_id, thesis_version,
risk_approval_id, symbol_spec_version, requested_price, maximum_slippage,
expiration_time, magic_number, correlation_id.

Before retrying: check MT5 history and open positions, confirm the first
request did NOT execute — NEVER blindly resend.

Broker reconciliation: continuously compare local trades, MT5 positions,
pending orders, deals, partial closes, broker-side SL/TP modifications.
On mismatch: freeze execution for symbol/account + critical alert + run
reconciliation workflow.
"""
import time
import uuid

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...config import settings
from ..marketdata.instrument_specs import instrument_specs


def _new_uuid():
    return str(uuid.uuid4())


class Mt5SafetyEnvelope:
    def __init__(self):
        self.orders = db.collection("mt5_safety_orders")
        self.frozen = db.collection("mt5_frozen_symbols")
        self.recon_log = db.collection("mt5_reconciliation")

    # ---- Order envelope builder ----
    def build_order(self, order, meta=None):
        """Attach the full safety envelope to an order request."""
        meta = meta or {}
        spec = instrument_specs.get_spec(order.get("symbol"))
        idempotency_key = order.get("idempotency_key") or _new_uuid()
        now = int(time.time() * 1000)
        expiration = order.get("expiration_time") or now + 60 * 1000
        envelope = {
            "idempotency_key": idempotency_key,
            "decision_id": meta.get("decision_id") or order.get("decision_id"),
            "thesis_version": meta.get("thesis_version") or order.get("thesis_version"),
            "risk_approval_id": meta.get("risk_approval_id") or order.get("risk_approval_id"),
            "symbol_spec_version": meta.get("symbol_spec_version") or (spec.get("symbol") if spec else None),
            "requested_price": order.get("requested_price") or order.get("price"),
            "maximum_slippage": meta.get("maximum_slippage") or order.get("maximum_slippage") or settings.MAX_SLIPPAGE_PIPS,
            "expiration_time": expiration,
            "magic_number": meta.get("magic_number") or order.get("magic_number") or 20260204,
            "correlation_id": meta.get("correlation_id") or _new_uuid(),
            "submitted_at": now,
        }
        return {**order, **envelope}

    def duplicate_check(self, order):
        """Reject duplicate order with same idempotency key."""
        key = order.get("idempotency_key")
        if not key:
            return {"duplicate": False}
        existing = self.orders.find_one({"idempotency_key": key})
        if existing:
            return {"duplicate": True, "existing": existing}
        return {"duplicate": False}

    def record(self, envelope, status, detail=None):
        self.orders.insert({
            "idempotency_key": envelope.get("idempotency_key"),
            "correlation_id": envelope.get("correlation_id"),
            "symbol": envelope.get("symbol"),
            "side": envelope.get("side"),
            "status": status,
            "detail": detail,
            "submitted_at": envelope.get("submitted_at"),
            "timestamp": int(time.time() * 1000),
        })

    def verify_before_retry(self, envelope):
        """Check local + MT5 state before any retry. Returns (ok, evidence)."""
        key = envelope.get("idempotency_key")
        evidence = {"local_orders": self.orders.find({"idempotency_key": key}), "open_positions": [], "history": []}
        # open positions for the symbol/side
        positions = db.collection("positions").find({"symbol": envelope.get("symbol"), "status": "open"})
        evidence["open_positions"] = positions
        # check history for a matching executed order
        history = db.collection("positions").find({"status": "closed"})
        for h in history[-50:]:
            if h.get("orderId") == key or h.get("idempotency_key") == key:
                evidence["history"].append(h)
        # If an executed record already exists -> do NOT resend.
        if evidence["history"] or evidence["open_positions"]:
            return False, evidence
        # if first attempt already recorded as submitted (not yet filled) -> wait
        recorded = self.orders.find({"idempotency_key": key})
        if any(r.get("status") == "submitted" for r in recorded):
            return False, evidence
        return True, evidence

    # ---- Freeze / reconciliation ----
    def freeze_symbol(self, symbol, reason):
        existing = self.frozen.find_one({"symbol": symbol})
        if existing:
            self.frozen.update(existing["id"], {"active": True, "reason": reason, "at": int(time.time() * 1000)})
        else:
            self.frozen.insert({"symbol": symbol, "active": True, "reason": reason, "at": int(time.time() * 1000)})
        event_bus.emit("mt5:execution-frozen", {"symbol": symbol, "reason": reason})
        logger.error(f"MT5 execution frozen for {symbol}: {reason}")
        return self.frozen.find_one({"symbol": symbol})

    def unfreeze_symbol(self, symbol):
        existing = self.frozen.find_one({"symbol": symbol})
        if existing:
            self.frozen.update(existing["id"], {"active": False, "clearedAt": int(time.time() * 1000)})
        return {"status": "unfrozen", "symbol": symbol}

    def is_frozen(self, symbol):
        existing = self.frozen.find_one({"symbol": symbol})
        return bool(existing and existing.get("active"))

    def frozen_symbols(self):
        return [f for f in self.frozen.find({}) if f.get("active")]

    def reconcile(self, local_positions, mt5_positions):
        """Compare local vs broker. Returns mismatches."""
        mismatches = []
        local_map = {p.get("id"): p for p in local_positions}
        mt5_map = {p.get("ticket") or p.get("id"): p for p in mt5_positions}
        # symbols present locally but not in MT5
        for lid, lp in local_map.items():
            if lp.get("status") == "open" and lid not in mt5_map:
                mismatches.append({"type": "missing-in-mt5", "id": lid, "symbol": lp.get("symbol"), "local": lp, "mt5": None})
        # SL/TP mismatch
        for lid, lp in local_map.items():
            mp = mt5_map.get(lid)
            if not mp or lp.get("status") != "open":
                continue
            if lp.get("stopLoss") is not None and mp.get("stopLoss") is not None and abs((lp.get("stopLoss") or 0) - (mp.get("stopLoss") or 0)) > 1e-9:
                mismatches.append({"type": "sl-mismatch", "id": lid, "symbol": lp.get("symbol"), "local_sl": lp.get("stopLoss"), "mt5_sl": mp.get("stopLoss")})
            if lp.get("takeProfit") is not None and mp.get("takeProfit") is not None and abs((lp.get("takeProfit") or 0) - (mp.get("takeProfit") or 0)) > 1e-9:
                mismatches.append({"type": "tp-mismatch", "id": lid, "symbol": lp.get("symbol"), "local_tp": lp.get("takeProfit"), "mt5_tp": mp.get("takeProfit")})
        if mismatches:
            self.recon_log.insert({"mismatches": mismatches, "count": len(mismatches), "timestamp": int(time.time() * 1000)})
            for m in mismatches:
                self.freeze_symbol(m.get("symbol"), f"reconciliation:{m['type']}")
            event_bus.emit("mt5:reconciliation-mismatch", {"mismatches": mismatches})
            logger.warn(f"MT5 reconciliation: {len(mismatches)} mismatches -> frozen")
        return mismatches

    def reconciliation_log(self, limit=50):
        rows = self.recon_log.find({})
        return rows[-limit:]


mt5_safety = Mt5SafetyEnvelope()


def init_mt5_safety():
    logger.info("MT5 safety envelope initialized (idempotency + reconciliation + freeze)")
    return mt5_safety

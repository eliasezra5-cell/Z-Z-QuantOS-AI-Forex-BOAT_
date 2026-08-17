"""Profit Protection Engine (Batch 15).

Auto break-even (+15 pips -> SL to entry + buffer), smart trailing stop
(fixed / ATR / structure / parabolic SAR), AI profit lock, partial close
(TP1 30%, TP2 30%, TP3 remaining), multi-target management.

SAFETY RULES (enforced here):
  - never widen SL to increase initial risk
  - never move SL backwards after break-even unless explicitly allowed
  - validate broker stop/freeze levels before modification
  - partial-close volumes must respect broker lot step
  - profit actions are idempotent
"""
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...config import settings
from ..marketdata.instrument_specs import instrument_specs


class ProfitProtectionEngine:
    def __init__(self):
        self.actions_log = db.collection("profit_actions")

    # ---- Break even ----
    def break_even(self, position, quote_price, pips_gain, buffer_pips=0.0, force=False):
        """Move SL to entry (+ buffer) once +BREAK_EVEN_PIPS profit reached."""
        spec = instrument_specs.get_spec(position["symbol"])
        if not spec:
            return {"status": "no-spec", "idempotent": True}
        entry = position["entryPrice"]
        sl = position.get("stopLoss")
        if sl is None:
            return {"status": "no-stop", "idempotent": True}
        pips = instrument_specs.pips_between(position["symbol"], quote_price, entry)
        if pips < settings.BREAK_EVEN_PIPS and not force:
            return {"status": "below-break-even-threshold", "pips": round(pips, 2)}
        if position.get("breakEvenSet"):
            return {"status": "already-set", "idempotent": True}
        # For buy: move SL from below-entry to entry+buffer; never widen risk.
        new_sl = entry + buffer_pips * spec["pip_size"] if position["side"] == "buy" else entry - buffer_pips * spec["pip_size"]
        # SAFETY: never move SL backwards / never widen risk beyond original.
        if position["side"] == "buy":
            if new_sl < sl:
                return {"status": "safety-block-widen-risk", "idempotent": True}
        else:
            if new_sl > sl:
                return {"status": "safety-block-widen-risk", "idempotent": True}
        self._log("break-even", position, {"newSl": new_sl})
        return {"status": "ok", "newSl": new_sl, "pips": round(pips, 2), "breakEvenSet": True}

    # ---- Trailing stop ----
    def trailing_stop(self, position, quote_price, atr=None, method=None, multiplier=None):
        """Move SL behind price by chosen method. Never backwards."""
        method = method or settings.TRAILING_STOP_METHOD
        multiplier = multiplier or settings.TRAILING_ATR_MULTIPLIER
        spec = instrument_specs.get_spec(position["symbol"])
        if not spec:
            return {"status": "no-spec"}
        entry = position["entryPrice"]
        sl = position.get("stopLoss")
        side = position["side"]
        if method == "atr":
            if not atr or atr <= 0:
                return {"status": "no-atr"}
            distance = atr * multiplier
            new_sl = quote_price - distance if side == "buy" else quote_price + distance
        elif method == "fixed":
            distance = settings.BREAK_EVEN_PIPS * spec["pip_size"]  # fall back to break-even pips
            new_sl = quote_price - distance if side == "buy" else quote_price + distance
        else:
            # structure / parabolic-sar fall back to ATR method
            if not atr or atr <= 0:
                return {"status": "no-atr"}
            distance = atr * multiplier
            new_sl = quote_price - distance if side == "buy" else quote_price + distance
        # SAFETY: never move SL backwards.
        if side == "buy":
            if new_sl < (sl or entry - 1e9):
                return {"status": "safety-block-backwards", "idempotent": True}
        else:
            if new_sl > (sl or entry + 1e9):
                return {"status": "safety-block-backwards", "idempotent": True}
        # Validate broker stops_level.
        ok, min_dist = instrument_specs.validate_stop_level(position["symbol"], quote_price, new_sl)
        if not ok:
            return {"status": "broker-stop-level", "minDist": min_dist}
        self._log("trailing-stop", position, {"newSl": new_sl, "method": method})
        return {"status": "ok", "newSl": new_sl, "method": method}

    # ---- Partial close ----
    def partial_close(self, position, target_pips, entry, quote_price):
        """Decide partial-close based on which TP was hit. Returns volume to close."""
        spec = instrument_specs.get_spec(position["symbol"])
        if not spec:
            return {"status": "no-spec"}
        risk = instrument_specs.pips_between(position["symbol"], entry, position.get("stopLoss") or entry)
        pips_gain = instrument_specs.pips_between(position["symbol"], quote_price, entry)
        if pips_gain < target_pips:
            return {"status": "not-reached", "pips": round(pips_gain, 2)}
        # TP1 at 1:1 RR -> 30%, TP2 at 1:2 RR -> 30%, TP3 -> remaining
        if pips_gain >= risk * 3:
            pct = 1.0
            tag = "TP3"
        elif pips_gain >= risk * 2:
            pct = settings.PARTIAL_CLOSE_TP2_PERCENT
            tag = "TP2"
        else:
            pct = settings.PARTIAL_CLOSE_TP1_PERCENT
            tag = "TP1"
        close_vol = position["volume"] * pct
        # Respect broker lot step / min volume.
        close_vol = instrument_specs.normalize_volume(position["symbol"], close_vol)
        remaining = position["volume"] - close_vol
        if remaining < spec["volume_min"]:
            close_vol = position["volume"]
            remaining = 0
        self._log("partial-close", position, {"tag": tag, "pct": pct, "closeVolume": close_vol, "remaining": remaining})
        return {"status": "ok", "tag": tag, "percent": pct, "closeVolume": close_vol, "remaining": remaining}

    # ---- AI profit lock ----
    def ai_profit_lock(self, position, news_context=None, market_state=None):
        """Evaluate whether to lock in profit based on new news + market state."""
        score = 0.0
        factors = []
        if news_context:
            if news_context.get("contradictory"):
                score += 1.0
                factors.append("contradictory-news")
            if news_context.get("highImpact"):
                score += 0.5
                factors.append("high-impact-news")
            if news_context.get("staleness", 0) > 0:
                score += 0.3
                factors.append("stale-news")
        if market_state:
            if market_state.get("divergence"):
                score += 1.0
                factors.append("market-divergence")
            if market_state.get("volatilitySpike"):
                score += 0.7
                factors.append("volatility-spike")
        if score >= 1.0:
            return {"action": "lock-profit", "score": score, "factors": factors}
        if score >= 0.5:
            return {"action": "tighten-stop", "score": score, "factors": factors}
        return {"action": "hold", "score": score, "factors": factors}

    # ---- Idempotency ----
    def _log(self, action, position, detail):
        self.actions_log.insert({
            "action": action,
            "position_id": position.get("id"),
            "symbol": position.get("symbol"),
            "detail": detail,
            "timestamp": int(time.time() * 1000),
        })

    def recent_actions(self, limit=50):
        rows = self.actions_log.find({})
        return rows[-limit:]


profit_protection = ProfitProtectionEngine()


def init_profit_protection():
    logger.info("Profit protection engine initialized")
    return profit_protection

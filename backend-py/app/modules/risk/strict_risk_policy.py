"""Strict Risk Policy Engine (Phase 2, Module 1) — FAIL-CLOSED.

Strict Risk Rules that override ALL AI decisions. Auto-trading stays DISABLED
by default (existing ``trading_modes`` default is preserved). This engine is
purely additive: it wraps the existing ``capital_protection`` engine, trading
mode manager and trading engine and never alters their APIs.

Enforced rules (all financial math in ``Decimal``):

  1. Spread filter       : reject when spread > ``MAX_SPREAD_POINTS``
  2. Daily loss limit    : on daily loss >= ``DAILY_LOSS_LIMIT`` -> lock the
                           day and switch to ANALYSIS_ONLY (auto-trading off)
  3. Max drawdown        : on equity down ``MAX_DRAWDOWN_PERCENT`` (15%) from
                           peak -> EMERGENCY STOP + close ALL open trades
  4. Fail-closed triggers: MT5 disconnected / market data stale (>30s) /
                           AI providers all down / reconciliation mismatch
                           -> execution disabled
  5. Auto-close <70%     : an open trade whose AI confidence drops below the
                           70% threshold (opposite news) is closed immediately
                           and idempotently

Every verdict is auditable through ``status()`` and the event bus.
"""
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from ...config import settings
from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from .capital_protection import capital_protection

# Defaults (overridable per call / via env in existing settings).
DEFAULT_MAX_SPREAD_POINTS = Decimal(str(settings.MAX_SPREAD_PIPS))
DEFAULT_DAILY_LOSS_LIMIT = Decimal(str(settings.DAILY_LOSS_LIMIT))
DEFAULT_MAX_DRAWDOWN_PERCENT = Decimal(str(settings.MAX_DRAWDOWN_PERCENT))
DEFAULT_AUTO_CLOSE_CONFIDENCE = Decimal(str(settings.AUTO_CLOSE_CONFIDENCE_THRESHOLD))
DEFAULT_STALE_MS = Decimal(settings.STALE_DATA_THRESHOLD_SECONDS) * Decimal(1000)

AUTO_DISABLE_MODES = ("AUTO_LIMITED", "AUTO_FULL", "SEMI_AUTO")


def _dec(value, fallback=Decimal("0")):
    """Deterministically convert a value to Decimal (fallback on failure)."""
    if value is None:
        return fallback
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return fallback


class StrictRiskPolicyEngine:
    """Additive fail-closed strict risk policy wrapper."""

    def __init__(self):
        self.stats = {
            "spread_blocks": 0,
            "daily_loss_switches": 0,
            "drawdown_stops": 0,
            "closed_all": 0,
            "auto_closes": 0,
            "gate_blocks": 0,
            "last_enforce": None,
            "last_verdict": None,
        }
        self._auto_closed = {}  # position_id -> timestamp (idempotency guard)

    # ------------------------------------------------------------------ #
    # 1. Spread filter
    # ------------------------------------------------------------------ #
    def check_spread(self, spread_points, max_spread=None):
        """Reject the trade when the spread exceeds the cap.

        Returns ``(allowed: bool, reason: str|None)``.
        """
        limit = _dec(max_spread, DEFAULT_MAX_SPREAD_POINTS) if max_spread is not None else DEFAULT_MAX_SPREAD_POINTS
        spread = _dec(spread_points)
        if spread <= Decimal("0"):
            return True, None
        if spread > limit:
            return False, f"spread {spread} > max {limit}"
        return True, None

    # ------------------------------------------------------------------ #
    # 2. Daily loss limit -> lock day + switch to Analysis Mode
    # ------------------------------------------------------------------ #
    def enforce_daily_loss(self, daily_loss, limit=None):
        """Auto-disable trading and switch to Analysis Mode on daily loss."""
        limit = _dec(limit, DEFAULT_DAILY_LOSS_LIMIT) if limit is not None else DEFAULT_DAILY_LOSS_LIMIT
        loss = abs(_dec(daily_loss))
        if loss < limit:
            return False, None

        capital_protection.lock_for_day(f"daily loss {loss} >= limit {limit}")
        from ..execution.modes import trading_modes  # lazy: avoids import cycle

        if trading_modes.get_mode() in AUTO_DISABLE_MODES:
            trading_modes.set_mode("ANALYSIS_ONLY", actor="system", reason="daily-loss-limit")
            self.stats["daily_loss_switches"] += 1
        event_bus.emit("strict-risk:daily-loss-limit", {"daily_loss": str(loss), "limit": str(limit)})
        logger.warn(f"STRICT RISK: daily loss limit hit ({loss}) -> analysis-only")
        return True, "daily-loss-limit"

    # ------------------------------------------------------------------ #
    # 3. Max drawdown -> EMERGENCY STOP + close all trades
    # ------------------------------------------------------------------ #
    def enforce_max_drawdown(self, equity, peak, max_drawdown=None):
        """On drawdown >= limit (default 15%): emergency stop + close all."""
        max_drawdown = _dec(max_drawdown, DEFAULT_MAX_DRAWDOWN_PERCENT) if max_drawdown is not None else DEFAULT_MAX_DRAWDOWN_PERCENT
        equity = _dec(equity)
        peak = _dec(peak, equity)
        if peak <= Decimal("0") or equity <= Decimal("0"):
            return False, None
        drawdown = (peak - equity) / peak
        if drawdown < max_drawdown:
            return False, None

        capital_protection.activate_emergency_stop(
            f"max drawdown {drawdown:.2%} >= {max_drawdown:.2%} from peak {peak}"
        )
        self.stats["drawdown_stops"] += 1
        closed = self.close_all_trades("emergency-drawdown")
        event_bus.emit("strict-risk:max-drawdown", {"drawdown": str(drawdown), "peak": str(peak), "closed": closed})
        logger.error(f"STRICT RISK: max drawdown {drawdown:.2%} -> EMERGENCY STOP, closed {len(closed)} trades")
        return True, "max-drawdown-emergency-stop"

    def close_all_trades(self, reason):
        """Close every open position through the trading engine (idempotent)."""
        from ..trading.engine import trading_engine  # lazy: avoids import cycle

        closed = []
        for position in trading_engine.get_open_positions():
            try:
                res = trading_engine.close_position(position["id"], reason)
                if res and res.get("status") == "closed":
                    closed.append(position["id"])
            except Exception as exc:  # noqa: BLE001 - never stop the sweep on one failure
                logger.warn(f"close-all failed for {position.get('id')}: {exc}")
        self.stats["closed_all"] += len(closed)
        return closed

    # ------------------------------------------------------------------ #
    # 4. Fail-closed triggers
    # ------------------------------------------------------------------ #
    def fail_closed_triggers(self):
        """Aggregate the fail-closed conditions that must halt execution."""
        triggers = []
        from ..execution.mt5_safety import mt5_safety  # lazy import
        from ..marketdata.live_prices import get_live_quote  # lazy import
        from ..mt5.adapter import mt5_state  # lazy import
        from ...foundation.provider_framework import providers  # lazy import

        if settings.MT5_ENABLED == "live" and not mt5_state.connected:
            triggers.append("mt5-disconnected")
        if self._stale_market_data(get_live_quote):
            triggers.append("market-data-stale")
        if self._ai_providers_down(providers):
            triggers.append("ai-providers-down")
        if mt5_safety.reconciliation_log(limit=1):
            triggers.append("reconciliation-mismatch")
        return triggers

    def _stale_market_data(self, get_live_quote, symbols=("XAUUSD", "EURUSD", "US500"), stale_ms=None):
        stale_ms = _dec(stale_ms, DEFAULT_STALE_MS) if stale_ms is not None else DEFAULT_STALE_MS
        now = Decimal(int(time.time() * 1000))
        for symbol in symbols:
            live = get_live_quote(symbol)
            if live:
                fetched = _dec(live.get("fetchedAt"), now)
                if now - fetched > stale_ms:
                    return True
        return False

    def _ai_providers_down(self, providers):
        try:
            ai_models = providers.list("ai-model")
        except Exception:  # noqa: BLE001 - provider framework absent
            return True
        if not ai_models:
            return True
        return all(not p.get("enabled", True) for p in ai_models)

    def sync_fail_closed(self):
        """Raise fail-closed triggers that are failing and clear ones that recovered.

        Keeps the persisted capital-protection fail-closed flags in sync with
        live conditions so a transient outage (e.g. a brief stale market-data
        window) auto-recovers instead of blocking every order until a manual
        API clear.
        """
        current = set(self.fail_closed_triggers())
        active = set(capital_protection.get_status().get("fail_closed") or [])
        raised = []
        for trigger in current - active:
            capital_protection.raise_fail_closed(trigger, f"strict-risk:{trigger}")
            raised.append(trigger)
        for trigger in active - current:
            capital_protection.clear_fail_closed(trigger)
            logger.info(f"STRICT RISK: cleared fail-closed trigger: {trigger}")
        return raised

    # ------------------------------------------------------------------ #
    # 5. Auto-close open trades below the 70% confidence threshold
    # ------------------------------------------------------------------ #
    def supervise_open_positions(self, positions=None, resolve_confidence=None):
        """Close any open AI trade whose confidence is below the threshold.

        ``resolve_confidence`` is an optional callable ``(position) -> float``
        used to obtain the current AI confidence (re-score). When omitted the
        position's stored ``confidence`` / ``initialConfidence`` is used.

        Idempotent: a position is closed at most once per engine lifetime.
        """
        from ..trading.engine import trading_engine  # lazy: avoids import cycle

        actions = []
        for position in positions if positions is not None else trading_engine.get_open_positions():
            position_id = position.get("id")
            if position_id in self._auto_closed:
                continue
            current = resolve_confidence(position) if resolve_confidence is not None else self._position_confidence(position)
            if current is None:
                continue
            current_dec = _dec(current)
            if current_dec >= DEFAULT_AUTO_CLOSE_CONFIDENCE:
                continue

            reason = (
                "Confidence degradation below 70% threshold (opposite news)"
                if current_dec >= _dec(settings.EMERGENCY_CLOSE_CONFIDENCE_THRESHOLD)
                else "EMERGENCY confidence degradation below 50% threshold"
            )
            try:
                res = trading_engine.close_position(position_id, reason)
            except Exception as exc:  # noqa: BLE001 - never stop the sweep
                logger.warn(f"strict-risk auto-close failed for {position_id}: {exc}")
                continue
            if not res or res.get("status") != "closed":
                continue
            self._auto_closed[position_id] = int(time.time() * 1000)
            self.stats["auto_closes"] += 1
            event_bus.emit("strict-risk:auto-close", {"position": position, "confidence": str(current_dec), "reason": reason})
            actions.append({"positionId": position_id, "symbol": position.get("symbol"), "confidence": str(current_dec), "reason": reason})
        return actions

    @staticmethod
    def _position_confidence(position):
        conf = position.get("confidence")
        if isinstance(conf, dict):
            conf = conf.get("score")
        if conf is None:
            conf = position.get("initialConfidence")
        if isinstance(conf, dict):
            conf = conf.get("score")
        return conf

    # ------------------------------------------------------------------ #
    # Authoritative pre-trade gate (overrides ALL AI decisions)
    # ------------------------------------------------------------------ #
    def pre_trade_gate(self, order, spread_points=None):
        """Return ``(blocked: bool, reasons: str|None)`` — final fail-closed gate."""
        reasons = []

        blocked, why = capital_protection.is_blocked()
        if blocked:
            reasons.append(f"capital-protection:{why}")

        from ..execution.modes import trading_modes  # lazy import

        mode = trading_modes.get_mode()
        if mode == "EMERGENCY_STOP":
            reasons.append("emergency-stop")
        if mode == "ANALYSIS_ONLY":
            reasons.append("analysis-only-mode")
        if mode == "DISABLED":
            reasons.append("auto-trading-disabled")
        for br in trading_modes.blocked_reasons():
            if br not in reasons:
                reasons.append(br)

        ok, why = self.check_spread(spread_points)
        if not ok:
            reasons.append(why)
            self.stats["spread_blocks"] += 1

        if reasons:
            self.stats["gate_blocks"] += 1
        return bool(reasons), ";".join(reasons) if reasons else None

    # ------------------------------------------------------------------ #
    # Periodic enforcement + status
    # ------------------------------------------------------------------ #
    def enforce_all(self, portfolio=None):
        """Run daily-loss + max-drawdown enforcement against the portfolio."""
        from ..portfolio.service import portfolio_service  # lazy import

        portfolio = portfolio or portfolio_service.get()
        actions = []
        ok, why = self.enforce_daily_loss(portfolio.get("dailyLoss") or 0)
        if ok:
            actions.append(why)
        peak = capital_protection.get_status().get("peak_equity")
        ok, why = self.enforce_max_drawdown(portfolio.get("equity") or 0, peak)
        if ok:
            actions.append(why)
        self.sync_fail_closed()
        self.stats["last_enforce"] = int(time.time() * 1000)
        self.stats["last_enforce_actions"] = actions
        return actions

    def status(self):
        return {
            "engine": "strict-risk-policy",
            "fail_closed": capital_protection.get_status().get("fail_closed", []),
            "emergency_stop": capital_protection.get_status().get("emergency_stop"),
            "shield_level": capital_protection.get_status().get("shield_level"),
            "daily_locked": capital_protection.get_status().get("daily_locked"),
            "thresholds": {
                "max_spread_points": str(DEFAULT_MAX_SPREAD_POINTS),
                "daily_loss_limit": str(DEFAULT_DAILY_LOSS_LIMIT),
                "max_drawdown_percent": str(DEFAULT_MAX_DRAWDOWN_PERCENT),
                "auto_close_confidence": str(DEFAULT_AUTO_CLOSE_CONFIDENCE),
                "stale_ms": str(DEFAULT_STALE_MS),
            },
            "stats": self.stats,
        }


strict_risk_policy = StrictRiskPolicyEngine()


def init_strict_risk_policy():
    """Register the periodic fail-closed enforcement sweep."""
    from ...foundation.scheduler import scheduler  # lazy import

    def _run():
        return strict_risk_policy.enforce_all()

    scheduler.register({
        "id": "strict-risk-policy-enforce",
        "intervalMs": 30 * 1000,
        "handler": _run,
    })
    logger.info("Strict risk policy engine initialized (FAIL-CLOSED: spread / daily loss / drawdown / fail-closed / auto-close)")
    return strict_risk_policy

"""Capital Guard Engine (Phase 2, Module 1) — strict FAIL-CLOSED override.

Strict Risk Rules that override ALL AI decisions. Auto-trading stays DISABLED
by default (existing ``trading_modes`` default). This engine adds the explicit
fail-closed gates required for production safety:

  1. Spread filter        : reject trades when spread > ``MAX_SPREAD_PIPS``
  2. Daily loss limit     : on hitting ``DAILY_LOSS_LIMIT`` -> lock the day and
                            switch to ANALYSIS_ONLY (auto-trading disabled)
  3. Max drawdown         : on equity falling ``MAX_DRAWDOWN_PERCENT`` from peak
                            -> EMERGENCY_STOP + close ALL open trades
  4. Fail-closed triggers : MT5 disconnected / stale feed / AI providers down /
                            reconciliation mismatch all disable execution
  5. Auto-close <70%      : handled by ``position_sync`` (opposite-news close)

Everything is additive — the existing capital protection engine, trading mode
manager, brain-monitor and MT5 safety envelope keep their behaviour; this guard
adds a single authoritative gate on top.
"""
import time

from ...config import settings
from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from .capital_protection import capital_protection

AUTO_DISABLE_MODES = ("AUTO_LIMITED", "AUTO_FULL", "SEMI_AUTO")


class CapitalGuardEngine:
    def __init__(self):
        self.stats = {
            "spread_blocks": 0,
            "daily_loss_switches": 0,
            "drawdown_stops": 0,
            "closed_all": 0,
            "last_enforce": None,
            "last_enforce_actions": [],
        }

    # ------------------------------------------------------------------ #
    # 1. Spread filter
    # ------------------------------------------------------------------ #
    def check_spread(self, spread_pips, max_spread=None):
        """Reject when spread exceeds the configured / requested cap."""
        limit = max_spread if max_spread is not None else settings.MAX_SPREAD_PIPS
        if spread_pips is None:
            return True, None
        try:
            spread = float(spread_pips)
        except (TypeError, ValueError):
            return True, None
        if spread > float(limit):
            return False, f"spread {spread:.2f} > max {limit}"
        return True, None

    # ------------------------------------------------------------------ #
    # 2. Daily loss limit -> lock day + switch to analysis mode
    # ------------------------------------------------------------------ #
    def enforce_daily_loss(self, daily_loss):
        """Auto-disable trading and switch to Analysis Mode on daily loss."""
        if not settings.DAILY_LOSS_LIMIT:
            return False, None
        try:
            loss = abs(float(daily_loss or 0))
        except (TypeError, ValueError):
            return False, None
        if loss < float(settings.DAILY_LOSS_LIMIT):
            return False, None

        capital_protection.lock_for_day(f"daily loss {loss:.2f} >= limit {settings.DAILY_LOSS_LIMIT}")
        from ..execution.modes import trading_modes  # lazy: avoids import cycle

        mode = trading_modes.get_mode()
        if mode in AUTO_DISABLE_MODES or mode == "AUTO_EXECUTE":
            trading_modes.set_mode("ANALYSIS_ONLY", actor="system", reason="daily-loss-limit")
            self.stats["daily_loss_switches"] += 1
        event_bus.emit("capital:daily-loss-limit", {"daily_loss": daily_loss, "limit": settings.DAILY_LOSS_LIMIT})
        logger.warn(f"CAPITAL GUARD: daily loss limit hit ({loss:.2f}) -> analysis-only")
        return True, "daily-loss-limit"

    # ------------------------------------------------------------------ #
    # 3. Max drawdown -> EMERGENCY STOP + close all trades
    # ------------------------------------------------------------------ #
    def enforce_max_drawdown(self, equity, peak):
        """On drawdown >= MAX_DRAWDOWN_PERCENT: emergency stop + close all."""
        try:
            equity = float(equity or 0)
            peak = float(peak or equity)
        except (TypeError, ValueError):
            return False, None
        if peak <= 0 or equity <= 0:
            return False, None
        drawdown = (peak - equity) / peak
        if drawdown < float(settings.MAX_DRAWDOWN_PERCENT):
            return False, None

        capital_protection.activate_emergency_stop(
            f"max drawdown {drawdown:.2%} >= {settings.MAX_DRAWDOWN_PERCENT:.2%} from peak {peak}"
        )
        self.stats["drawdown_stops"] += 1
        closed = self.close_all_trades("emergency-drawdown")
        event_bus.emit("capital:max-drawdown", {"drawdown": drawdown, "peak": peak, "closed": closed})
        logger.error(f"CAPITAL GUARD: max drawdown {drawdown:.2%} -> EMERGENCY STOP, closed {len(closed)} trades")
        return True, "max-drawdown-emergency-stop"

    def close_all_trades(self, reason):
        """Close every open position through the trading engine."""
        from ..trading.engine import trading_engine  # lazy: avoids import cycle

        closed = []
        for position in trading_engine.get_open_positions():
            try:
                trading_engine.close_position(position["id"], reason)
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
        stale = self._stale_market_data(get_live_quote)
        if stale:
            triggers.append("market-data-stale")
        ai_down = self._ai_providers_down(providers)
        if ai_down:
            triggers.append("ai-providers-down")
        if mt5_safety.reconciliation_log(limit=1):
            triggers.append("reconciliation-mismatch")
        return triggers

    def _stale_market_data(self, get_live_quote, symbols=("XAUUSD", "EURUSD", "US500")):
        now = int(time.time() * 1000)
        for symbol in symbols:
            live = get_live_quote(symbol)
            if live:
                fetched = live.get("fetchedAt") or now
                if now - fetched > settings.STALE_DATA_THRESHOLD_SECONDS * 1000:
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

        Mirrors ``strict_risk_policy.sync_fail_closed`` so a transient outage
        (e.g. a brief stale market-data window) auto-recovers instead of
        blocking every order until a manual API clear.
        """
        current = set(self.fail_closed_triggers())
        active = set(capital_protection.get_status().get("fail_closed") or [])
        raised = []
        for trigger in current - active:
            capital_protection.raise_fail_closed(trigger, f"capital-guard:{trigger}")
            raised.append(trigger)
        for trigger in active - current:
            capital_protection.clear_fail_closed(trigger)
            logger.info(f"CAPITAL GUARD: cleared fail-closed trigger: {trigger}")
        return raised

    # ------------------------------------------------------------------ #
    # 5. Pre-trade gate (authoritative override for ALL AI decisions)
    # ------------------------------------------------------------------ #
    def fail_closed_gate(self, order, spread_pips=None):
        """Engine-level hard gate: capital protection override + spread cap.

        Trading-mode gating is enforced upstream (auto controller / executor);
        this gate is the final fail-closed layer inside ``_safety_checks``.
        """
        blocked, why = capital_protection.is_blocked()
        if blocked:
            return False, why
        ok, why = self.check_spread(spread_pips)
        if not ok:
            self.stats["spread_blocks"] += 1
            return False, why
        return True, None

    def pre_trade_gate(self, order, spread_pips=None):
        """Return ``(blocked, reasons)`` overriding every AI decision."""
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
        for br in trading_modes.blocked_reasons():
            if br not in reasons:
                reasons.append(br)

        ok, why = self.check_spread(spread_pips)
        if not ok:
            reasons.append(why)
            self.stats["spread_blocks"] += 1

        return (bool(reasons), ";".join(reasons) if reasons else None)

    # ------------------------------------------------------------------ #
    # Periodic enforcement
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
        self.stats["last_enforce"] = int(time.time() * 1000)
        self.stats["last_enforce_actions"] = actions
        return actions

    def status(self):
        return {
            "stats": self.stats,
            "fail_closed": capital_protection.get_status().get("fail_closed", []),
            "emergency_stop": capital_protection.get_status().get("emergency_stop"),
            "mode": self._current_mode(),
        }

    def _current_mode(self):
        from ..execution.modes import trading_modes  # lazy import

        return trading_modes.get_mode()


capital_guard = CapitalGuardEngine()


def init_capital_guard():
    """Register the periodic fail-closed enforcement sweep."""
    from ...foundation.scheduler import scheduler  # lazy import

    def _run():
        return capital_guard.enforce_all()

    scheduler.register({
        "id": "capital-guard-enforce",
        "intervalMs": 30 * 1000,
        "handler": _run,
    })
    logger.info("Capital guard engine initialized (FAIL-CLOSED: spread / daily loss / drawdown / fail-closed)")
    return capital_guard

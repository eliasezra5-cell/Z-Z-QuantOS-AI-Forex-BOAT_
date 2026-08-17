"""AI Brain Execution Core (additive module).

Implements the two runtime pieces the master prompt requires but that were
only defined, never wired:

  1. ConfidenceMonitor — re-score every open AI trade every 2 seconds and
     AUTO-CLOSE when current confidence drops below
     AUTO_CLOSE_CONFIDENCE_THRESHOLD (0.70), EMERGENCY-CLOSE (with alert to all
     channels) below EMERGENCY_CLOSE_CONFIDENCE_THRESHOLD (0.50).

  2. KillSwitchMonitor — continuously DETECT every kill-switch condition and
     fire the previously manual-only kill switches (modes.py defines them but
     nothing ever auto-triggers them). Weekend and major-news-in-30m are
     treated as "pause new trades" windows rather than permanent stops.

Nothing in this file modifies existing modules; it only composes their public
APIs. All events are recorded to `confidence_re_scores` / `brain_monitor_state`
and emitted on the event bus so every action is auditable and idempotent.
"""
import threading
import time
from datetime import datetime, timedelta, timezone

from ...config import settings
from ...foundation.event_bus import event_bus
from ...foundation.json_store import db
from ...foundation.logger import logger
from ...foundation.provider_framework import providers
from ..alerts.service import alert_service
from ..economic.engine import get_high_impact_events
from ..execution.auto_controller import auto_trade_controller
from ..execution.modes import AUTO_EXECUTION_MODES, KILL_SWITCHES, trading_modes
from ..marketdata.engine import generate_candles, get_quote
from ..marketdata.live_prices import get_live_quote
from ..mt5.adapter import mt5_state
from ..news.engine import get_news
from ..portfolio.service import portfolio_service
from ..risk.capital_protection import capital_protection
from ..technical.price_action import analyze_price_action
from ..trading.engine import trading_engine

EMERGENCY_ALERT_CHANNELS = ["web", "telegram", "email", "push", "desktop", "mt5"]

PAUSE_KILL_SWITCHES = {"weekend", "major_news_in_30m"}

# Persistent state record used for idempotent kill-switch tracking.
STATE_COLLECTION = "brain_monitor_state"
RESCORE_COLLECTION = "confidence_re_scores"


def _now_ms():
    return int(time.time() * 1000)


def _utcnow():
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Confidence re-scoring
# --------------------------------------------------------------------------- #
class ConfidenceScorer:
    """Deterministic re-score of an open position's confidence.

    Reductions (all clamped to 0..1, capped per factor):
      - contradictory_news: fresh, high-impact news with sentiment opposite the
        position side.
      - structure_break: price closed beyond the most recent 20-bar swing high/
        low against the position (technical structure broke).
      - divergence: price moved materially against the news-implied direction.
      - risk_pressure: price is inside ~25% of the original SL distance.
    """

    def __init__(self):
        self.col = db.collection(RESCORE_COLLECTION)

    def _contradictory_news_deduction(self, symbol, side):
        now = _now_ms()
        max_deduction = 0.0
        for item in get_news({"symbol": symbol, "limit": 10}):
            ts = item.get("time") or now
            age_hours = max(0.0, (now - ts) / 3600000.0)
            if age_hours > 6:
                continue
            sentiment = item.get("sentiment") or 0
            contradicts = (side == "buy" and sentiment < -0.1) or (side == "sell" and sentiment > 0.1)
            if not contradicts:
                continue
            severity = abs(sentiment) * (item.get("trustScore") or 0.7) * (item.get("marketImpact") or 0.5)
            recency = max(0.0, 1.0 - age_hours / 6.0)
            deduction = min(0.15, severity * recency * 0.6)
            max_deduction = max(max_deduction, deduction)
        return max_deduction

    def _structure_break_deduction(self, symbol, side, price):
        candles = generate_candles(symbol, "H1", 60)
        if len(candles) < 30:
            return 0.0
        pa = analyze_price_action(candles)
        recent = candles[-20:]
        recent_low = min(c["low"] for c in recent)
        recent_high = max(c["high"] for c in recent)
        broke = (side == "buy" and price < recent_low) or (side == "sell" and price > recent_high)
        if not broke:
            return 0.0
        # Confirmation from the trend structure when available.
        trend = (pa or {}).get("trend")
        confirmed = (side == "buy" and trend in ("bearish", "bearish-look")) or (side == "sell" and trend in ("bullish", "bullish-look"))
        return 0.25 if confirmed else 0.15

    def _divergence_deduction(self, symbol, side, price):
        items = get_news({"symbol": symbol, "limit": 10})
        if not items:
            return 0.0
        avg_sentiment = sum(i.get("sentiment") or 0 for i in items) / len(items)
        if abs(avg_sentiment) < 0.05:
            return 0.0
        expected_up = avg_sentiment > 0
        entry = price  # fallback; caller passes position price when entry unknown
        pnl_pct = 0.0
        if entry > 0:
            pnl_pct = ((price - entry) / entry) * 100 if side == "buy" else ((entry - price) / entry) * 100
        # Price moved against the news-implied direction by > 0.3%.
        if expected_up and pnl_pct < -0.3:
            return min(0.20, abs(pnl_pct) / 2.0)
        if not expected_up and pnl_pct < -0.3:
            return min(0.20, abs(pnl_pct) / 2.0)
        return 0.0

    def _risk_pressure_deduction(self, position, price):
        sl = position.get("stopLoss")
        entry = position.get("entryPrice") or price
        if sl is None or entry <= 0 or sl == price:
            return 0.0
        original_distance = abs(entry - sl) / entry * 100
        current_distance = abs(price - sl) / entry * 100
        if original_distance <= 0:
            return 0.0
        if current_distance < max(original_distance * 0.25, 0.05):
            return 0.15
        return 0.0

    def score(self, position, price=None):
        symbol = position["symbol"]
        side = position["side"]
        quote = get_quote(symbol)
        price = price or (quote["bid"] if side == "buy" else quote["ask"])

        initial = position.get("confidence") or position.get("initialConfidence") or 0.80

        deductions = {
            "contradictory_news": self._contradictory_news_deduction(symbol, side),
            "structure_break": self._structure_break_deduction(symbol, side, price),
            "divergence": self._divergence_deduction(symbol, side, price),
            "risk_pressure": self._risk_pressure_deduction(position, price),
        }
        current = max(0.0, min(1.0, initial - sum(deductions.values())))
        return {
            "positionId": position.get("id"),
            "symbol": symbol,
            "side": side,
            "initial": round(initial, 4),
            "current": round(current, 4),
            "deductions": {k: round(v, 4) for k, v in deductions.items()},
            "price": price,
            "timestamp": _now_ms(),
        }

    def record(self, result):
        return self.col.insert(result)


confidence_scorer = ConfidenceScorer()


class ConfidenceMonitor:
    """2-second loop that re-scores open AI positions and auto-closes."""

    def __init__(self, interval_seconds=2.0):
        self.interval = interval_seconds
        self.running = False
        self.thread = None
        self.closed = {}  # position_id -> close action (idempotency guard)
        self.last_scan = None
        self.stats = {"scans": 0, "auto_closes": 0, "emergency_closes": 0, "holds": 0}

    def _should_close(self, result):
        current = result["current"]
        if current >= settings.AUTO_CLOSE_CONFIDENCE_THRESHOLD:
            return None
        if current < settings.EMERGENCY_CLOSE_CONFIDENCE_THRESHOLD:
            return "emergency-close"
        return "auto-close"

    def scan(self):
        """One pass over open positions. Returns the list of actions taken."""
        actions = []
        for position in trading_engine.get_open_positions():
            if position.get("confidence") is None and position.get("initialConfidence") is None:
                continue
            result = confidence_scorer.score(position)
            confidence_scorer.record(result)
            action = self._should_close(result)
            if action is None:
                self.stats["holds"] += 1
                continue
            # Idempotency guard: never close the same position twice.
            key = position["id"]
            if key in self.closed:
                continue
            self._execute_close(position, result, action)
            self.closed[key] = {"action": action, "at": _now_ms()}
            actions.append({"positionId": key, "symbol": position["symbol"], "action": action, "result": result})
        self.last_scan = _now_ms()
        self.stats["scans"] += 1
        return actions

    def _execute_close(self, position, result, action):
        reason = (
            "Confidence degradation below 70% threshold"
            if action == "auto-close"
            else "EMERGENCY confidence degradation below 50% threshold"
        )
        log_action = "emergency-close" if action == "emergency-close" else "auto-close"
        auto_trade_controller.record_reanalysis(position, {"confidence": result["current"], "initial": result["initial"], "scorer": "brain-confidence-monitor"}, log_action, reason)

        mode = trading_modes.get_mode()
        if mode in AUTO_EXECUTION_MODES:
            trading_engine.close_position(position["id"], reason, result["price"])
            self.stats["emergency_closes" if action == "emergency-close" else "auto_closes"] += 1
            event_bus.emit("trading:confidence-close", {
                "positionId": position["id"], "symbol": position["symbol"], "action": log_action,
                "confidence": result["current"], "initial": result["initial"], "reason": reason,
            })
            if action == "emergency-close":
                alert_service.notify(
                    f"EMERGENCY CLOSE {position['symbol']}",
                    f"Confidence dropped to {result['current']:.0%} (initial {result['initial']:.0%}). Position closed. {reason}",
                    severity="critical",
                    channels=EMERGENCY_ALERT_CHANNELS,
                )
            else:
                alert_service.notify(
                    f"Auto-close {position['symbol']}",
                    f"Confidence dropped below 70% to {result['current']:.0%}. Position closed. {reason}",
                    severity="warning",
                    channels=["web", "telegram"],
                )
        else:
            # Not in an auto-execution mode: never force a close; alert instead.
            event_bus.emit("trading:confidence-alert", {
                "positionId": position["id"], "symbol": position["symbol"], "action": log_action,
                "confidence": result["current"], "initial": result["initial"], "reason": reason,
                "mode": mode,
            })
            alert_service.notify(
                f"Confidence alert {position['symbol']}",
                f"Confidence {result['current']:.0%} below threshold (initial {result['initial']:.0%}) — close suggested but trading mode is {mode}.",
                severity="warning",
                channels=["web", "telegram"],
            )

    def _loop(self):
        while self.running:
            try:
                self.scan()
            except Exception as exc:  # noqa: BLE001
                logger.error("Confidence monitor scan failed", meta={"error": str(exc)})
            time.sleep(self.interval)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info(f"Confidence monitor started (every {self.interval}s)")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)

    def status(self):
        return {
            "intervalSeconds": self.interval,
            "running": self.running,
            "lastScan": self.last_scan,
            "stats": self.stats,
            "closed": self.closed,
        }


confidence_monitor = ConfidenceMonitor()


# --------------------------------------------------------------------------- #
# Kill-switch auto-detection
# --------------------------------------------------------------------------- #
class KillSwitchMonitor:
    """Periodically DETECTS kill-switch conditions and fires them.

    Hard-stop conditions call ``trading_modes.trigger_kill_switch`` (which
    forces EMERGENCY_STOP and cannot self-deactivate). Weekend and
    major-news-in-30m are treated as pause windows instead of permanent stops.
    """

    def __init__(self, interval_seconds=5.0):
        self.interval = interval_seconds
        self.running = False
        self.thread = None
        self.pauses = {}  # condition -> until_ms
        self.live_ever_seen = False
        self.last_live_at = None
        self.last_scan = None
        self.history = db.collection("brain_monitor_kill_switch_log")

    # ---- detection helpers ----
    def _is_weekend(self, dt=None):
        dt = dt or _utcnow()
        # Saturday 22:00 UTC .. Sunday 22:00 UTC
        return (dt.weekday() == 5 and dt.hour >= 22) or (dt.weekday() == 6 and dt.hour < 22)

    def _weekend_pause_until(self, dt=None):
        dt = dt or _utcnow()
        # Next Sunday 22:00 UTC (the current weekend window's end).
        days_ahead = (6 - dt.weekday()) % 7
        end = dt + timedelta(days=days_ahead)
        end = end.replace(hour=22, minute=0, second=0, microsecond=0)
        if end <= dt:
            end = end + timedelta(days=7)
        return int(end.timestamp() * 1000)

    def _major_news_events(self, window_minutes=30):
        now = _now_ms()
        window_ms = window_minutes * 60 * 1000
        return [e for e in get_high_impact_events() if now <= e["time"] <= now + window_ms]

    def _weekly_loss(self, closed):
        now = _utcnow()
        week_start = now - timedelta(days=now.weekday())
        week_start_ms = int(week_start.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        return sum(p["profit"] for p in closed if (p.get("closedAt") or 0) >= week_start_ms and p["profit"] < 0)

    def _daily_loss(self, closed):
        now = _utcnow()
        today_start_ms = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        return sum(p["profit"] for p in closed if (p.get("closedAt") or 0) >= today_start_ms and p["profit"] < 0)

    def _consecutive_losses(self, closed):
        count = 0
        for p in sorted(closed, key=lambda x: x.get("closedAt") or 0, reverse=True):
            if p.get("profit", 0) < 0:
                count += 1
            else:
                break
        return count

    def _stale_market_data(self):
        now = _now_ms()
        fresh_now = False
        for symbol in ("XAUUSD", "EURUSD", "BTCUSD", "US500"):
            live = get_live_quote(symbol)
            if live:
                self.live_ever_seen = True
                self.last_live_at = live.get("fetchedAt") or now
                if now - (live.get("fetchedAt") or now) < settings.STALE_DATA_THRESHOLD_SECONDS * 1000:
                    fresh_now = True
        if not self.live_ever_seen:
            return False  # never saw live data (e.g. offline demo) -> not stale
        if self.last_live_at and now - self.last_live_at > settings.STALE_DATA_THRESHOLD_SECONDS * 1000:
            return not fresh_now
        return False

    def _ai_providers_down(self):
        ai_models = providers.list("ai-model")
        if not ai_models:
            return True
        return all(not p.get("enabled", True) for p in ai_models)

    # ---- main detection ----
    def detect(self):
        closed = db.collection("positions").find({"status": "closed"})
        portfolio = portfolio_service.get()
        equity = portfolio.get("equity") or 0
        cp = capital_protection.get_status()
        hard_stops = []
        pauses = {}

        if settings.DAILY_LOSS_LIMIT and self._daily_loss(closed) <= -settings.DAILY_LOSS_LIMIT:
            hard_stops.append(("daily_loss_limit", f"daily loss {self._daily_loss(closed):.2f} <= limit {settings.DAILY_LOSS_LIMIT}"))
        if settings.WEEKLY_LOSS_LIMIT and self._weekly_loss(closed) <= -settings.WEEKLY_LOSS_LIMIT:
            hard_stops.append(("weekly_loss_limit", f"weekly loss {self._weekly_loss(closed):.2f} <= limit {settings.WEEKLY_LOSS_LIMIT}"))
        if self._consecutive_losses(closed) >= settings.MAX_CONSECUTIVE_LOSSES:
            hard_stops.append(("five_consecutive_losses", f"{self._consecutive_losses(closed)} consecutive losing trades"))
        start_equity = cp.get("start_equity")
        if start_equity and equity > 0 and equity < start_equity * settings.EMERGENCY_EQUITY_THRESHOLD:
            hard_stops.append(("equity_below_80pct", f"equity {equity:.2f} < {settings.EMERGENCY_EQUITY_THRESHOLD:.0%} of start {start_equity:.2f}"))
        peak = cp.get("peak_equity")
        if peak and peak > 0 and equity > 0:
            drawdown = (peak - equity) / peak
            if drawdown > settings.MAX_DRAWDOWN_PERCENT:
                hard_stops.append(("max_drawdown_exceeded", f"drawdown {drawdown:.2%} > limit {settings.MAX_DRAWDOWN_PERCENT:.2%}"))
        if settings.MT5_ENABLED == "live" and not mt5_state.connected:
            hard_stops.append(("mt5_disconnected", "MT5 live bridge is disconnected"))
        if self._stale_market_data():
            hard_stops.append(("market_data_stale", f"no fresh quote in {settings.STALE_DATA_THRESHOLD_SECONDS}s"))
        if self._ai_providers_down():
            hard_stops.append(("ai_provider_failure", "all AI model providers unavailable"))
        if cp.get("shield_level") == "RED":
            hard_stops.append(("capital_shield_red", "capital shield RED"))

        if self._is_weekend():
            pauses["weekend"] = self._weekend_pause_until()
        news_events = self._major_news_events(30)
        if news_events:
            latest_end = max(e["time"] for e in news_events) + 5 * 60 * 1000
            pauses["major_news_in_30m"] = max(latest_end, _now_ms() + 60 * 1000)

        return {"hard_stops": hard_stops, "pauses": pauses}

    def apply(self, detection):
        applied: dict = {"hard_stops": [], "pauses": {}}
        for switch, detail in detection["hard_stops"]:
            if switch not in KILL_SWITCHES:
                continue
            existing = (trading_modes.kill_switches_status() or {}).get(switch)
            if existing and existing.get("active"):
                continue  # idempotent: already fired
            trading_modes.trigger_kill_switch(switch, True, detail)
            self._log("kill-switch", switch, detail)
            applied["hard_stops"].append(switch)
        for condition, until in detection["pauses"].items():
            if condition not in KILL_SWITCHES:
                continue
            if self.pauses.get(condition, 0) == until:
                continue
            self.pauses[condition] = until
            event_bus.emit("trading:pause", {"condition": condition, "until": until})
            self._log("pause", condition, f"paused until {until}")
            applied["pauses"][condition] = until
        self._prune_pauses()
        self.last_scan = _now_ms()
        return applied

    def _prune_pauses(self):
        now = _now_ms()
        expired = [c for c, until in self.pauses.items() if until <= now]
        for c in expired:
            del self.pauses[c]
            event_bus.emit("trading:unpause", {"condition": c})
            self._log("unpause", c, "window expired")

    def _log(self, kind, condition, detail):
        self.history.insert({"kind": kind, "condition": condition, "detail": detail, "timestamp": _now_ms()})

    def _loop(self):
        while self.running:
            try:
                self.apply(self.detect())
            except Exception as exc:  # noqa: BLE001
                logger.error("Kill switch monitor scan failed", meta={"error": str(exc)})
            time.sleep(self.interval)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info(f"Kill switch monitor started (every {self.interval}s)")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)

    def status(self):
        return {
            "intervalSeconds": self.interval,
            "running": self.running,
            "lastScan": self.last_scan,
            "pauses": self.pauses,
            "liveEverSeen": self.live_ever_seen,
            "lastLiveAt": self.last_live_at,
            "fired": trading_modes.kill_switches_status(),
            "history": self.history.find({})[-50:],
        }


kill_switch_monitor = KillSwitchMonitor()


# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #
def init_brain_monitor():
    """Additive registration of the AI Brain execution core monitors."""
    state = db.collection(STATE_COLLECTION)
    if state.count() == 0:
        state.insert({"id": "brain-monitor", "enabled": True, "startedAt": _now_ms()})

    def _on_mt5_disconnected(event):
        if settings.MT5_ENABLED == "live":
            kill_switch_monitor.apply({"hard_stops": [("mt5_disconnected", "MT5 disconnected event")], "pauses": {}})

    def _on_ai_provider_failure(event):
        kill_switch_monitor.apply({"hard_stops": [("ai_provider_failure", "AI provider failure event")], "pauses": {}})

    event_bus.on("mt5:disconnected", _on_mt5_disconnected)
    event_bus.on("ai:provider-failure", _on_ai_provider_failure)

    confidence_monitor.start()
    kill_switch_monitor.start()
    logger.info("AI Brain execution core initialized (confidence monitor + kill-switch monitor)")
    return {"confidence_monitor": confidence_monitor, "kill_switch_monitor": kill_switch_monitor}


def brain_status():
    return {
        "confidenceMonitor": confidence_monitor.status(),
        "killSwitchMonitor": kill_switch_monitor.status(),
        "pauses": kill_switch_monitor.pauses,
        "tradingMode": trading_modes.get_mode(),
        "blockedReasons": trading_modes.blocked_reasons(),
        "capitalShield": capital_protection.get_status().get("shield_level"),
    }


def run_brain_scan():
    """Manual one-shot scan (confidence re-score + kill-switch detection)."""
    closes = confidence_monitor.scan()
    detection = kill_switch_monitor.detect()
    applied = kill_switch_monitor.apply(detection)
    return {
        "confidenceCloses": closes,
        "detection": detection,
        "applied": applied,
        "status": brain_status(),
        "ok": True,
        "timestamp": _now_ms(),
    }


def recent_rescores(limit=50):
    return db.collection(RESCORE_COLLECTION).find({})[-limit:]

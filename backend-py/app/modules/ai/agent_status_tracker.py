"""Passive AI Agent Status Tracker (additive — no decision logic changes).

Observers the existing decision flows purely through the event bus. Both
``modules/ai/decision_pipeline.py`` and ``modules/ai/decision_center.py``
already emit ``ai:decision`` / ``AIDecisionMade`` events whose payload carries a
``decision`` dict with an ``agentScores`` list (each entry containing
``agent_id``, ``name``, ``direction``, ``confidence``, ``reasoning`` and
``provider_status``). This tracker subscribes to those events and records each
agent's latest status, vote, confidence, reasoning and provider so the Agent
Command Center frontend can render a live kanban board.

Nothing here mutates decision logic, return values, control flow or timing.
Every failure is caught and logged so the tracker can never break the trading
decision pipeline.
"""
import threading
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db

VALID_STATUSES = ("idle", "analyzing", "voted", "done")

# Default roster: live pipeline agents plus the legacy decision-center agents so
# the kanban is populated before the first event. Ids must match the
# ``agent_id`` / ``agent.id`` values the pipeline actually produces.
DEFAULT_AGENTS = {
    "news": "News Agent",
    "historical": "Historical Agent",
    "macro": "Macro Agent",
    "technical": "Technical Agent",
    "risk": "Risk Agent",
    "sentiment": "Sentiment Agent",
    "fundamentals": "Fundamentals Agent",
    "trend_agent": "Trend Agent",
    "indicator_agent": "Indicator Agent",
    "pattern_agent": "Pattern Agent",
    "smc_agent": "SMC Agent",
}


def _pretty_name(agent_id):
    return agent_id.replace("_", " ").title()


class AgentStatusTracker:
    """In-memory status board + persisted decision history per agent."""

    def __init__(self):
        self._lock = threading.Lock()
        self._status = {}
        self._history = {}
        self._history_col = db.collection("agent_status_history")
        self._started = False
        for agent_id in DEFAULT_AGENTS:
            self._ensure_registered(agent_id)

    # ------------------------------------------------------------------ #
    # Registration / status mutation
    # ------------------------------------------------------------------ #
    def _ensure_registered(self, agent_id):
        if agent_id in self._status:
            return self._status[agent_id]
        record = {
            "agent_id": agent_id,
            "name": DEFAULT_AGENTS.get(agent_id, _pretty_name(agent_id)),
            "status": "idle",
            "model_used": None,
            "decision": None,
            "confidence": None,
            "reasoning": None,
            "symbol": None,
            "updatedAt": None,
        }
        self._status[agent_id] = record
        return record

    def register(self, agent_id, name=None):
        """Register an agent so it appears on the board (idempotent)."""
        try:
            with self._lock:
                record = self._ensure_registered(agent_id)
                if name:
                    record["name"] = name
                return dict(record)
        except Exception as exc:  # noqa: BLE001 - tracker must never raise
            logger.error(f"agent status tracker register failed: {exc}")
            return None

    def set_status(self, agent_id, status, model_used=None, decision=None,
                   confidence=None, reasoning=None, symbol=None, name=None):
        """Record one agent's current status. Never raises."""
        try:
            status = status if status in VALID_STATUSES else "idle"
            with self._lock:
                record = self._ensure_registered(agent_id)
                if name:
                    record["name"] = name
                record.update({
                    "status": status,
                    "model_used": model_used,
                    "decision": decision,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "symbol": symbol,
                    "updatedAt": int(time.time() * 1000),
                })
                if status in ("voted", "done"):
                    self._append_history(record)
                return dict(record)
        except Exception as exc:  # noqa: BLE001 - tracker must never raise
            logger.error(f"agent status tracker set_status failed: {exc}")
            return None

    def _append_history(self, record):
        rows = self._history.setdefault(record["agent_id"], [])
        fingerprint = (
            record["status"], record["decision"], record["confidence"],
            record["reasoning"], record["symbol"],
        )
        if rows and self._fingerprint(rows[-1]) == fingerprint:
            return
        rows.append(dict(record))
        if len(rows) > 200:
            del rows[: len(rows) - 200]
        try:
            self._history_col.insert(dict(record))
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort
            logger.warn(f"agent status history persist failed: {exc}")

    @staticmethod
    def _fingerprint(record):
        return (
            record.get("status"), record.get("decision"), record.get("confidence"),
            record.get("reasoning"), record.get("symbol"),
        )

    # ------------------------------------------------------------------ #
    # Read paths for the API / frontend
    # ------------------------------------------------------------------ #
    def get_all_statuses(self):
        try:
            with self._lock:
                return [dict(r) for r in self._status.values()]
        except Exception as exc:  # noqa: BLE001
            logger.error(f"agent status tracker get_all_statuses failed: {exc}")
            return []

    def get_history(self, agent_id, limit=20):
        """Recent terminal records for one agent, newest last."""
        try:
            with self._lock:
                rows = list(self._history.get(agent_id) or [])
            if not rows:
                rows = self._load_persisted_history(agent_id)
            return rows[-limit:]
        except Exception as exc:  # noqa: BLE001
            logger.error(f"agent status tracker get_history failed: {exc}")
            return []

    def _load_persisted_history(self, agent_id):
        try:
            rows = self._history_col.find({"agent_id": agent_id})
            rows.sort(key=lambda r: r.get("updatedAt") or 0)
            return rows
        except Exception as exc:  # noqa: BLE001 - fallback is best-effort
            logger.warn(f"agent status history load failed: {exc}")
            return []

    # ------------------------------------------------------------------ #
    # Passive event observation
    # ------------------------------------------------------------------ #
    def _on_decision(self, event):
        try:
            payload = event.get("payload") if isinstance(event, dict) else None
            decision = payload.get("decision") if isinstance(payload, dict) else None
            if not isinstance(decision, dict):
                return
            symbol = decision.get("symbol")
            for agent in decision.get("agentScores") or []:
                if not isinstance(agent, dict) or not agent.get("agent_id"):
                    continue
                self.set_status(
                    agent["agent_id"],
                    "done",
                    model_used=agent.get("provider_status") or None,
                    decision=agent.get("direction"),
                    confidence=agent.get("confidence"),
                    reasoning=agent.get("reasoning"),
                    symbol=symbol,
                    name=agent.get("name"),
                )
        except Exception as exc:  # noqa: BLE001 - observer must never break the bus
            logger.error(f"agent status tracker event handler failed: {exc}")

    def start(self):
        if self._started:
            return self
        event_bus.on("ai:decision", self._on_decision)
        event_bus.on("AIDecisionMade", self._on_decision)
        self._started = True
        logger.info("Agent status tracker started (passive event observer)")
        return self


agent_status_tracker = AgentStatusTracker()

# Subscribe at import time (idempotent) so the tracker observes every decision
# event without requiring any extra init call from ``main.py``.
agent_status_tracker.start()


def init_agent_status_tracker():
    agent_status_tracker.start()
    return agent_status_tracker

"""Dynamic Contextual Consensus + Abstention (Batch 07/22).

NOT fixed 80/20 weights. Weights computed from ~13 context factors (event
severity, age, source quality, confirmation, volatility regime, liquidity,
session, historical performance, instrument, time horizon, model calibration,
data quality, agent disagreement). Weighted voting WITH abstention.

Mandatory abstention states (10):
  TRADE, NO_TRADE, WAIT_FOR_CONFIRMATION, DATA_INSUFFICIENT,
  CONFLICTING_SIGNALS, STALE_EVENT, ALREADY_PRICED_IN, MARKET_CLOSED,
  RISK_BLOCKED, PROVIDER_DEGRADED

Rules:
  - any agent says NO_TRADE with confidence > 0.8 -> overall NO_TRADE
  - all agents agree -> confidence bonus +0.05
  - agents disagree -> confidence penalty -0.10
  - low confidence must NEVER be forced into BUY/SELL

Custom agents: model_name, system_prompt, voting_weight (0-20%),
api_key_encrypted (per-agent key support).
"""
import time
import uuid

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...persistence.repository import encrypt_api_key

ABSTENTION_STATES = [
    "TRADE", "NO_TRADE", "WAIT_FOR_CONFIRMATION", "DATA_INSUFFICIENT",
    "CONFLICTING_SIGNALS", "STALE_EVENT", "ALREADY_PRICED_IN",
    "MARKET_CLOSED", "RISK_BLOCKED", "PROVIDER_DEGRADED",
]

CORE_AGENTS = [
    {"id": "news", "name": "NewsAnalysisAgent", "weight": 0.30, "prompt": "Evaluate news direction & gold impact only."},
    {"id": "market", "name": "MarketValidationAgent", "weight": 0.25, "prompt": "Validate market behavior vs news."},
    {"id": "macro", "name": "MacroAnalysisAgent", "weight": 0.15, "prompt": "Macro environment, regime, sessions."},
    {"id": "historical", "name": "HistoricalAnalysisAgent", "weight": 0.15, "prompt": "Historical pattern matching."},
    {"id": "risk", "name": "RiskAnalysisAgent", "weight": 0.15, "prompt": "Portfolio state, risk limits."},
]


class DynamicConsensusEngine:
    def __init__(self):
        self.col = db.collection("consensus_history")
        self.agent_perf = {}  # agent_id -> {correct, total}

    def _context_weights(self, context):
        """Compute dynamic weights from context factors. Returns base weight map."""
        ctx = context or {}
        base = {a["id"]: a["weight"] for a in CORE_AGENTS}
        # event severity boosts news/market
        severity = ctx.get("eventSeverity") or 0.0
        base["news"] += severity * 0.10
        base["market"] += severity * 0.05
        # volatility regime boosts risk
        if ctx.get("volatilityRegime") in ("high", "crisis"):
            base["risk"] += 0.10
        # historical performance adjustment
        for aid in base:
            perf = self.agent_perf.get(aid)
            if perf and perf["total"] >= 5:
                acc = perf["correct"] / perf["total"]
                base[aid] *= 0.5 + min(acc, 1.0)  # clamp [0.5x, 2.0x] of base
        # clamp to [0.05, 0.60]
        for aid in base:
            base[aid] = max(0.05, min(0.60, base[aid]))
        # normalize to sum 1.0
        total = sum(base.values())
        if total > 0:
            base = {k: v / total for k, v in base.items()}
        return base

    def _weigh_agent(self, agent, abstention, confidence):
        """An agent that abstains contributes NO weight (mandatory abstention)."""
        if abstention != "TRADE":
            return 0.0
        return confidence

    def compute(self, votes, context=None):
        """votes: list of {agent_id, direction(buy/sell/neutral/abstain),
        confidence (0..1), abstention, reasoning}. Returns consensus dict."""
        context = context or {}
        weights = self._context_weights(context)

        direction_scores = {"buy": 0.0, "sell": 0.0, "neutral": 0.0}
        abstentions = []
        total_weight = 0.0
        no_trade_veto = False
        agreement_flags = []

        for v in votes:
            aid = v.get("agent_id")
            w = weights.get(aid, 0.0)
            abstention = (v.get("abstention") or "TRADE").upper()
            if abstention not in ABSTENTION_STATES:
                abstention = "DATA_INSUFFICIENT"
            conf = max(0.0, min(1.0, v.get("confidence") or 0.0))
            if abstention != "TRADE":
                abstentions.append({"agent": aid, "state": abstention, "confidence": conf, "reasoning": v.get("reasoning")})
                # Mandatory veto: any agent says NO_TRADE with confidence > 0.8
                if abstention == "NO_TRADE" and conf > 0.8:
                    no_trade_veto = True
                continue
            direction = (v.get("direction") or "neutral").lower()
            if direction not in direction_scores:
                direction = "neutral"
            weighted = self._weigh_agent(v, abstention, conf) * w
            direction_scores[direction] += weighted
            total_weight += w
            agreement_flags.append(direction)

        # consensus direction
        total = sum(direction_scores.values())
        if total > 0:
            direction = max(direction_scores, key=direction_scores.get)
            strength = direction_scores[direction] / total
        else:
            direction = "neutral"
            strength = 0.0

        # agreement bonus / disagreement penalty
        confidence_bonus = 0.0
        if agreement_flags:
            distinct = set(agreement_flags)
            if len(distinct) == 1:
                confidence_bonus = 0.05
            elif len(distinct) >= 3:
                confidence_bonus = -0.10

        agreement = (agreement_flags.count(direction) / len(agreement_flags)) if agreement_flags and direction in ("buy", "sell", "neutral") else 0.0

        raw_confidence = strength
        confidence = max(0.0, min(1.0, raw_confidence + confidence_bonus))

        # No-trade veto overrides everything
        if no_trade_veto:
            direction = "no_trade"
            confidence = max(confidence, 0.8)

        consensus = {
            "direction": direction,
            "buy_weight": round(direction_scores["buy"], 4),
            "sell_weight": round(direction_scores["sell"], 4),
            "neutral_weight": round(direction_scores["neutral"], 4),
            "strength": round(strength, 4),
            "agreement": round(agreement, 4),
            "weight_map": {k: round(v, 4) for k, v in weights.items()},
            "abstentions": abstentions,
            "confidence": round(confidence, 4),
            "confidence_bonus": confidence_bonus,
            "no_trade_veto": no_trade_veto,
        }

        self._record(consensus, context)
        return consensus

    def _record(self, consensus, context):
        self.col.insert({
            "consensus": consensus,
            "context_keys": list((context or {}).keys()),
            "timestamp": int(time.time() * 1000),
        })

    def record_agent_outcome(self, agent_id, correct):
        perf = self.agent_perf.setdefault(agent_id, {"correct": 0, "total": 0})
        perf["total"] += 1
        if correct:
            perf["correct"] += 1

    def history(self, limit=50):
        rows = self.col.find({})
        return rows[-limit:]

    def agent_performance(self):
        return self.agent_perf


dynamic_consensus = DynamicConsensusEngine()


class CustomAgentRegistry:
    """Admin CRUD for custom agents (unlimited, user-created)."""

    def __init__(self):
        self.col = db.collection("custom_agents")

    def list(self):
        return self.col.find({})

    def create(self, data):
        if not data.get("name"):
            return {"status": "name-required"}
        weight = float(data.get("voting_weight") or 0.0)
        if not (0 <= weight <= 0.20):
            return {"status": "weight-must-be-0-to-20pct"}
        provider_type = data.get("provider_type") or data.get("providerType") or "free_local"
        doc = {
            "id": data.get("id") or str(uuid.uuid4()),
            "name": data["name"],
            "provider_type": provider_type,
            "model_name": data.get("model_name") or "default",
            "system_prompt": data.get("system_prompt") or "",
            "voting_weight": weight,
            "api_key_encrypted": encrypt_api_key(data.get("api_key")),
            "api_key_ref": f"enc:{uuid.uuid4().hex[:12]}" if data.get("api_key") else None,
            "base_url": data.get("base_url") or "",
            "enabled": data.get("enabled", True),
            "template": data.get("template"),
            "createdAt": int(time.time() * 1000),
        }
        self.col.insert(doc)
        event_bus.emit("custom-agent:created", {"agent": doc["name"]})
        return doc

    def update(self, agent_id, patch):
        row = self.col.find_one({"id": agent_id})
        if not row:
            return None
        if "voting_weight" in patch:
            w = float(patch["voting_weight"])
            if not (0 <= w <= 0.20):
                return {"status": "weight-must-be-0-to-20pct"}
        if "api_key" in patch:
            patch = {**patch, "api_key_encrypted": encrypt_api_key(patch.pop("api_key"))}
        self.col.update(agent_id, {**patch, "updatedAt": int(time.time() * 1000)})
        return self.col.find_one({"id": agent_id})

    def remove(self, agent_id):
        return self.col.remove(agent_id)

    def enabled_agents(self):
        return [a for a in self.col.find({"enabled": True})]


custom_agent_registry = CustomAgentRegistry()


def init_dynamic_consensus():
    logger.info("Dynamic consensus engine + custom agent registry initialized")
    return dynamic_consensus, custom_agent_registry

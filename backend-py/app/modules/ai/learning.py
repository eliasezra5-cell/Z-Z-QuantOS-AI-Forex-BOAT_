"""AI learning engine mirroring the Node ai/learning.js.

Full learning engine: outcome logging + weight updates, experience replay
buffer, pattern learning, mistake analysis, champion/challenger comparison
and per-strategy performance attribution.
"""
import time

from ...foundation.logger import logger
from ...foundation.json_store import db
from .memory import ai_memory

REPLAY_BUFFER_CAP = 1000
TRADE_COST_PCT = 0.01
CHALLENGER_MIN_SAMPLES = 5
CHALLENGER_MARGIN_PP = 5.0

MISTAKE_SUGGESTIONS = {
    "Insufficient signal confidence": "Raise consensus agreement thresholds before acting on low-confidence signals",
    "validation": "Tighten pre-trade validation rules and re-check certification before entry",
    "unknown": "Tag rejected outcomes with an explicit reason in the decision payload",
    "rejected": "Review rejection source in the order pipeline and add the specific violation to the decision metadata",
}


class LearningEngine:
    def __init__(self):
        self.col = db.collection("learning_log")
        self.model = db.collection("ai_model_state")
        self.replay_col = db.collection("replay_buffer")
        self.challenger_col = db.collection("challenger_state")
        if self.model.count() == 0:
            self.model.insert({
                "version": 1,
                "weights": {"trend": 1.0, "indicators": 1.0, "patterns": 1.0, "smc": 1.0, "news": 1.0, "macro": 1.0},
                "trainedAt": int(time.time() * 1000),
                "sampleCount": 0,
            })

    def record_outcome(self, decision, trade_result):
        """Persist a trade outcome and update the model weights."""
        news_category = decision.get("newsCategory") or (decision.get("news") or {}).get("category") or "unknown"
        setup = decision.get("setup") or (decision.get("meta") or {}).get("setup") or "default"
        timeframe = (
            decision.get("timeframe")
            or (decision.get("consensus") or {}).get("timeframe")
            or (decision.get("meta") or {}).get("timeframe")
            or "default"
        )
        validation = decision.get("validation")
        log = self.col.insert({
            "symbol": decision.get("symbol"),
            "direction": (decision.get("consensus") or {}).get("direction"),
            "confidence": (decision.get("confidence") or {}).get("score"),
            "profit": trade_result.get("profit"),
            "win": trade_result.get("profit", 0) > 0,
            "timestamp": int(time.time() * 1000),
            "agentContributions": (decision.get("xai") or {}).get("contributions"),
            "newsCategory": news_category,
            "setup": setup,
            "timeframe": timeframe,
            "validation": validation,
            "mistakeReason": self._extract_mistake_reason(decision, validation),
        })

        m = self.model.find_one({})
        sample_count = (m.get("sampleCount") or 0) + 1
        new_weights = dict(m.get("weights") or {})
        improvement = 1.005 if trade_result.get("profit", 0) > 0 else 0.995
        for key in list(new_weights.keys()):
            new_weights[key] = min(max(new_weights[key] * improvement, 0.5), 1.5)
        self.model.update(m["id"], {
            "version": m.get("version", 0) + 1,
            "weights": new_weights,
            "trainedAt": int(time.time() * 1000),
            "sampleCount": sample_count,
        })
        self._shadow_record(log)
        ai_memory.remember("last-training", {"sampleCount": sample_count, "version": m.get("version", 0) + 1})

        logger.info(f"Learning engine: recorded outcome {'win' if trade_result.get('profit', 0) > 0 else 'loss'}, sample #{sample_count}")
        return log

    def record_experience(self, state, action, reward, next_state, done):
        """Add an experience tuple to the replay buffer, evicting oldest when over cap."""
        entry = self.replay_col.insert({
            "state": state,
            "action": action,
            "reward": reward,
            "nextState": next_state,
            "done": bool(done),
            "timestamp": int(time.time() * 1000),
        })
        overflow = self.replay_col.count() - REPLAY_BUFFER_CAP
        if overflow > 0:
            oldest = self.replay_col.find({}, {"sort": ["timestamp", "asc"]})
            for row in oldest[:overflow]:
                self.replay_col.remove(row["id"])
        return entry

    def pattern_stats(self):
        """Aggregate learning_log win rates by 'newsCategory:setup' pattern key."""
        logs = self.col.find({})
        agg = {}
        for l in logs:
            cat = l.get("newsCategory") or "unknown"
            setup = l.get("setup") or "default"
            key = f"{cat}:{setup}"
            bucket = agg.setdefault(key, {"pattern": key, "newsCategory": cat, "setup": setup, "wins": 0, "sampleCount": 0})
            bucket["wins"] += 1 if l.get("win") else 0
            bucket["sampleCount"] += 1
        for bucket in agg.values():
            bucket["winRate"] = round(bucket["wins"] / bucket["sampleCount"] * 100) / 100 if bucket["sampleCount"] else 0
        return agg

    def best_patterns(self, k=5):
        """Return the top-k patterns ranked by win rate then sample count."""
        patterns = list(self.pattern_stats().values())
        patterns.sort(key=lambda p: (p["winRate"], p["sampleCount"]), reverse=True)
        return patterns[:k]

    # ---- Persisted pattern learning (win rate by newsCategory + setup) ----
    def persist_pattern_stats(self):
        """Store the aggregated win-rate table into ``learning_patterns``.

        The AI agents query this persisted table directly (rather than
        recomputing from the raw log) so win rates by ``newsCategory`` +
        technical ``setup`` are stable and auditable over time.
        """
        pattern_col = db.collection("learning_patterns")
        current = {p["pattern"]: p for p in self.pattern_stats().values()}
        existing = {p["pattern"]: p for p in pattern_col.find({})}
        for key, stats in current.items():
            prev = existing.get(key)
            row = {
                "pattern": key,
                "newsCategory": stats["newsCategory"],
                "setup": stats["setup"],
                "wins": stats["wins"],
                "sampleCount": stats["sampleCount"],
                "winRate": stats["winRate"],
                "updatedAt": int(time.time() * 1000),
            }
            if prev:
                pattern_col.update(prev["id"], row)
            else:
                pattern_col.insert(row)
        return pattern_col.find({})

    def get_pattern_win_rate(self, news_category, technical_setup):
        """Look up the persisted win rate for a news category + technical setup."""
        pattern_col = db.collection("learning_patterns")
        rows = pattern_col.find({"newsCategory": news_category, "setup": technical_setup})
        if rows:
            best = max(rows, key=lambda r: r.get("sampleCount", 0))
            return {"pattern": best.get("pattern"), "winRate": best.get("winRate"), "sampleCount": best.get("sampleCount")}
        return {"pattern": f"{news_category}:{technical_setup}", "winRate": None, "sampleCount": 0}

    def mistake_analysis(self):
        """Group losses by rejection/validation reason and attach improvement suggestions."""
        logs = self.col.find({})
        losses = [l for l in logs if not l.get("win")]
        agg = {}
        for l in losses:
            reason = l.get("mistakeReason") or "unknown"
            bucket = agg.setdefault(reason, {"reason": reason, "count": 0, "suggestion": None})
            bucket["count"] += 1
        for bucket in agg.values():
            bucket["suggestion"] = (
                MISTAKE_SUGGESTIONS.get(bucket["reason"])
                or MISTAKE_SUGGESTIONS.get(str(bucket["reason"]).lower())
                or "Review the entry conditions and add tighter filters for this failure mode"
            )
        return {
            "totalLosses": len(losses),
            "byReason": sorted(agg.values(), key=lambda b: b["count"], reverse=True),
        }

    def champion_challenger(self, n=20, margin_pp=CHALLENGER_MARGIN_PP):
        """Compare the champion model against a challenger over the last N outcomes."""
        m = self.model.find_one({})
        logs = sorted(self.col.find({}), key=lambda l: l["timestamp"], reverse=True)[:n]
        total = len(logs)
        champ_wins = sum(1 for l in logs if l.get("win"))
        champ_rate = round(champ_wins / total * 100) / 100 if total else 0

        cc = self.challenger_col.find_one({})
        if cc is None:
            cc = self._create_challenger(m)

        chal_total = cc.get("wins", 0) + cc.get("losses", 0)
        chal_rate = round(cc.get("wins", 0) / chal_total * 100) / 100 if chal_total else champ_rate

        status = "champion"
        if chal_total >= CHALLENGER_MIN_SAMPLES and (chal_rate - champ_rate) * 100 > margin_pp:
            self.model.update(m["id"], {
                "version": m.get("version", 0) + 1,
                "weights": cc.get("weights") or m.get("weights"),
                "trainedAt": int(time.time() * 1000),
                "sampleCount": m.get("sampleCount", 0),
                "previousWeights": m.get("weights"),
                "previousWinRate": champ_rate,
                "promotedFromChallenger": True,
            })
            self.challenger_col.update(cc["id"], {"wins": 0, "losses": 0, "sampleCount": 0, "promotedAt": int(time.time() * 1000)})
            status = "challenger_wins"
        elif m.get("promotedFromChallenger") and m.get("previousWinRate") is not None and champ_rate < m["previousWinRate"] - margin_pp / 100:
            self.model.update(m["id"], {
                "version": m.get("version", 0) + 1,
                "weights": m.get("previousWeights") or m.get("weights"),
                "trainedAt": int(time.time() * 1000),
                "sampleCount": m.get("sampleCount", 0),
                "previousWeights": None,
                "previousWinRate": None,
                "promotedFromChallenger": False,
            })
            status = "rollback"

        m = self.model.find_one({})
        return {
            "champion": {
                "version": m.get("version"),
                "weights": m.get("weights"),
                "sampleCount": m.get("sampleCount"),
                "trainedAt": m.get("trainedAt"),
            },
            "challenger": {
                "version": cc.get("version"),
                "weights": cc.get("weights"),
                "sampleCount": cc.get("sampleCount", 0),
                "wins": cc.get("wins", 0),
                "losses": cc.get("losses", 0),
                "winRate": chal_rate,
            },
            "status": status,
            "comparison": {
                "championWinRate": champ_rate,
                "challengerWinRate": chal_rate,
                "marginPp": round((chal_rate - champ_rate) * 100, 2),
                "outcomesCompared": min(chal_total, n),
            },
        }

    def strategy_learning(self):
        """Per-strategy (direction + timeframe) win rate and expectancy after trade costs."""
        logs = self.col.find({})
        agg = {}
        for l in logs:
            direction = l.get("direction") or "neutral"
            timeframe = l.get("timeframe") or "default"
            key = f"{direction}:{timeframe}"
            bucket = agg.setdefault(key, {
                "strategy": key,
                "direction": direction,
                "timeframe": timeframe,
                "wins": 0,
                "sampleCount": 0,
                "totalProfit": 0.0,
            })
            bucket["wins"] += 1 if l.get("win") else 0
            bucket["sampleCount"] += 1
            bucket["totalProfit"] += l.get("profit") or 0
        strategies = []
        for bucket in agg.values():
            count = bucket["sampleCount"]
            avg_profit = round(bucket["totalProfit"] / count * 100) / 100 if count else 0
            cost = round(TRADE_COST_PCT * abs(avg_profit) * 100) / 100
            strategies.append({
                "strategy": bucket["strategy"],
                "direction": bucket["direction"],
                "timeframe": bucket["timeframe"],
                "winRate": round(bucket["wins"] / count * 100) / 100 if count else 0,
                "sampleCount": count,
                "avgProfit": avg_profit,
                "estCostPerTrade": cost,
                "expectancy": round((avg_profit - cost) * 100) / 100,
            })
        strategies.sort(key=lambda s: s["expectancy"], reverse=True)
        return strategies

    def get_state(self):
        m = self.model.find_one({})
        logs = self.col.find({})
        wins = sum(1 for l in logs if l.get("win"))
        total = len(logs)
        mistakes = self.mistake_analysis()
        return {
            "version": m["version"],
            "weights": m["weights"],
            "sampleCount": m["sampleCount"],
            "trainedAt": m["trainedAt"],
            "performance": {
                "total": total,
                "winRate": round(wins / total * 100) / 100 if total else 0,
                "avgProfit": round(sum((l.get("profit") or 0) for l in logs) / total * 100) / 100 if total else 0,
            },
            "recentLogs": sorted(logs, key=lambda l: l["timestamp"], reverse=True)[:10],
            "replayBufferSize": self.replay_col.count(),
            "patternLearning": {
                "trackedPatterns": len(self.pattern_stats()),
                "bestPatterns": self.best_patterns(5),
            },
            "mistakeSummary": {
                "totalLosses": mistakes["totalLosses"],
                "lossRate": round(mistakes["totalLosses"] / total * 100) / 100 if total else 0,
                "topReasons": mistakes["byReason"][:3],
            },
            "championChallenger": self.champion_challenger(),
            "strategyPerformance": self.strategy_learning(),
        }

    def _create_challenger(self, model):
        """Create a challenger model as a lightly perturbed copy of the champion."""
        weights = {}
        for key, value in (model.get("weights") or {}).items():
            weights[key] = round(min(max(float(value) * 1.02, 0.5), 1.5), 3)
        return self.challenger_col.insert({
            "version": model.get("version", 0),
            "weights": weights,
            "wins": 0,
            "losses": 0,
            "sampleCount": 0,
            "createdAt": int(time.time() * 1000),
        })

    def _shadow_record(self, log):
        """Evaluate the challenger on the same outcome via deterministic shadow trade."""
        cc = self.challenger_col.find_one({})
        if cc is None:
            return
        direction = log.get("direction")
        if direction not in ("buy", "sell"):
            return
        outcome = self._shadow_outcome(log, cc)
        if outcome is None:
            return
        patch = {
            "sampleCount": cc.get("sampleCount", 0) + 1,
            "lastEvaluatedAt": log.get("timestamp"),
        }
        if outcome:
            patch["wins"] = cc.get("wins", 0) + 1
        else:
            patch["losses"] = cc.get("losses", 0) + 1
        self.challenger_col.update(cc["id"], patch)

    def _shadow_outcome(self, log, challenger):
        """Determine challenger win/loss: 5% exploration may flip the traded direction."""
        weights = challenger.get("weights") or {}
        seed_val = int(sum(float(v) for v in weights.values()) * 1000) + sum(ord(c) for c in str(log.get("symbol") or "X"))
        explores = seed_val % 100 < 5
        won = bool(log.get("win"))
        if not explores:
            return won
        return not won

    def _extract_mistake_reason(self, decision, validation):
        """Extract a loss reason from decision validation metadata or xai explanation."""
        if isinstance(validation, dict):
            reason = validation.get("reason") or validation.get("rejection") or validation.get("status")
            if reason:
                return str(reason)
        elif validation:
            return str(validation)
        xai = decision.get("xai") or {}
        reason = xai.get("reason") or xai.get("decision")
        if reason:
            return str(reason)
        return "unknown"


learning_engine = LearningEngine()


def init_learning():
    logger.info("AI learning engine initialized")
    return learning_engine

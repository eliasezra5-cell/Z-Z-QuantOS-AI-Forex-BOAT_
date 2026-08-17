"""Pattern Learning Engine (Phase 2, Module 2) — additive.

Computes historical win rates for the ``news_category + technical_setup``
combination and persists them so the AI decision pipeline can query them
before acting. This is a pure offline learning framework: nothing is learned
from live trades beyond the persisted aggregate statistics, and every stored
value is auditable.

Purely additive: reads the same ``learning_log`` collection the existing
learning engine writes, but stores its aggregated pattern table in its own
``pattern_win_rates`` collection and exposes a ``win_rate_boost`` helper the
AI agents can use to adjust a candidate decision's confidence.
"""
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db

MIN_SAMPLE_FOR_BOOST = 5
DECIMAL_QUANT = Decimal("0.0001")


def _dec(value, fallback=Decimal("0")):
    if value is None:
        return fallback
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return fallback


class PatternLearningEngine:
    def __init__(self):
        self.log_col = db.collection("learning_log")
        self.pattern_col = db.collection("pattern_win_rates")
        self.analysis_col = db.collection("pattern_learning_analysis")

    # ------------------------------------------------------------------ #
    # Aggregation: win rate by news_category + technical_setup
    # ------------------------------------------------------------------ #
    def compute(self, logs=None):
        """Aggregate learning_log into (newsCategory, setup) win rates."""
        logs = logs if logs is not None else self.log_col.find({})
        agg = {}
        for entry in logs:
            category = entry.get("newsCategory") or entry.get("decision", {}).get("news", {}).get("category") or "unknown"
            setup = entry.get("setup") or (entry.get("decision", {}).get("meta") or {}).get("setup") or "default"
            key = f"{category}:{setup}"
            bucket = agg.setdefault(key, {
                "pattern": key,
                "newsCategory": category,
                "technicalSetup": setup,
                "wins": 0,
                "sampleCount": 0,
            })
            won = entry.get("win")
            if won is None:
                won = (entry.get("profit") or 0) > 0 or entry.get("outcome") == "win"
            bucket["wins"] += 1 if won else 0
            bucket["sampleCount"] += 1
        rows = []
        for bucket in agg.values():
            count = bucket["sampleCount"]
            win_rate = _dec(bucket["wins"]) / _dec(count) if count else Decimal("0")
            rows.append({
                **bucket,
                "winRate": float(win_rate.quantize(DECIMAL_QUANT, rounding=ROUND_HALF_UP)),
                "updatedAt": int(time.time() * 1000),
            })
        rows.sort(key=lambda r: (r["winRate"], r["sampleCount"]), reverse=True)
        return rows

    def persist(self, logs=None):
        """Store the aggregated pattern table into ``pattern_win_rates``."""
        rows = self.compute(logs)
        existing = {p.get("pattern"): p for p in self.pattern_col.find({})}
        stored = []
        for row in rows:
            prev = existing.get(row["pattern"])
            if prev:
                self.pattern_col.update(prev["id"], row)
                stored.append({**row, "id": prev["id"]})
            else:
                inserted = self.pattern_col.insert(row)
                stored.append(inserted)
        event_bus.emit("pattern-learning:persisted", {"patterns": len(stored)})
        return stored

    # ------------------------------------------------------------------ #
    # Query API for the AI decision pipeline
    # ------------------------------------------------------------------ #
    def get_win_rate(self, news_category, technical_setup):
        """Return the persisted win rate for a news category + technical setup."""
        rows = self.pattern_col.find({"newsCategory": news_category, "technicalSetup": technical_setup})
        if rows:
            best = max(rows, key=lambda r: r.get("sampleCount", 0))
            return {
                "pattern": best.get("pattern"),
                "winRate": best.get("winRate"),
                "sampleCount": best.get("sampleCount"),
            }
        return {"pattern": f"{news_category}:{technical_setup}", "winRate": None, "sampleCount": 0}

    def win_rate_boost(self, news_category, technical_setup, base_confidence=0.0):
        """Adjust a candidate confidence by the historical win rate edge.

        Returns ``(adjusted_confidence, meta)``. No adjustment is applied when
        the pattern has not been observed enough times (avoids overfitting on
        tiny samples).
        """
        pattern = self.get_win_rate(news_category, technical_setup)
        if pattern.get("sampleCount", 0) < MIN_SAMPLE_FOR_BOOST or pattern.get("winRate") is None:
            return base_confidence, {
                "pattern": pattern.get("pattern"),
                "adjusted": False,
                "reason": f"insufficient samples ({pattern.get('sampleCount')}/{MIN_SAMPLE_FOR_BOOST})",
                "winRate": pattern.get("winRate"),
            }
        win_rate = _dec(pattern.get("winRate"))
        base = _dec(base_confidence)
        # Blend the model confidence with the historical win rate (50/50) so
        # the learned edge nudges — but never overrides — the AI confidence.
        adjusted = (base + win_rate) / Decimal("2")
        adjusted = min(max(adjusted, Decimal("0")), Decimal("1"))
        return float(adjusted.quantize(DECIMAL_QUANT, rounding=ROUND_HALF_UP)), {
            "pattern": pattern.get("pattern"),
            "adjusted": True,
            "reason": "historical win rate blend",
            "winRate": pattern.get("winRate"),
            "sampleCount": pattern.get("sampleCount"),
        }

    def summary(self):
        rows = self.pattern_col.find({})
        total = len(rows)
        boosted = sum(1 for r in rows if r.get("sampleCount", 0) >= MIN_SAMPLE_FOR_BOOST)
        return {
            "trackedPatterns": total,
            "patternsWithEnoughSamples": boosted,
            "minSampleForBoost": MIN_SAMPLE_FOR_BOOST,
            "bestPatterns": self.top_patterns(5),
        }

    def top_patterns(self, k=5):
        rows = sorted(self.pattern_col.find({}), key=lambda r: (r.get("winRate") or 0, r.get("sampleCount") or 0), reverse=True)
        return rows[:k]


pattern_learning = PatternLearningEngine()


def init_pattern_learning():
    logger.info("Pattern learning engine initialized (win rate by newsCategory + technicalSetup)")
    return pattern_learning

"""Mistake Analysis Engine (Phase 2, Module 2) — additive.

Daily root-cause analysis of losing trades. Deterministic heuristic rules
classify each loss into an actionable root cause ("Ignored high spread",
"Entered against DXY trend", "Low confidence entry", ...) so the team can
tighten the corresponding filters. This is offline analysis only — no
live, unsupervised self-learning.

Purely additive: reads ``learning_log`` / ``historical_trades`` and writes
its findings to the ``mistake_analysis`` collection for the frontend and the
daily Celery worker to consume.
"""
import time
from decimal import Decimal, InvalidOperation

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db

SPREAD_MISTAKE_THRESHOLD = Decimal("30")


def _dec(value, fallback=Decimal("0")):
    if value is None:
        return fallback
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return fallback


class MistakeAnalyzer:
    def __init__(self):
        self.col = db.collection("learning_log")
        self.result_col = db.collection("mistake_analysis")

    # ------------------------------------------------------------------ #
    # Root-cause classification (deterministic heuristics)
    # ------------------------------------------------------------------ #
    def classify(self, trade):
        """Return the most likely root cause for a losing trade.

        Priority:
          1. entered into a wide spread
          2. went against the DXY trend (risk-on/off conflict)
          3. low-confidence entry (below profile minimum)
          4. no stop-loss protection
          5. unknown
        """
        spread = trade.get("spreadAtEntry") or (trade.get("decision", {}).get("context", {}) or {}).get("spreadPips")
        if spread is not None and _dec(spread) >= SPREAD_MISTAKE_THRESHOLD:
            return {"root_cause": "Ignored high spread", "confidence": 0.9, "detail": f"entered with spread {spread}"}

        dxy_trend = trade.get("dxyTrend") or (trade.get("decision", {}).get("macro", {}) or {}).get("dxy", {}).get("trend")
        direction = (trade.get("direction") or "").lower()
        if dxy_trend and direction:
            if dxy_trend == "bullish" and direction == "sell":
                return {"root_cause": "Entered against DXY trend", "confidence": 0.85, "detail": f"short while DXY bullish"}
            if dxy_trend == "bearish" and direction == "buy":
                return {"root_cause": "Entered against DXY trend", "confidence": 0.85, "detail": f"long while DXY bearish"}

        confidence = trade.get("confidence")
        if isinstance(confidence, dict):
            confidence = confidence.get("score")
        if confidence is not None and _dec(confidence) < Decimal("0.70"):
            return {"root_cause": "Low confidence entry", "confidence": 0.8, "detail": f"entered at confidence {confidence}"}

        if trade.get("stopLoss") is None:
            return {"root_cause": "No stop-loss protection", "confidence": 0.75, "detail": "position opened without SL"}

        return {"root_cause": "Unknown", "confidence": 0.3, "detail": "no obvious rule violated"}

    # ------------------------------------------------------------------ #
    # Daily run: analyze every losing trade and aggregate root causes
    # ------------------------------------------------------------------ #
    def analyze(self, logs=None):
        logs = logs if logs is not None else self.col.find({})
        losses = [entry for entry in logs if not entry.get("win")]
        findings = []
        for entry in losses:
            cause = self.classify(entry)
            findings.append({
                "position_id": entry.get("id"),
                "symbol": entry.get("symbol"),
                "direction": entry.get("direction"),
                "profit": entry.get("profit"),
                "newsCategory": entry.get("newsCategory"),
                "setup": entry.get("setup"),
                "timestamp": entry.get("timestamp"),
                **cause,
            })
        aggregated = {}
        for finding in findings:
            key = finding["root_cause"]
            bucket = aggregated.setdefault(key, {"root_cause": key, "count": 0, "avgLoss": Decimal("0")})
            bucket["count"] += 1
            bucket["avgLoss"] += _dec(finding.get("profit"))
        for bucket in aggregated.values():
            if bucket["count"]:
                bucket["avgLoss"] = float(bucket["avgLoss"] / _dec(bucket["count"]))
        summary = {
            "analyzedAt": int(time.time() * 1000),
            "totalLosses": len(findings),
            "byRootCause": sorted(
                aggregated.values(),
                key=lambda b: b["count"],
                reverse=True,
            ),
        }
        self.result_col.insert(summary)
        event_bus.emit("mistake-analysis:complete", summary)
        return summary

    def latest(self, limit=5):
        rows = self.result_col.find({})
        return rows[-limit:]

    def health(self):
        return {
            "runs": self.result_col.count(),
            "latest": self.latest(1)[-1] if self.result_col.count() else None,
        }


mistake_analyzer = MistakeAnalyzer()


def init_mistake_analyzer():
    logger.info("Mistake analysis engine initialized (offline root-cause analysis)")
    return mistake_analyzer

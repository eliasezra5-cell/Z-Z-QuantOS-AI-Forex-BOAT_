"""Research Manager (Feature 1 — debate resolution).

Resolves the bull vs bear researcher debate into a 5-tier institutional rating
(Buy / Overweight / Hold / Underweight / Sell) WITHOUT averaging the two
arguments blindly: it weights each side by its stated confidence and rebuttal
strength, then maps the net stance onto the rating scale. The resolved rating
is fed into ``consensus_v2.compute_consensus`` as one additional weighted voice
(never a dictator — the existing abstention / veto logic is untouched).
"""
from .agents.base import AgentResult, clamp01

RATING_SCALE = ["Buy", "Overweight", "Hold", "Underweight", "Sell"]

# Rating -> (direction, directional strength) used as a consensus nudge.
RATING_SIGNAL = {
    "Buy": ("buy", 1.0),
    "Overweight": ("buy", 0.6),
    "Hold": ("neutral", 0.0),
    "Underweight": ("sell", 0.6),
    "Sell": ("sell", 1.0),
}


def _data_of(result):
    if result is None:
        return {}
    return result.data if hasattr(result, "data") else (result.get("data") or {})


def _abstention_of(result, default="TRADE"):
    if result is None:
        return "MISSING"
    abst = getattr(result, "abstention", None)
    if abst:
        return str(abst).upper()
    if isinstance(result, dict):
        return str(result.get("abstention") or default).upper()
    return default


def rating_for_net(net):
    if net >= 0.50:
        return "Buy"
    if net >= 0.20:
        return "Overweight"
    if net > -0.20:
        return "Hold"
    if net > -0.50:
        return "Underweight"
    return "Sell"


class ResearchManager:
    def resolve(self, bull_result, bear_result, context=None):
        """Resolve the debate into a rating + rationale + transcript.

        ``bull_result`` / ``bear_result`` are AgentResult objects (or dicts with
        a ``data`` field) carrying ``{stance, argument, confidence, counters}``.
        Returns a dict with rating, direction, strength, rationale and an
        ordered debate transcript.

        When neither side produced an analyst case (non-``TRADE`` abstention,
        e.g. ``PROVIDER_DEGRADED`` / ``DATA_INSUFFICIENT``), the result is
        marked ``available: false`` / ``status: "unavailable"`` with a human
        reason — it never fabricates a neutral-looking rating from two empty
        cases. When only one side is available the debate still resolves but is
        flagged ``status: "partial"``.
        """
        context = context or {}
        bull_data = _data_of(bull_result)
        bear_data = _data_of(bear_result)

        bull_abst = _abstention_of(bull_result)
        bear_abst = _abstention_of(bear_result)
        bull_available = bull_abst == "TRADE" and bool(str(bull_data.get("argument") or "").strip())
        bear_available = bear_abst == "TRADE" and bool(str(bear_data.get("argument") or "").strip())

        if not bull_available and not bear_available:
            return self._unavailable(bull_abst, bear_abst, bull_data, bear_data)

        bull_conf = clamp01(bull_data.get("confidence")) if bull_available else 0.0
        bear_conf = clamp01(bear_data.get("confidence")) if bear_available else 0.0
        bull_arg = str(bull_data.get("argument") or "").strip() if bull_available else ""
        bear_arg = str(bear_data.get("argument") or "").strip() if bear_available else ""

        # Weighted net stance: +1 = bull wins, -1 = bear wins.
        total = bull_conf + bear_conf
        if total > 0:
            net = (bull_conf - bear_conf) / total
        else:
            net = 0.0

        # Argument strength bonus: a side with multiple rebuttal counters is
        # considered stronger when the two confidences are close.
        bull_counters = [str(c) for c in (bull_data.get("counters") or []) if str(c).strip()] if bull_available else []
        bear_counters = [str(c) for c in (bear_data.get("counters") or []) if str(c).strip()] if bear_available else []
        spread = abs(bull_conf - bear_conf)
        rebuttal_bonus = 0.10 if (bull_counters and bear_counters and spread < 0.25) else 0.0
        net = clamp01(abs(net) + rebuttal_bonus) * (1 if net >= 0 else -1)

        rating = rating_for_net(net)
        direction, strength = RATING_SIGNAL[rating]

        transcript = [
            {"speaker": "bull", "stance": "bull", "argument": bull_arg,
             "counters": bull_counters, "confidence": round(bull_conf, 3), "state": bull_abst},
            {"speaker": "bear", "stance": "bear", "argument": bear_arg,
             "counters": bear_counters, "confidence": round(bear_conf, 3), "state": bear_abst},
            {"speaker": "research_manager", "stance": rating,
             "argument": None, "counters": [], "confidence": round(strength, 3)},
        ]

        rationale = (
            f"Bull confidence {bull_conf:.2f} vs Bear confidence {bear_conf:.2f} "
            f"-> net stance {net:+.2f} -> {rating}. "
            + (f"Bull rebutted with {len(bull_counters)} counter-points; "
               f"bear rebutted with {len(bear_counters)}." if bull_counters or bear_counters else "")
        ).strip()

        if not (bull_available and bear_available):
            missing = "bear" if not bear_available else "bull"
            missing_state = bear_abst if missing == "bear" else bull_abst
            rationale = (f"{missing.capitalize()} case unavailable ({missing_state}); " + rationale).strip()
            status = "partial"
        else:
            status = "complete"

        return {
            "available": True,
            "status": status,
            "rating": rating,
            "direction": direction,
            "strength": round(strength, 3),
            "net": round(net, 3),
            "rationale": rationale,
            "transcript": transcript,
            "bull": {
                "stance": "bull",
                "argument": bull_arg,
                "confidence": round(bull_conf, 3),
                "counters": bull_counters,
                "state": bull_abst,
            },
            "bear": {
                "stance": "bear",
                "argument": bear_arg,
                "confidence": round(bear_conf, 3),
                "counters": bear_counters,
                "state": bear_abst,
            },
        }

    def _unavailable(self, bull_abst, bear_abst, bull_data, bear_data):
        """Debate could not run: neither side produced an analyst case."""
        reason = (
            f"Research debate unavailable — neither side produced an analyst case "
            f"(bull: {bull_abst}, bear: {bear_abst}). Configure and reach an LLM "
            f"provider to enable the bull/bear debate."
        )
        transcript = [
            {"speaker": "bull", "stance": "bull", "argument": "", "counters": [],
             "confidence": 0.0, "state": bull_abst},
            {"speaker": "bear", "stance": "bear", "argument": "", "counters": [],
             "confidence": 0.0, "state": bear_abst},
            {"speaker": "research_manager", "stance": "unavailable", "argument": None,
             "counters": [], "confidence": 0.0, "state": "LLM_UNAVAILABLE"},
        ]
        return {
            "available": False,
            "status": "unavailable",
            "rating": None,
            "direction": "neutral",
            "strength": 0.0,
            "net": 0.0,
            "rationale": reason,
            "reason": reason,
            "transcript": transcript,
            "bull": {"stance": "bull", "argument": "", "confidence": 0.0,
                     "counters": [], "state": bull_abst},
            "bear": {"stance": "bear", "argument": "", "confidence": 0.0,
                     "counters": [], "state": bear_abst},
        }


research_manager = ResearchManager()

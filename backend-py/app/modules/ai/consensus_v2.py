"""Strict 80/20 Consensus Engine (additive, institutional mandate).

Directional Confidence Calculation (100% total):
  - News Analysis Agent    : 40%
  - Historical Pattern     : 20%
  - Macro Analysis         : 20%
  - Technical Execution    : 20%   (EXECUTION only, never direction)
  News Family = News + Historical + Macro = 80%. Technical = 20%.

Risk Manager Agent (VETO POWER):
  - Risk contributes NO directional weight.
  - risk_approved = False  => Final Decision is immediately NO_TRADE.
  - risk_approved = True   => Final Confidence = 40/20/20/20 formula.

Technical execution weight is only applied when the agent confirms an entry;
when it abstains/rejects, its 20% is redistributed proportionally across the
three directional agents (technical never carries a directional vote).
"""
from decimal import Decimal, ROUND_HALF_UP

from ...foundation.logger import logger

CORE_WEIGHTS = {
    "news": Decimal("0.40"),
    "historical": Decimal("0.20"),
    "macro": Decimal("0.20"),
    "technical": Decimal("0.20"),
}

DIRECTIONAL = ("news", "historical", "macro")
ABSTENTION_STATES = {
    "TRADE", "NO_TRADE", "WAIT_FOR_CONFIRMATION", "DATA_INSUFFICIENT",
    "CONFLICTING_SIGNALS", "STALE_EVENT", "ALREADY_PRICED_IN",
    "MARKET_CLOSED", "RISK_BLOCKED", "PROVIDER_DEGRADED", "ABSTAIN", "REJECTED",
}

# Bull vs Bear research rating contributes as ONE additional weighted voice,
# capped so it can nudge but never dictate the strict 80/20 consensus.
DEBATE_CAP = Decimal("0.10")


def _dec(value, default=Decimal("0")):
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal(str(default))


def compute_consensus(agent_results, risk_result=None, debate_result=None):
    """Compute the final decision from agent results.

    ``agent_results``: list of AgentResult dicts (or objects with to_dict()).
    ``risk_result``: the RiskManagerAgent result (veto) or None.
    ``debate_result``: optional dict from ``ResearchManager.resolve`` with
        ``direction`` (buy/sell/neutral) and ``strength`` (0..1). It is ONE
        extra weighted voice (capped at 10%) — never overrides veto/abstention.

    Returns a dict with direction, confidence, weights, status and XAI data.
    """
    votes = []
    for r in agent_results:
        d = r.to_dict() if hasattr(r, "to_dict") else r
        votes.append(d)

    risk_approved = True
    risk_reasons = []
    risk_blocked = False
    if risk_result is not None:
        rd = risk_result.to_dict() if hasattr(risk_result, "to_dict") else risk_result
        risk_approved = bool(rd.get("data", {}).get("riskApproved", rd.get("riskApproved", True)))
        risk_reasons = rd.get("data", {}).get("reasons", [])
        risk_blocked = not risk_approved

    # ---- Directional scoring from the three news-family agents + technical ----
    directional_scores = {"buy": Decimal("0"), "sell": Decimal("0"), "neutral": Decimal("0")}
    directional_weight_used = Decimal("0")
    abstentions = []
    technical_result = None

    for v in votes:
        aid = v.get("agent_id")
        weight = _dec(v.get("weight"), CORE_WEIGHTS.get(aid, Decimal("0")))
        if aid == "risk":
            continue  # veto only
        abstention = str(v.get("abstention") or "TRADE").upper()
        if abstention not in ABSTENTION_STATES:
            abstention = "DATA_INSUFFICIENT"
        conf = _dec(v.get("confidence"))
        if aid == "technical":
            technical_result = {"state": abstention, "confidence": conf, "execution": v.get("data", {}).get("execution")}
            # Technical contributes to execution quality, not direction.
            continue
        if abstention != "TRADE":
            abstentions.append({"agent": aid, "state": abstention, "confidence": float(conf), "reasoning": v.get("reasoning")})
            continue
        direction = str(v.get("direction") or "neutral").lower()
        if direction not in directional_scores:
            direction = "neutral"
        # A vote only carries weight when direction is not neutral (avoid 80/20 dilution).
        if direction == "neutral":
            abstentions.append({"agent": aid, "state": "ABSTAIN", "confidence": float(conf), "reasoning": v.get("reasoning")})
            continue
        directional_scores[direction] += weight * conf
        directional_weight_used += weight

    # Redistribute unused directional weight (neutral votes / abstentions)
    # proportionally across the directional agents that did vote.
    active_directional = [aid for aid in DIRECTIONAL
                          if any(v.get("agent_id") == aid and str(v.get("abstention") or "TRADE").upper() == "TRADE"
                                 and str(v.get("direction") or "neutral").lower() != "neutral" for v in votes)]
    if active_directional:
        remaining = Decimal("0.80") - directional_weight_used
        if remaining > 0:
            share = remaining / Decimal(len(active_directional))
            for aid in active_directional:
                vote = next(v for v in votes if v.get("agent_id") == aid)
                conf = _dec(vote.get("confidence"))
                direction = str(vote.get("direction") or "neutral").lower()
                directional_scores[direction] += share * conf
                directional_weight_used += share

    total_weighted = sum(directional_scores.values())
    if total_weighted > 0:
        direction = max(directional_scores, key=directional_scores.get)
        core_confidence = directional_scores[direction] / total_weighted
    else:
        direction = "neutral"
        core_confidence = Decimal("0")

    # ---- Technical execution gate ----
    technical_confirmed = technical_result is not None and technical_result["state"] == "TRADE"
    if not technical_confirmed and direction in ("buy", "sell"):
        # Technical rejected the entry: degrade confidence, keep direction.
        core_confidence = core_confidence * Decimal("0.7")
        execution_status = "rejected"
    else:
        execution_status = "confirmed" if technical_confirmed else "n/a"

    # ---- Custom agents (weighted after core 80%) ----
    custom_total = Decimal("0")
    custom_scores = {"buy": Decimal("0"), "sell": Decimal("0"), "neutral": Decimal("0")}
    custom_details = []
    for v in votes:
        if not str(v.get("agent_id") or "").startswith("custom-"):
            continue
        if str(v.get("abstention") or "TRADE").upper() != "TRADE":
            custom_details.append({"agent": v.get("name"), "state": v.get("abstention"), "contribution": 0.0})
            continue
        w = _dec(v.get("weight"))
        conf = _dec(v.get("confidence"))
        d = str(v.get("direction") or "neutral").lower()
        if d in custom_scores:
            custom_scores[d] += w * conf
            custom_total += w
            custom_details.append({"agent": v.get("name"), "state": "TRADE",
                                   "contribution": float((w * conf).quantize(Decimal("0.0001"), ROUND_HALF_UP))})

    # ---- Combine core + custom into final directional score ----
    final_scores = {"buy": directional_scores["buy"], "sell": directional_scores["sell"]}
    # Custom votes shift the core (news-family) direction.
    for d in ("buy", "sell"):
        if custom_scores[d] > 0:
            final_scores[d] += custom_scores[d] * Decimal("0.20")  # custom capped at 20% of total weight

    # ---- Research debate rating: one more voice, never a dictator ----
    debate_nudge = {"direction": None, "strength": 0.0}
    if debate_result is not None and debate_result.get("direction") in ("buy", "sell"):
        d = debate_result["direction"]
        s = _dec(debate_result.get("strength"), Decimal("0"))
        if s > Decimal("0"):
            final_scores[d] += s * DEBATE_CAP
            debate_nudge = {"direction": d, "strength": float(s)}

    logger.info(
        "Consensus custom pool: {} custom agent(s) contributing weight {:.4f} -> "
        "customScores {} | debate nudge {}".format(
            len(custom_details), float(custom_total),
            {k: float(v) for k, v in custom_scores.items()}, debate_nudge,
        )
    )
    if not any(str(v.get("abstention") or "TRADE").upper() == "TRADE"
               for v in votes if v.get("agent_id") in DIRECTIONAL):
        logger.warn(
            "Consensus: all directional agents abstained ({}) - degraded consensus".format(
                [v.get("agent_id") for v in votes if v.get("abstention")]
            )
        )

    # ---- Risk veto ----
    if risk_blocked:
        final_decision = {
            "direction": "no_trade",
            "confidence": 0.0,
            "riskApproved": False,
            "riskReasons": risk_reasons,
            "status": "NO_TRADE",
        }
        return _build_result(final_decision, votes, direction, core_confidence,
                             custom_details, technical_result, execution_status,
                             risk_blocked=True, debate_nudge=debate_nudge)

    # ---- Thresholds (90 / 70 / <70) ----
    if direction in ("buy", "sell"):
        max_score = final_scores[direction] if final_scores[direction] > 0 else Decimal("0.01")
        denominator = final_scores["buy"] + final_scores["sell"] or Decimal("1")
        confidence = max_score / denominator
        # Scale confidence into [0,1] using the 80/20 weighting.
        confidence = confidence * Decimal("0.80") + core_confidence * Decimal("0.20")
        confidence = Decimal(str(max(Decimal("0"), min(Decimal("1"), confidence))))
    else:
        confidence = Decimal("0")

    if confidence >= Decimal("0.90"):
        status = "AUTO_EXECUTE"
    elif confidence >= Decimal("0.70"):
        status = "SUGGESTED"
    else:
        status = "NO_TRADE"

    final_decision = {
        "direction": direction if status != "NO_TRADE" else "no_trade",
        "confidence": float(confidence.quantize(Decimal("0.0001"), ROUND_HALF_UP)),
        "riskApproved": True,
        "riskReasons": [],
        "status": status,
    }
    return _build_result(final_decision, votes, direction, core_confidence,
                         custom_details, technical_result, execution_status,
                         risk_blocked=False, debate_nudge=debate_nudge)


def _build_result(final_decision, votes, direction, core_confidence, custom_details,
                  technical_result, execution_status, risk_blocked, debate_nudge=None):
    weights = {
        "news": 0.40, "historical": 0.20, "macro": 0.20, "technical": 0.20,
        "custom": sum(float(v.get("weight", 0)) for v in votes if str(v.get("agent_id") or "").startswith("custom-")),
        "risk": 0.0,  # veto only
    }
    return {
        "direction": final_decision["direction"],
        "confidence": final_decision["confidence"],
        "status": final_decision["status"],
        "riskApproved": final_decision["riskApproved"],
        "riskReasons": final_decision["riskReasons"],
        "weights": weights,
        "core": {
            "direction": direction,
            "confidence": float(core_confidence.quantize(Decimal("0.0001"), ROUND_HALF_UP)),
        },
        "technicalExecution": {
            "status": execution_status,
            "confirmed": technical_result is not None and technical_result["state"] == "TRADE",
        },
        "customAgents": custom_details,
        "agentVotes": votes,
        "xai": {
            "formula": "Final = News*0.40 + Historical*0.20 + Macro*0.20 + Technical*0.20 (execution) + custom; Risk = VETO",
            "newsFamilyWeight": 0.80,
            "technicalWeight": 0.20,
            "riskVeto": risk_blocked,
            "debate": debate_nudge or {"direction": None, "strength": 0.0},
        },
    }


def init_consensus_v2():
    logger.info("Strict 80/20 consensus engine initialized (News family 80%, Technical 20%, Risk veto)")
    return compute_consensus

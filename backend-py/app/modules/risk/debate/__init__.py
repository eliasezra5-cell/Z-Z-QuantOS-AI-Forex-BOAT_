"""Risk Debate Team (Feature 3, additive).

Three risk officers with distinct mandates debate every proposed order before
the portfolio gate runs:

  - Aggressive officer : high risk tolerance, blocks only extreme exposure
  - Conservative officer: low tolerance, tightest limits, earliest reduce/reject
  - Neutral officer    : midpoint between the two

The debate is resolved conservatively: a single reject is a reject, and any
reduce produces the minimum (lowest) allowed volume. The gate can only REDUCE
or REJECT an order — it can never increase volume beyond what was requested.
All officers are deterministic (no LLM dependency) so the gate is testable and
never depends on provider availability.
"""
from .officers import AGGRESSIVE_OFFICER, CONSERVATIVE_OFFICER, NEUTRAL_OFFICER
from .officers import resolve_debate

OFFICERS = {
    "aggressive": AGGRESSIVE_OFFICER,
    "conservative": CONSERVATIVE_OFFICER,
    "neutral": NEUTRAL_OFFICER,
}


def debate_order(context):
    """Run all three officers on one order context.

    ``context``: dict with volume, notionalPct, riskAmountPct (and optional
    stopLoss/confidence/openPositions). Returns the resolved debate dict with
    officer verdicts, overall verdict and a capped maxVolume.
    """
    requested = float(context.get("volume") or 0)
    votes = []
    for stance, fn in OFFICERS.items():
        try:
            votes.append(fn(context))
        except Exception:  # noqa: BLE001 - an officer must never block the pipeline
            votes.append({
                "stance": stance,
                "verdict": "abstain",
                "maxVolume": requested,
                "rationale": "officer unavailable",
                "confidence": 0.0,
            })
    return resolve_debate(votes, requested)

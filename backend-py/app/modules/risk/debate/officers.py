"""Risk officers + debate resolution (Feature 3).

Each officer is a pure function mapping an order-risk context to a vote:

    {"stance", "verdict": approve|reduce|reject, "maxVolume", "rationale", "confidence"}

Thresholds are defined as percentage-of-equity bands (notionalPct / riskAmountPct)
so the same rules scale to any account size. When equity is unknown/zero the
percentages collapse to zero and officers default to approve (a fail-open that
is safe because the surrounding deterministic gates still enforce hard limits).
"""


def _pct(context):
    notional_pct = float(context.get("notionalPct") or 0)
    risk_pct = float(context.get("riskAmountPct") or 0)
    return notional_pct, risk_pct


def AGGRESSIVE_OFFICER(context):
    notional_pct, risk_pct = _pct(context)
    if risk_pct > 8.0 or notional_pct > 40.0:
        return {"stance": "aggressive", "verdict": "reject",
                "maxVolume": 0.0,
                "rationale": f"Extreme exposure: risk {risk_pct:.1f}% / notional {notional_pct:.1f}% of equity",
                "confidence": 0.95}
    return {"stance": "aggressive", "verdict": "approve",
            "maxVolume": float(context.get("volume") or 0),
            "rationale": f"Risk within aggressive tolerance (risk {risk_pct:.1f}%, notional {notional_pct:.1f}%)",
            "confidence": 0.8}


def CONSERVATIVE_OFFICER(context):
    notional_pct, risk_pct = _pct(context)
    stop_loss = context.get("stopLoss")
    if risk_pct > 4.0 or notional_pct > 25.0:
        return {"stance": "conservative", "verdict": "reject",
                "maxVolume": 0.0,
                "rationale": f"Exposure exceeds conservative limits (risk {risk_pct:.1f}% / notional {notional_pct:.1f}%)",
                "confidence": 0.95}
    requested = float(context.get("volume") or 0)
    if risk_pct > 2.0 or stop_loss is None:
        return {"stance": "conservative", "verdict": "reduce",
                "maxVolume": round(requested * 0.5, 6),
                "rationale": f"High per-trade risk ({risk_pct:.1f}%) or missing stop loss — halving size",
                "confidence": 0.85}
    return {"stance": "conservative", "verdict": "approve",
            "maxVolume": requested,
            "rationale": f"Risk within conservative tolerance (risk {risk_pct:.1f}%, notional {notional_pct:.1f}%)",
            "confidence": 0.8}


def NEUTRAL_OFFICER(context):
    notional_pct, risk_pct = _pct(context)
    if risk_pct > 5.0 or notional_pct > 30.0:
        return {"stance": "neutral", "verdict": "reject",
                "maxVolume": 0.0,
                "rationale": f"Exposure exceeds neutral limits (risk {risk_pct:.1f}% / notional {notional_pct:.1f}%)",
                "confidence": 0.9}
    requested = float(context.get("volume") or 0)
    if risk_pct > 3.0:
        return {"stance": "neutral", "verdict": "reduce",
                "maxVolume": round(requested * 0.75, 6),
                "rationale": f"Elevated risk ({risk_pct:.1f}%) — trimming to 75% of requested size",
                "confidence": 0.8}
    return {"stance": "neutral", "verdict": "approve",
            "maxVolume": requested,
            "rationale": f"Risk within neutral tolerance (risk {risk_pct:.1f}%, notional {notional_pct:.1f}%)",
            "confidence": 0.8}


def resolve_debate(votes, requested):
    """Resolve officer votes -> single gate verdict (conservative resolution)."""
    requested = float(requested or 0)
    max_volume = requested
    blockers = []
    reduce_reasons = []
    for v in votes:
        verdict = v.get("verdict")
        if verdict == "reject":
            blockers.append({"stance": v.get("stance"), "rationale": v.get("rationale")})
        elif verdict == "reduce":
            max_volume = min(max_volume, float(v.get("maxVolume") or requested))
            reduce_reasons.append({"stance": v.get("stance"), "rationale": v.get("rationale")})

    if blockers:
        return {
            "approved": False,
            "verdict": "reject",
            "maxVolume": 0.0,
            "reason": "; ".join(b.get("rationale") or b.get("stance") or "risk-debate" for b in blockers),
            "blockers": blockers,
            "reduceReasons": [],
            "officers": votes,
        }
    if max_volume <= 0:
        return {
            "approved": False,
            "verdict": "reject",
            "maxVolume": 0.0,
            "reason": "risk-debate reduced position to zero",
            "blockers": [],
            "reduceReasons": reduce_reasons,
            "officers": votes,
        }
    if max_volume < requested - 1e-9:
        return {
            "approved": True,
            "verdict": "reduce",
            "maxVolume": round(max_volume, 6),
            "requestedVolume": requested,
            "reason": "; ".join(r.get("rationale") or r.get("stance") or "risk-debate" for r in reduce_reasons),
            "blockers": [],
            "reduceReasons": reduce_reasons,
            "officers": votes,
        }
    return {
        "approved": True,
        "verdict": "approve",
        "maxVolume": requested,
        "requestedVolume": requested,
        "reason": "All risk officers approve",
        "blockers": [],
        "reduceReasons": [],
        "officers": votes,
    }

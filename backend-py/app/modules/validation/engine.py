"""Market Validation Engine (Batch 10).

6 validation checks with weights and blocking flags:
  1. NewsValidation       25%  BLOCKING
  2. TechnicalValidation  15%  non-blocking
  3. SMCValidation        10%  non-blocking
  4. MacroValidation      10%  non-blocking
  5. MarketValidation     15%  BLOCKING (for spread)
  6. RiskValidation       25%  BLOCKING

Hard validation gates are separate from soft scores. A high AI confidence
score must NEVER override a hard blocker.
"""
import time

from ...foundation.logger import logger

OVERALL_SCORE_AUTO_EXECUTE = 0.70

HARD_BLOCKERS = [
    "unverified_news",
    "stale_news",
    "stale_market_data",
    "market_closed",
    "abnormal_spread",
    "insufficient_liquidity",
    "missing_broker_spec",
    "risk_engine_rejection",
    "capital_protection_active",
    "duplicate_execution_key",
    "model_output_schema_failure",
    "contradictory_official_source",
    "execution_provider_unhealthy",
]

CHECK_DEFS = [
    {"id": "news", "label": "News Validation", "weight": 0.25, "blocking": True},
    {"id": "technical", "label": "Technical Validation", "weight": 0.15, "blocking": False},
    {"id": "smc", "label": "SMC Validation", "weight": 0.10, "blocking": False},
    {"id": "macro", "label": "Macro Validation", "weight": 0.10, "blocking": False},
    {"id": "market", "label": "Market Validation", "weight": 0.15, "blocking": True},
    {"id": "risk", "label": "Risk Validation", "weight": 0.25, "blocking": True},
]


class ValidationEngine:
    def __init__(self):
        self.hard_blockers = []

    # ---- Individual checks ----
    def check_news(self, context):
        """25% BLOCKING. verified, source tier >= min, trust >= 0.6, not dup/fake."""
        news = context.get("news") or {}
        score = 0.0
        reasons = []
        if news.get("verified"):
            score += 0.5
        else:
            reasons.append("news not verified")
        tier = news.get("sourceTier", 4)
        min_tier = news.get("minSourceTier", 3)
        if tier <= min_tier:
            score += 0.25
        else:
            reasons.append(f"source tier {tier} below min {min_tier}")
        if (news.get("trust") or 0) >= 0.6:
            score += 0.25
        else:
            reasons.append(f"source trust {(news.get('trust') or 0):.2f} < 0.6")
        if news.get("isDuplicate"):
            reasons.append("duplicate news")
            score = min(score, 0.2)
        if news.get("isFake"):
            reasons.append("fake news")
            score = min(score, 0.1)
        return {"check": "news", "score": score, "blocking": True, "passed": score >= 0.7 and not reasons, "reasons": reasons}

    def check_technical(self, context):
        """15% non-blocking. structure supports, no contradiction, MTF alignment."""
        tech = context.get("technical") or {}
        score = 0.0
        reasons = []
        if tech.get("structureSupported"):
            score += 0.5
        else:
            reasons.append("structure does not support")
        if not tech.get("contradiction"):
            score += 0.25
        else:
            reasons.append("technical contradiction")
        if tech.get("mtfAligned"):
            score += 0.25
        else:
            reasons.append("MTF not aligned")
        return {"check": "technical", "score": score, "blocking": False, "passed": score >= 0.5, "reasons": reasons}

    def check_smc(self, context):
        """10% non-blocking. execution zone exists, quality >= 0.5, not mitigated."""
        smc = context.get("smc") or {}
        score = 0.0
        reasons = []
        if smc.get("executionZone"):
            score += 0.4
        else:
            reasons.append("no execution zone")
        if (smc.get("zoneQuality") or 0) >= 0.5:
            score += 0.3
        else:
            reasons.append(f"zone quality {(smc.get('zoneQuality') or 0):.2f} < 0.5")
        if not smc.get("mitigated"):
            score += 0.3
        else:
            reasons.append("zone mitigated")
        return {"check": "smc", "score": score, "blocking": False, "passed": score >= 0.5, "reasons": reasons}

    def check_macro(self, context):
        """10% non-blocking. not weekend, not low liquidity, no conflicting events."""
        macro = context.get("macro") or {}
        score = 0.0
        reasons = []
        if not macro.get("weekend"):
            score += 0.4
        else:
            reasons.append("weekend")
        if not macro.get("lowLiquidity"):
            score += 0.3
        else:
            reasons.append("low liquidity")
        if not macro.get("conflictingEvents"):
            score += 0.3
        else:
            reasons.append("conflicting economic events")
        return {"check": "macro", "score": score, "blocking": False, "passed": score >= 0.5, "reasons": reasons}

    def check_market(self, context):
        """15% BLOCKING for spread. cross-market aligned, spread acceptable, vol in range."""
        market = context.get("market") or {}
        score = 0.0
        reasons = []
        if market.get("crossMarketAligned"):
            score += 0.4
        else:
            reasons.append("cross-market divergence")
        max_spread = market.get("maxSpreadPips") or 3
        if (market.get("spreadPips") or 0) <= max_spread:
            score += 0.3
        else:
            reasons.append(f"spread {market.get('spreadPips')} > max {max_spread}")
        if market.get("volatilityInRange"):
            score += 0.3
        else:
            reasons.append("volatility out of range")
        return {"check": "market", "score": score, "blocking": True, "passed": score >= 0.5 and not reasons, "reasons": reasons}

    def check_risk(self, context):
        """25% BLOCKING. daily/weekly limits, position count, margin, consecutive losses."""
        risk = context.get("risk") or {}
        score = 0.0
        reasons = []
        if not risk.get("dailyLimitReached"):
            score += 0.3
        else:
            reasons.append("daily loss limit reached")
        if not risk.get("weeklyLimitReached"):
            score += 0.2
        else:
            reasons.append("weekly loss limit reached")
        if not risk.get("maxPositionsReached"):
            score += 0.2
        else:
            reasons.append("max positions reached")
        if not risk.get("marginLow"):
            score += 0.15
        else:
            reasons.append("margin too low")
        if not risk.get("consecutiveLossesReached"):
            score += 0.15
        else:
            reasons.append("consecutive losses reached")
        return {"check": "risk", "score": score, "blocking": True, "passed": score >= 0.6 and not reasons, "reasons": reasons}

    # ---- Hard blockers ----
    def raise_hard_blocker(self, blocker, detail):
        if blocker not in HARD_BLOCKERS:
            return
        if blocker not in self.hard_blockers:
            self.hard_blockers.append(blocker)
        logger.warn(f"HARD BLOCKER: {blocker} — {detail}")

    def clear_hard_blocker(self, blocker):
        if blocker in self.hard_blockers:
            self.hard_blockers.remove(blocker)

    def check_hard_blockers(self, context=None):
        context = context or {}
        active = list(self.hard_blockers)
        # dynamic hard blockers from context
        if context.get("staleNews"):
            active.append("stale_news")
        if context.get("staleMarketData"):
            active.append("stale_market_data")
        if context.get("marketClosed"):
            active.append("market_closed")
        if context.get("abnormalSpread"):
            active.append("abnormal_spread")
        if context.get("capitalProtectionActive"):
            active.append("capital_protection_active")
        if context.get("duplicateExecutionKey"):
            active.append("duplicate_execution_key")
        if context.get("schemaFailure"):
            active.append("model_output_schema_failure")
        return {"blocked": len(active) > 0, "blockers": sorted(set(active))}

    # ---- Full evaluation ----
    def evaluate(self, context):
        results = [
            self.check_news(context),
            self.check_technical(context),
            self.check_smc(context),
            self.check_macro(context),
            self.check_market(context),
            self.check_risk(context),
        ]
        weighted = sum(r["score"] * next(c["weight"] for c in CHECK_DEFS if c["id"] == r["check"]) for r in results)
        overall = round(weighted, 4)
        hard = self.check_hard_blockers(context)
        blocking_failed = [r for r in results if r["blocking"] and not r["passed"]]
        can_execute = overall >= OVERALL_SCORE_AUTO_EXECUTE and not hard["blocked"] and len(blocking_failed) == 0
        mode = "auto-execute" if can_execute else ("analysis-only" if (overall < OVERALL_SCORE_AUTO_EXECUTE or hard["blocked"]) else "suggest")
        return {
            "overall_score": overall,
            "results": results,
            "hard_blockers": hard,
            "blocking_failed": [r["check"] for r in blocking_failed],
            "can_auto_execute": can_execute,
            "mode": mode,
            "timestamp": int(time.time() * 1000),
        }


validation_engine = ValidationEngine()


def init_validation_engine():
    logger.info("Market Validation Engine initialized (6 checks + hard blockers)")
    return validation_engine

"""Institutional PRO Intelligence Agent (additive, custom pool).

Wires the PRO / institutional data sources into the AI decision pipeline as ONE
directional vote. The agent fetches real forward-looking and smart-money data —
Prediction Markets (crowd probability), CFTC Commitment of Traders, Fixed Income
yield-curve regime — and converts them into a deterministic signal that votes in
the consensus as a capped custom agent (``custom-pro-institutional``, weight
0.10). The core 80/20 formula, the technical execution gate and the risk veto
are untouched.

Graceful degradation: every source is fetched inside its own try/except and a
source that is unreachable, misconfigured or purely simulated is skipped rather
than trusted. If no real source remains usable the agent returns a clean
``DATA_INSUFFICIENT`` abstention — it never crashes the pipeline and never
votes on fabricated data.
"""
from ....foundation.logger import logger
from ...fixedincome import service as fixedincome_service
from ...institutional_flow import engine as institutional_engine
from ...prediction_markets import engine as prediction_engine
from ..agents.base import AgentResult, clamp01

AGENT_ID = "custom-pro-institutional"
AGENT_NAME = "InstitutionalProAgent"
AGENT_WEIGHT = 0.10
NEUTRAL_BAND = 0.20

# Symbol -> CFTC contract asset name for COT positioning.
_SYMBOL_ASSET = {
    "XAUUSD": "gold",
    "XAGUSD": "silver",
    "USOIL": "crude",
    "UKOIL": "crude",
    "EURUSD": "eurusd",
    "GBPUSD": "gbpusd",
    "USDJPY": "jpyusd",
    "AUDUSD": "audusd",
    "USDCAD": "cadusd",
    "NZDUSD": "nzdusd",
    "BTCUSD": "bitcoin",
    "ETHUSD": "ethereum",
}


def _asset_for_symbol(symbol):
    return _SYMBOL_ASSET.get(str(symbol or "").upper(), "gold")


def _prediction_markets_signal():
    """Crowd-probability signal from Polymarket (real, no API key).

    Returns ``(score, used, notes)`` with score in [-1, 1] relative to the
    traded symbol (XAUUSD): recession / inflation odds and Fed *cut* odds are
    gold-positive; Fed *hike* odds are gold-negative.
    """
    try:
        snap = prediction_engine.macro_overview(limit_per_topic=2)
    except Exception as exc:  # noqa: BLE001 - optional source
        logger.warn(f"pro agent: prediction-markets fetch failed: {exc}")
        return 0.0, 0, []
    score = 0.0
    used = 0
    notes = []
    for group in snap.get("groups") or []:
        topic = str(group.get("topic") or "").lower()
        markets = [m for m in (group.get("markets") or []) if not m.get("closed")]
        if not markets:
            continue
        question = str(markets[0].get("question") or "").lower()
        prob = markets[0].get("probability")
        if prob is None:
            continue
        prob = float(prob)
        if "recession" in topic or "recession" in question:
            # Elevated recession risk adds a safe-haven bid; a LOW recession
            # read is only the absence of a bid, not a sell signal.
            if prob > 0.5:
                score += (prob - 0.5) * 2.0
                used += 1
                notes.append(f"recession odds {prob:.2f}")
            else:
                notes.append(f"recession odds low ({prob:.2f})")
        elif "inflation" in topic or "inflation" in question:
            if prob > 0.5:
                score += (prob - 0.5) * 2.0
                used += 1
                notes.append(f"inflation odds {prob:.2f}")
            else:
                notes.append(f"inflation odds low ({prob:.2f})")
        elif any(k in question for k in ("cut", "lower", "ease")):
            score += (prob - 0.5) * 2.0  # dovish expectation -> gold bid
            used += 1
            notes.append(f"Fed cut odds {prob:.2f}")
        elif any(k in question for k in ("hike", "raise", "increase")):
            score -= (prob - 0.5) * 2.0  # hawkish expectation -> gold drag
            used += 1
            notes.append(f"Fed hike odds {prob:.2f}")
        # Unclear wording -> no directional read, skip silently.
    return max(-1.0, min(1.0, score)), used, notes


def _fixed_income_signal():
    """Yield-curve regime signal from FRED (only when live data present)."""
    try:
        curve = fixedincome_service.get_treasury_curve()
    except Exception as exc:  # noqa: BLE001 - optional source
        logger.warn(f"pro agent: fixed-income fetch failed: {exc}")
        return 0.0, 0, []
    if str(curve.get("source") or "") == "simulator":
        # FRED key missing -> fabricated curve; never vote on simulated yields.
        return 0.0, 0, []
    spread = (curve.get("spreads") or {}).get("2s10s")
    if spread is None:
        return 0.0, 0, []
    score = 0.0
    if spread < 0:
        score = 1.0  # inverted curve -> recession risk -> gold bid
    elif spread < 0.5:
        score = 0.3  # flattening -> mild caution
    else:
        score = -0.3  # steep/normal -> risk-on -> mild gold drag
    return score, 1, [f"2s10s {spread:.2f} {'inverted' if spread < 0 else 'flat' if spread < 0.5 else 'steep'}"]


def _cot_signal(symbol):
    """CFTC Commitment of Traders positioning (real public endpoint only)."""
    asset = _asset_for_symbol(symbol)
    try:
        res = institutional_engine.cot(asset)
    except Exception as exc:  # noqa: BLE001 - optional source
        logger.warn(f"pro agent: COT fetch failed: {exc}")
        return 0.0, 0, []
    if not res.get("available") or str(res.get("source") or "") != "cftc":
        # CFTC unreachable -> simulated COT; never vote on fabricated positioning.
        return 0.0, 0, []
    report = res.get("report") or {}
    bias = str(report.get("bias") or "").lower()
    net = report.get("netNonCommercial")
    score = 0.0
    if bias == "bullish" or (net is not None and net > 0):
        score = 1.0
    elif bias == "bearish" or (net is not None and net < 0):
        score = -1.0
    if score == 0.0:
        return 0.0, 0, []
    return score, 1, [f"COT {asset} {'long' if score > 0 else 'short'}-biased"]


class InstitutionalProAgent:
    id = AGENT_ID
    name = AGENT_NAME
    weight = AGENT_WEIGHT

    async def run(self, context=None):
        context = context or {}
        symbol = context.get("symbol") or "XAUUSD"

        signals = []
        for label, fetcher in (
            ("predictionMarkets", _prediction_markets_signal),
            ("fixedIncome", _fixed_income_signal),
            ("cot", lambda: _cot_signal(symbol)),
        ):
            try:
                score, used, notes = fetcher()
            except Exception as exc:  # noqa: BLE001 - one source must never break others
                logger.warn(f"pro agent: {label} failed: {exc}")
                continue
            if used:
                signals.append({"source": label, "score": round(score, 3), "notes": notes})

        if not signals:
            return AgentResult(
                self.id, self.name, self.weight, direction="neutral", confidence=0.0,
                abstention="DATA_INSUFFICIENT",
                reasoning="No live PRO/institutional data available (all sources unreachable or simulated)",
                data={"sources": [], "dataAvailable": 0},
            )

        net = sum(s["score"] for s in signals) / len(signals)
        direction = "neutral"
        if net > NEUTRAL_BAND:
            direction = "buy"
        elif net < -NEUTRAL_BAND:
            direction = "sell"
        confidence = clamp01(min(0.9, abs(net) + 0.15))
        detail = ", ".join(n for s in signals for n in s["notes"]) or "mixed"
        return AgentResult(
            self.id, self.name, self.weight,
            direction=direction,
            confidence=confidence,
            reasoning=f"PRO net {round(net, 3)} from {len(signals)} source(s): {detail}",
            abstention="TRADE",
            data={
                "net": round(net, 3),
                "dataAvailable": len(signals),
                "sources": signals,
            },
        )

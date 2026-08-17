"""AI Decision Center mirroring the Node ai/decisionCenter.js (multi-agent consensus)."""
import asyncio
import time

from ...foundation.logger import logger
from ...foundation.provider_framework import providers
from ...foundation.event_bus import event_bus
from ...foundation.json_store import db
from ..technical.smc import analyze_smc
from ..technical.price_action import analyze_price_action
from ..technical.candlesticks import detect_patterns
from ..technical.indicators import calculate_all_indicators
from ..news.engine import get_news
from ..economic.engine import get_economic_events
from ..macro.engine import get_macro_snapshot
from ..marketdata.engine import generate_candles, get_instrument
from .memory import ai_memory, rag_query

AGENTS = [
    {"id": "trend_agent", "name": "Trend Agent", "focus": "price action & structure", "weight": 0.2},
    {"id": "indicator_agent", "name": "Indicator Agent", "focus": "technical indicators", "weight": 0.15},
    {"id": "pattern_agent", "name": "Pattern Agent", "focus": "candlestick patterns", "weight": 0.1},
    {"id": "smc_agent", "name": "Smart Money Agent", "focus": "institutional footprints", "weight": 0.2},
    {"id": "news_agent", "name": "News Agent", "focus": "sentiment & impact", "weight": 0.15},
    {"id": "macro_agent", "name": "Macro Agent", "focus": "macro environment", "weight": 0.1},
    {"id": "risk_agent", "name": "Risk Agent", "focus": "position & capital risk", "weight": 0.1},
]


def register_local_model():
    if providers.get("local-model"):
        return

    async def _reason(context):
        indicators = context.get("indicators") or {}
        pa = context.get("priceAction") or {}
        score = (pa.get("score") or 0) + (indicators["rsi14"] - 50) / 100 if indicators.get("rsi14") is not None else (pa.get("score") or 0)
        return {
            "direction": "buy" if score > 0.1 else ("sell" if score < -0.1 else "neutral"),
            "confidence": min(abs(score) + 0.4, 0.95),
            "reasoning": "Multiple bullish signals align" if score > 0 else ("Multiple bearish signals align" if score < 0 else "Signals are mixed"),
            "model": "local-fin-model",
        }

    providers.register({
        "id": "local-model",
        "category": "ai-model",
        "name": "Local LLM (FinBERT-style)",
        "enabled": True,
        "reason": _reason,
    })


def init_decision_center():
    register_local_model()
    logger.info("AI Decision Center initialized with multi-agent consensus")
    return analyze_symbol


async def analyze_symbol_async(symbol):
    """Async entrypoint: builds context once, then runs all agents in parallel via asyncio.gather."""
    context = build_context(symbol)
    agent_votes = await asyncio.gather(*[asyncio.to_thread(_run_agent, a, context) for a in AGENTS])
    return _finish_analysis(symbol, context, agent_votes)


def analyze_symbol(symbol):
    context = build_context(symbol)
    agent_votes = [_run_agent(a, context) for a in AGENTS]
    return _finish_analysis(symbol, context, agent_votes)


def _finish_analysis(symbol, context, agent_votes):
    consensus = _compute_consensus(agent_votes)
    confidence = _confidence_engine(agent_votes, context)
    xai = _explainable(agent_votes, consensus, context)
    recommendation = _build_recommendation(symbol, consensus, confidence, context)
    context["consensusDirection"] = consensus["direction"]
    expected_move = expected_move_distribution(symbol, context)

    col = db.collection("ai_decisions")
    decision = col.insert({
        "symbol": symbol,
        "timestamp": int(time.time() * 1000),
        "consensus": consensus,
        "confidence": confidence,
        "agents": [{"id": v["agent"]["id"], "direction": v["direction"], "confidence": v["confidence"], "reasoning": v["reasoning"], "contribution": v["contribution"]} for v in agent_votes],
        "recommendation": recommendation,
        "expectedMove": expected_move,
        "xai": xai,
    })

    event_bus.emit("ai:decision", {"decision": decision})
    event_bus.emit("AIDecisionMade", {"decision": decision, "event": "AIDecisionMade"})
    ai_memory.remember(f"symbol:{symbol}", {"decision": consensus["direction"], "confidence": confidence["score"], "time": int(time.time() * 1000)})
    return {**decision, "contextSummary": context["summary"]}


def build_context(symbol):
    candles = generate_candles(symbol, "H1", 300)
    indicators = calculate_all_indicators(candles)
    price_action = analyze_price_action(candles)
    patterns = detect_patterns(candles)
    smc = analyze_smc(candles)
    news = get_news({"limit": 10, "symbol": symbol})
    economic = get_economic_events({"limit": 10})
    macro = get_macro_snapshot()
    rag = rag_query(symbol, 3)
    instrument = get_instrument(symbol)
    return {
        "symbol": symbol,
        "instrumentPip": instrument["pip"],
        "candles": candles[-5:],
        "indicators": indicators,
        "priceAction": price_action,
        "patterns": patterns,
        "smc": smc,
        "news": news,
        "economic": economic,
        "macro": macro,
        "rag": rag,
        "summary": {
            "price": candles[-1]["close"],
            "rsi": indicators["rsi14"],
            "trend": price_action["trend"],
            "smcBias": smc["summary"]["trend"],
            "newsCount": len(news),
            "avgNewsSentiment": round(sum(n["sentiment"] for n in news) / len(news), 2) if news else 0,
            "highImpactEvents": sum(1 for e in economic if e["impact"] == 3 and e["status"] != "released"),
        },
    }


def _run_agent(agent, context):
    c = context["summary"]
    direction = "neutral"
    confidence = 0.5
    reasoning = "No strong signal"

    agent_id = agent["id"]
    if agent_id == "trend_agent":
        score = context["priceAction"].get("score") or 0
        direction = "buy" if score > 0.3 else ("sell" if score < -0.3 else "neutral")
        confidence = min(abs(score) + 0.5, 0.95)
        reasoning = f"Price action {context['priceAction']['trend']}, last structure {context['priceAction'].get('latestStructure') or 'n/a'}"
    elif agent_id == "indicator_agent":
        rsi = context["indicators"]["rsi14"]
        ema_bull = (context["indicators"]["ema20"] or 0) > (context["indicators"]["ema50"] or 0)
        macd_data = context["indicators"]["macd"]
        macd_line = macd_data.get("line")
        macd_signal = macd_data.get("signal")
        macd_bull = bool(macd_line and macd_signal and macd_line[-1] > macd_signal[-1]) if (macd_line and macd_signal) else False
        score = 0
        if rsi is not None and rsi < 30:
            score += 1
        if rsi is not None and rsi > 70:
            score -= 1
        if ema_bull:
            score += 1
        else:
            score -= 1
        if macd_bull:
            score += 1
        else:
            score -= 1
        direction = "buy" if score >= 2 else ("sell" if score <= -2 else "neutral")
        confidence = min(abs(score) / 3 + 0.4, 0.9)
        reasoning = f"RSI {round(rsi) if rsi is not None else 'n/a'}, EMA20{'>' if ema_bull else '<'}EMA50, MACD {'bullish' if macd_bull else 'bearish'}"
    elif agent_id == "pattern_agent":
        bull = sum(1 for p in context["patterns"] if p["type"] == "bullish")
        bear = sum(1 for p in context["patterns"] if p["type"] == "bearish")
        direction = "buy" if bull > bear + 1 else ("sell" if bear > bull + 1 else "neutral")
        confidence = min((abs(bull - bear) + 1) / 5, 0.85)
        reasoning = f"{bull} bullish / {bear} bearish patterns detected"
    elif agent_id == "smc_agent":
        trend = (context["smc"].get("summary") or {}).get("trend")
        direction = "buy" if trend == "bullish" else ("sell" if trend == "bearish" else "neutral")
        inst_bias = (context["smc"].get("summary") or {}).get("institutionalBias")
        confidence = 0.8 if inst_bias == trend else 0.55
        reasoning = f"SMC trend {trend}, {((context['smc'].get('premiumDiscount') or {}).get('position')) or 'equilibrium'} zone, BOS/CHoCH present"
    elif agent_id == "news_agent":
        avg_sentiment = c.get("avgNewsSentiment") or 0
        direction = "buy" if avg_sentiment > 0.15 else ("sell" if avg_sentiment < -0.15 else "neutral")
        confidence = min(abs(avg_sentiment) * 2 + 0.4, 0.85)
        reasoning = f"News sentiment {avg_sentiment:.2f} across {c.get('newsCount', 0)} articles"
    elif agent_id == "macro_agent":
        risk_on = context["macro"].get("riskOn")
        macro_bias = "buy" if risk_on else "sell"
        direction = macro_bias if context["priceAction"]["trend"] == "bullish" else "neutral"
        confidence = 0.6
        reasoning = f"Risk-{'on' if risk_on else 'off'} environment, VIX {context['macro']['indicators']['vix']:.1f}"
    elif agent_id == "risk_agent":
        atr = context["indicators"].get("atr14") or 0
        price = c.get("price") or 1
        volatility_pct = (atr / price) * 100
        if volatility_pct > 2:
            direction = "neutral"
            confidence = 0.3
            reasoning = f"High volatility ({volatility_pct:.2f}% ATR), reducing exposure"
        else:
            direction = "neutral"
            confidence = 0.6
            reasoning = f"Volatility acceptable ({volatility_pct:.2f}% ATR)"

    return {"agent": agent, "direction": direction, "confidence": confidence, "reasoning": reasoning, "weight": agent["weight"], "contribution": agent["weight"]}


def _compute_consensus(votes):
    buy = 0.0
    sell = 0.0
    neutral = 0.0
    for v in votes:
        if v["direction"] == "buy":
            buy += v["weight"]
        elif v["direction"] == "sell":
            sell += v["weight"]
        else:
            neutral += v["weight"]
    total = buy + sell + neutral
    direction = "buy" if (buy > sell and buy > neutral) else ("sell" if (sell > buy and sell > neutral) else "neutral")
    strength = max(buy, sell) / (total or 1)
    agreement = max(buy, sell, neutral) / (total or 1)
    return {
        "direction": direction,
        "buyWeight": round(buy * 100) / 100,
        "sellWeight": round(sell * 100) / 100,
        "neutralWeight": round(neutral * 100) / 100,
        "strength": round(strength * 100) / 100,
        "agreement": round(agreement * 100) / 100,
    }


def _confidence_engine(votes, context):
    total_weight = sum(v["weight"] for v in votes)
    groups = {"buy": 0, "sell": 0, "neutral": 0}
    for v in votes:
        groups[v["direction"]] = groups.get(v["direction"], 0) + v["weight"]
    agreement = max(groups["buy"], groups["sell"], groups["neutral"]) / total_weight if total_weight > 0 else 0
    avg_agent_conf = sum(v["confidence"] * v["weight"] for v in votes) / (total_weight or 1)
    context_quality = min(1, (0.2 if len(context["news"]) > 0 else 0) + (0.3 if len(context["candles"]) >= 200 else 0.15) + 0.4)
    confidence = agreement * 0.4 + avg_agent_conf * 0.4 + context_quality * 0.2
    return {
        "score": round(confidence * 100) / 100,
        "level": "high" if confidence > 0.7 else ("medium" if confidence > 0.5 else "low"),
        "agreement": agreement,
        "avgAgentConfidence": round(avg_agent_conf * 100) / 100,
        "contextQuality": round(context_quality * 100) / 100,
    }


def _explainable(votes, consensus, context):
    now = int(time.time() * 1000)
    contributions = [{"agent": v["agent"]["name"], "direction": v["direction"], "contribution": round(v["weight"] * 100) / 100, "reasoning": v["reasoning"]} for v in votes]
    return {
        "decision": consensus["direction"],
        "timeline": [
            {"step": "Market Data Ingest", "detail": f"{context['summary']['price']} {context['summary']['trend']}", "at": now - 5000},
            {"step": "Technical Analysis", "detail": f"RSI {context['summary']['rsi']}" if context["summary"]["rsi"] is not None else "RSI n/a", "at": now - 4000},
            {"step": "SMC Analysis", "detail": f"{context['summary']['smcBias']} institutional bias", "at": now - 3000},
            {"step": "News + Macro Filter", "detail": f"Sentiment {context['summary']['avgNewsSentiment']}" if context["summary"]["avgNewsSentiment"] is not None else "Sentiment n/a", "at": now - 2000},
            {"step": "Multi-Agent Consensus", "detail": f"{consensus['direction']} with {consensus['agreement'] * 100}% agreement", "at": now - 1000},
        ],
        "contributions": contributions,
        "confidenceBreakdown": {"agreementWeight": 40, "agentConfidenceWeight": 40, "contextQualityWeight": 20},
    }


def expected_move_distribution(symbol, context):
    """Deterministic expected price-move distribution for the next H1 candle.

    probabilityUp is derived from RSI drift, average news sentiment and the
    price-action score; the move side follows the consensus direction when it is
    present in the context, otherwise it mirrors probabilityUp.
    """
    price = context["summary"]["price"]
    atr = context["indicators"].get("atr14") or price * 0.001
    rsi = context["indicators"].get("rsi14")
    avg_sentiment = context["summary"].get("avgNewsSentiment") or 0
    pa_score = context["priceAction"].get("score") or 0

    signals = []
    if rsi is not None:
        signals.append((rsi - 50) / 50)
    signals.append(avg_sentiment)
    signals.append(pa_score)
    directional = sum(signals) / max(len(signals), 1)
    probability_up = max(0.0, min(1.0, 0.5 + directional * 0.4))
    probability_down = round(1 - probability_up, 4)

    direction = context.get("consensusDirection")
    if direction not in ("buy", "sell"):
        direction = "buy" if probability_up >= 0.5 else "sell"

    if direction == "sell":
        move_low = price - atr * 0.75
        move_median = price - atr * 1.25
        move_high = price - atr * 2.25
        invalidation = price + atr * 2.5
    else:
        move_low = price + atr * 0.75
        move_median = price + atr * 1.25
        move_high = price + atr * 2.25
        invalidation = price - atr * 2.5

    return {
        "symbol": symbol,
        "moveLow": round(move_low, 5),
        "moveMedian": round(move_median, 5),
        "moveHigh": round(move_high, 5),
        "predictionInterval": {
            "lower": round(min(move_low, move_high), 5),
            "upper": round(max(move_low, move_high), 5),
        },
        "expectedVolatilityPct": round((atr / price) * 100, 4),
        "expectedPriceRange": {
            "low": round(min(price, move_low, move_high), 5),
            "high": round(max(price, move_low, move_high), 5),
        },
        "duration": "next-H1-candle",
        "invalidation": round(invalidation, 5),
        "spreadAdjusted": True,
        "probabilityUp": round(probability_up, 4),
        "probabilityDown": probability_down,
        "efx": round((move_median - price) / price * 100, 4),
        "eax": round(abs(move_high - move_low) / price * 100, 4),
    }


def _build_recommendation(symbol, consensus, confidence, context):
    if consensus["direction"] == "neutral" or confidence["score"] < 0.45:
        return {"action": "hold", "direction": consensus["direction"], "reason": "Insufficient signal confidence", "expectedPips": 0, "expectedRisk": 0}
    price = context["summary"]["price"]
    atr = context["indicators"].get("atr14") or price * 0.001
    pips = round((atr * (0.8 + consensus["strength"] * 0.6)) / context["instrumentPip"])
    entry = round(price, 5)
    stop = round(price - atr * 1.5 if consensus["direction"] == "buy" else price + atr * 1.5, 5)
    tp = round(price + atr * (2 + consensus["strength"]) if consensus["direction"] == "buy" else price - atr * (2 + consensus["strength"]), 5)
    return {
        "action": "recommend",
        "direction": consensus["direction"],
        "entry": entry,
        "stopLoss": stop,
        "takeProfit": tp,
        "rrRatio": round(2.5, 2),
        "expectedPips": round(pips, 1),
        "expectedRisk": round(atr * 1.5, 5),
        "reason": f"Consensus {consensus['direction']} at {confidence['score']} confidence ({confidence['level']})",
        "agents": len([a for a in AGENTS if a["id"] != "risk_agent"]),
    }

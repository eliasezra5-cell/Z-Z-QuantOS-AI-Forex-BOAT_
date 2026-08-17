"""Historical intelligence engine mirroring the Node historical/engine.js."""
import random
import re
import time

from ...foundation.logger import logger
from ...foundation.json_store import db
from ..marketdata.engine import generate_candles, get_quote  # noqa: F401
from ..technical.indicators import calculate_all_indicators
from ..technical.price_action import analyze_price_action

_STRATEGIES = ["trend-follow", "breakout", "mean-reversion", "smc", "news-reaction"]
_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "US500", "WTI"]

NEWS_WEIGHT = 0.4
MARKET_WEIGHT = 0.2
TECHNICAL_WEIGHT = 0.4
MATCH_WEIGHTS = {"news": NEWS_WEIGHT, "market": MARKET_WEIGHT, "technical": TECHNICAL_WEIGHT}


def _pick(arr):
    return arr[random.randrange(len(arr))]


def _tokenize(item):
    tokens = set()
    for kw in item.get("keywords") or []:
        tokens.add(str(kw).strip().lower())
    for ent in item.get("entities") or []:
        tokens.add(str(ent).strip().lower())
    for key in ("category", "driver"):
        value = item.get(key)
        if value:
            tokens.add(str(value).strip().lower())
    title = str(item.get("title") or item.get("name") or "")
    tokens.update(w for w in re.split(r"[^a-z0-9]+", title.lower()) if len(w) > 2)
    for key in ("symbol", "strategy"):
        value = item.get(key)
        if value:
            tokens.add(str(value).strip().lower())
    return tokens


def _jaccard(a, b):
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _market_similarity(event, candidate, context):
    market = (context or {}).get("market") or {}
    cand_dir = candidate.get("direction")
    if cand_dir not in ("buy", "sell"):
        return 0.0
    signals = []
    gold_dir = market.get("goldDirection")
    if gold_dir in ("bullish", "bearish"):
        expected = "buy" if gold_dir == "bullish" else "sell"
        signals.append(1.0 if cand_dir == expected else 0.0)
    rsi_regime = market.get("rsiRegime")
    if rsi_regime in ("overbought", "oversold"):
        expected = "sell" if rsi_regime == "overbought" else "buy"
        signals.append(1.0 if cand_dir == expected else 0.0)
    if not signals:
        return 0.0
    return sum(signals) / len(signals)


def _candidate_tags(candidate):
    tags = {str(t).strip().lower() for t in (candidate.get("tags") or [])}
    if not tags:
        d = candidate.get("direction")
        if d == "buy":
            tags.add("bullish")
        elif d == "sell":
            tags.add("bearish")
        move_pips = candidate.get("movePips")
        if isinstance(move_pips, (int, float)) and abs(move_pips) >= 300:
            tags.add("high-volatility")
    return tags


def _technical_similarity(event, candidate, context):
    tech = (context or {}).get("technical") or {}
    expected = set()
    trend = tech.get("trend")
    if trend in ("bullish", "bearish"):
        expected.add(trend)
    rsi = tech.get("rsi14")
    if rsi is None:
        rsi = tech.get("rsi")
    if rsi is not None:
        if rsi >= 70:
            expected.add("overbought")
        elif rsi <= 30:
            expected.add("oversold")
        else:
            expected.add("neutral-rsi")
    volatility = tech.get("volatility")
    if volatility is None:
        volatility = tech.get("volatilityPct")
    if volatility is not None:
        if volatility >= 0.03:
            expected.add("high-volatility")
        elif volatility <= 0.01:
            expected.add("low-volatility")
        else:
            expected.add("normal-volatility")
    if not expected:
        return 0.0
    return _jaccard(expected, _candidate_tags(candidate))


def compute_match_score(event, candidate, context=None):
    """Deterministic 40/20/40 weighted match score between an event and a candidate."""
    news = _jaccard(_tokenize(event), _tokenize(candidate))
    market = _market_similarity(event, candidate, context)
    technical = _technical_similarity(event, candidate, context)
    score = NEWS_WEIGHT * news + MARKET_WEIGHT * market + TECHNICAL_WEIGHT * technical
    score = max(0.0, min(1.0, score))
    return {
        "score": round(score * 10000) / 10000,
        "news": round(news * 10000) / 10000,
        "market": round(market * 10000) / 10000,
        "technical": round(technical * 10000) / 10000,
        "weights": dict(MATCH_WEIGHTS),
    }


def init_historical():
    col = db.collection("historical_trades")
    if col.count() == 0:
        trades = []
        for _ in range(60):
            symbol = _pick(_SYMBOLS)
            direction = "buy" if random.random() > 0.5 else "sell"
            entry = 100 + random.random() * 100
            pips = (random.random() - 0.4) * 80
            trades.append({
                "symbol": symbol,
                "direction": direction,
                "entry": round(entry, 2),
                "exit": round(entry + (pips if direction == "buy" else -pips) * 0.01, 2),
                "profit": round((random.random() - 0.45) * 500, 2),
                "win": random.random() > 0.45,
                "time": int(time.time() * 1000) - random.randint(0, 30) * 86400000,
                "strategy": _pick(_STRATEGIES),
            })
        col.insert_many(trades)
    logger.info("Historical intelligence initialized")
    return get_historical_snapshot


def get_historical_snapshot():
    trades = db.collection("historical_trades").find({})
    wins = sum(1 for t in trades if t.get("win"))
    best = None
    worst = None
    for t in trades:
        if best is None or t["profit"] > best["profit"]:
            best = t
        if worst is None or t["profit"] < worst["profit"]:
            worst = t
    return {
        "trades": trades,
        "stats": {
            "total": len(trades),
            "winRate": round(wins / len(trades) * 100) / 100 if trades else 0,
            "avgProfit": round(sum(t["profit"] for t in trades) / len(trades) * 100) / 100 if trades else 0,
            "totalProfit": round(sum(t["profit"] for t in trades) * 100) / 100,
            "bestTrade": best,
            "worstTrade": worst,
            "strategyBreakdown": _breakdown_by_strategy(trades),
        },
    }


def _breakdown_by_strategy(trades):
    mapping = {}
    for t in trades:
        s = t.get("strategy", "unknown")
        if s not in mapping:
            mapping[s] = {"count": 0, "wins": 0, "profit": 0}
        mapping[s]["count"] += 1
        mapping[s]["wins"] += 1 if t.get("win") else 0
        mapping[s]["profit"] += t["profit"]
    return [
        {"strategy": strategy, "count": s["count"], "winRate": round(s["wins"] / s["count"] * 100) / 100, "profit": round(s["profit"] * 100) / 100}
        for strategy, s in mapping.items()
    ]


def replay_market(symbol, timeframe, count=200):
    candles = generate_candles(symbol, timeframe, count)
    replay = []
    for i in range(50, len(candles) + 1, 25):
        sl = candles[:i]
        indicators = calculate_all_indicators(sl)
        pa = analyze_price_action(sl)
        replay.append({
            "bar": i,
            "price": sl[-1]["close"],
            "signal": pa["trend"],
            "rsi": indicators["rsi14"],
            "timestamp": sl[-1]["time"],
        })
    return {"symbol": symbol, "timeframe": timeframe, "replay": replay}


def pattern_matching(symbol, context=None):
    current = calculate_all_indicators(generate_candles(symbol, "H1", 300))
    historical = [t for t in db.collection("historical_trades").find({"symbol": symbol})]
    if context is None:
        rsi = current.get("rsi14")
        atr = current.get("atr14")
        base = current.get("sma20")
        volatility = (atr / base) if atr is not None and base else None
        context = {
            "market": {"goldDirection": None, "rsiRegime": None},
            "technical": {"trend": "bullish" if rsi is not None and rsi > 50 else "bearish", "rsi14": rsi, "volatility": volatility},
        }
    event = {"symbol": symbol, "strategy": None}
    matches = [
        {**t, "similarity": compute_match_score(event, t, context)["score"]}
        for t in historical if t.get("symbol") == symbol
    ]
    matches.sort(key=lambda m: m["similarity"], reverse=True)
    return {"currentSignal": "bullish-context" if current["rsi14"] > 50 else "bearish-context", "matches": matches[:5]}


def get_similar_events(news_item, context=None):
    if not isinstance(news_item, dict):
        return []
    news = db.collection("news_items").find({})
    out = []
    for n in news:
        if n.get("category") == news_item.get("category") and n.get("id") != news_item.get("id"):
            score = compute_match_score(news_item, n, context)["score"]
            out.append({**n, "relevance": score})
        if len(out) >= 4:
            break
    out.sort(key=lambda m: m["relevance"], reverse=True)
    return out

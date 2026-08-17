"""News intelligence engine mirroring the Node news/engine.js."""
import random
import threading
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...foundation.provider_framework import providers
from ..ai.memory import vector_store

NEWS_TEMPLATES = [
    {"title": "Fed officials signal patience on rate cuts as inflation remains sticky", "source": "Reuters", "category": "macro", "impact": 0.85, "sentiment": -0.2, "entities": ["Federal Reserve", "USD", "FOMC"]},
    {"title": "ECB holds rates steady, hints at easing in coming months", "source": "Bloomberg", "category": "central-banks", "impact": 0.7, "sentiment": 0.1, "entities": ["ECB", "EUR", "interest rates"]},
    {"title": "Crude oil climbs 2% as OPEC+ extends production cuts", "source": "CNBC", "category": "energy", "impact": 0.65, "sentiment": 0.6, "entities": ["OPEC", "WTI", "oil"]},
    {"title": "Bitcoin surges past resistance on ETF inflows", "source": "MarketWatch", "category": "crypto", "impact": 0.8, "sentiment": 0.8, "entities": ["BTC", "Bitcoin", "ETF"]},
    {"title": "Non-farm payrolls beat expectations, dollar strengthens", "source": "Investing.com", "category": "macro", "impact": 0.9, "sentiment": 0.3, "entities": ["USD", "NFP", "labor market"]},
    {"title": "Gold hits fresh record high as safe-haven demand rises", "source": "Reuters", "category": "precious-metals", "impact": 0.75, "sentiment": 0.7, "entities": ["Gold", "XAU", "XAUUSD"]},
    {"title": "Bank of Japan signals potential rate hike amid weak yen", "source": "Bloomberg", "category": "central-banks", "impact": 0.8, "sentiment": 0.4, "entities": ["BOJ", "JPY", "USDJPY"]},
    {"title": "Tech stocks rally as AI demand accelerates", "source": "CNBC", "category": "equities", "impact": 0.6, "sentiment": 0.7, "entities": ["Nasdaq", "AAPL", "AI"]},
    {"title": "Treasury yields ease after weak auction", "source": "MarketWatch", "category": "bonds", "impact": 0.55, "sentiment": 0.2, "entities": ["US10Y", "Treasury"]},
    {"title": "Retail sales data points to resilient consumer spending", "source": "Investing.com", "category": "macro", "impact": 0.7, "sentiment": 0.5, "entities": ["USD", "retail"]},
    {"title": "UK inflation falls more than expected, pound drops", "source": "Reuters", "category": "macro", "impact": 0.75, "sentiment": -0.3, "entities": ["GBP", "GBPUSD", "BoE"]},
    {"title": "Ethereum upgrade goes live, developers report smooth transition", "source": "CoinDesk", "category": "crypto", "impact": 0.5, "sentiment": 0.6, "entities": ["ETH", "Ethereum"]},
]

SOURCES = [
    {"id": "reuters", "name": "Reuters", "type": "website", "enabled": True, "priority": 1, "reliability": 0.98},
    {"id": "bloomberg", "name": "Bloomberg", "type": "website", "enabled": True, "priority": 1, "reliability": 0.97},
    {"id": "cnbc", "name": "CNBC", "type": "website", "enabled": True, "priority": 2, "reliability": 0.9},
    {"id": "marketwatch", "name": "MarketWatch", "type": "website", "enabled": True, "priority": 2, "reliability": 0.88},
    {"id": "investing", "name": "Investing.com", "type": "website", "enabled": True, "priority": 2, "reliability": 0.85},
    {"id": "fed", "name": "Federal Reserve", "type": "official", "enabled": True, "priority": 1, "reliability": 0.99},
    {"id": "ecb", "name": "European Central Bank", "type": "official", "enabled": True, "priority": 1, "reliability": 0.99},
    {"id": "boj", "name": "Bank of Japan", "type": "official", "enabled": True, "priority": 1, "reliability": 0.99},
    {"id": "imf", "name": "IMF", "type": "official", "enabled": True, "priority": 2, "reliability": 0.98},
    {"id": "bis", "name": "Bank for International Settlements", "type": "official", "enabled": True, "priority": 2, "reliability": 0.98},
    {"id": "x", "name": "X (Twitter)", "type": "social", "enabled": True, "priority": 3, "reliability": 0.6},
    {"id": "telegram", "name": "Telegram", "type": "social", "enabled": True, "priority": 3, "reliability": 0.65},
    {"id": "whatsapp", "name": "WhatsApp Channels", "type": "social", "enabled": False, "priority": 3, "reliability": 0.6},
    {"id": "discord", "name": "Discord", "type": "social", "enabled": True, "priority": 3, "reliability": 0.6},
    {"id": "reddit", "name": "Reddit", "type": "social", "enabled": True, "priority": 4, "reliability": 0.5},
    {"id": "youtube", "name": "YouTube", "type": "social", "enabled": True, "priority": 4, "reliability": 0.5},
    {"id": "rss", "name": "RSS Feeds", "type": "rss", "enabled": True, "priority": 2, "reliability": 0.8},
    {"id": "premium_api", "name": "Premium News APIs", "type": "api", "enabled": True, "priority": 1, "reliability": 0.95},
    {"id": "custom_api", "name": "Custom APIs", "type": "api", "enabled": False, "priority": 2, "reliability": 0.8},
]

BULLISH_KEYWORDS = ["surges", "rallies", "beats", "gains", "climbs", "record high", "strengthens", "demand rises", "rises"]
BEARISH_KEYWORDS = ["falls", "drops", "plunges", "slides", "slumps", "weak", "misses", "fears", "record low", "crisis", "drops"]
POSITIVE_KEYWORDS = ["gain", "grow", "surge", "jump", "beat", "strong", "rally", "climb", "raise", "boost", "optimism", "expand"]
NEGATIVE_KEYWORDS = ["fall", "drop", "decline", "cut", "miss", "weak", "slump", "fear", "crash", "warn", "risk", "concern", "selloff", "uncertainty"]
SENSATIONAL_WORDS = ["guaranteed", "urgent", "secret", "shocking", "insider", "to the moon", "100%"]

TRUST_WEIGHTS = {
    "source": 0.35,
    "verification": 0.25,
    "crossCheck": 0.20,
    "history": 0.10,
    "ai": 0.10,
}

CONFIDENCE_WEIGHTS = {
    "source": 0.30,
    "sentiment": 0.25,
    "verification": 0.15,
    "temporal": 0.15,
    "impact": 0.10,
    "entity": 0.05,
}

SOURCE_HISTORY_ACCURACY = {
    "Reuters": 0.9,
    "Bloomberg": 0.9,
    "CNBC": 0.8,
    "MarketWatch": 0.75,
    "Investing.com": 0.7,
    "CoinDesk": 0.7,
    "Federal Reserve": 0.95,
    "European Central Bank": 0.95,
    "Bank of Japan": 0.95,
    "IMF": 0.9,
    "Bank for International Settlements": 0.9,
    "X (Twitter)": 0.5,
    "Telegram": 0.55,
    "WhatsApp Channels": 0.5,
    "Discord": 0.55,
    "Reddit": 0.45,
    "YouTube": 0.45,
    "RSS Feeds": 0.7,
    "Premium News APIs": 0.85,
    "Custom APIs": 0.7,
}

EVENT_PATTERNS = [
    ("fomc", ["fomc", "federal reserve rate", "fed rate decision", "fed decision"]),
    ("cpi", ["cpi", "consumer price index", "inflation data", "inflation print", "pce inflation", "pce data"]),
    ("rate-decision", ["rate decision", "rate hike", "rate cut", "holds rates", "interest rate", "monetary policy"]),
    ("earnings", ["earnings", "quarterly result", "q1 ", "q2 ", "q3 ", "q4 ", "reports results", "profit report", "earnings call"]),
    ("geopolitics", ["war", "conflict", "sanction", "invasion", "attack", "geopolitical", "election", "protest", "escalat", "tension"]),
    ("release", ["release", "released", "report", "payrolls", "nfp", "gdp", "retail sales", "jobless", "print"]),
]

EVENT_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CNY", "CHF", "AUD", "CAD", "NZD", "BTC", "XAU", "XAG", "WTI", "OIL"}

EVENT_VENUES = [
    ("fomc", "Federal Reserve"),
    ("federal reserve", "Federal Reserve"),
    ("fed", "Federal Reserve"),
    ("ecb", "European Central Bank"),
    ("boj", "Bank of Japan"),
    ("boe", "Bank of England"),
    ("reserve bank of australia", "Reserve Bank of Australia"),
]


def _clamp01(value):
    """Clamp a numeric value to the [0, 1] range."""
    return max(0.0, min(1.0, float(value)))


def _cross_reference_count(item):
    """Number of independent sources corroborating an item, mirroring verify_news_item."""
    refs = item.get("crossReference")
    if isinstance(refs, list):
        return len(set(r for r in refs if r))
    return max(0, int(item.get("crossReferenceCount") or (1 if item.get("source") else 0)))


def _score_neutral_title(title):
    """Deterministic keyword/entity-based sentiment for neutral titles, scaled to [-1, 1]."""
    positive = sum(title.count(kw) for kw in POSITIVE_KEYWORDS)
    negative = sum(title.count(kw) for kw in NEGATIVE_KEYWORDS)
    delta = positive - negative
    return max(-1, min(1, delta * 0.25))


def infer_sentiment(title):
    """Infer deterministic sentiment in [-1, 1] from headline keyword signals."""
    t = str(title).lower()
    score = 0.0
    for kw in BULLISH_KEYWORDS:
        if kw in t:
            score += 0.4
    for kw in BEARISH_KEYWORDS:
        if kw in t:
            score -= 0.4
    if score == 0:
        score = _score_neutral_title(t)
    return max(-1, min(1, score))


def extract_keywords(title):
    stop = {"the", "a", "an", "as", "on", "in", "at", "of", "to", "for", "with", "after", "hits", "show", "set", "over", "data"}
    import re
    words = [w for w in re.split(r"[^a-z0-9]+", str(title).lower()) if len(w) > 3 and w not in stop]
    return words[:6]


def extract_entities(title):
    known = {
        "fed": "Federal Reserve", "federal reserve": "Federal Reserve", "fomc": "FOMC", "ecb": "ECB", "boj": "Bank of Japan", "boe": "Bank of England",
        "opec": "OPEC", "imf": "IMF", "usd": "US Dollar", "eur": "Euro", "gbp": "British Pound", "jpy": "Japanese Yen", "btc": "Bitcoin",
        "bitcoin": "Bitcoin", "eth": "Ethereum", "ethereum": "Ethereum", "gold": "Gold", "xauusd": "Gold", "wti": "WTI Crude", "oil": "Crude Oil",
        "nasdaq": "Nasdaq", "treasury": "US Treasury", "inflation": "Inflation", "etf": "Exchange Traded Fund", "apple": "Apple Inc.",
    }
    t = str(title).lower()
    out = []
    for k, v in known.items():
        if k in t:
            out.append(v)
        if len(out) >= 4:
            break
    return out


def _title_fingerprint(title):
    """Normalized title fingerprint: lowercase, stripped punctuation, sorted unique words."""
    import re
    words = [w for w in re.split(r"[^a-z0-9]+", str(title).lower()) if w]
    return " ".join(sorted(set(words)))


def detect_fake_news(item):
    """Deterministic fake-news risk [0, 1] from title and source red-flag signals."""
    title = str(item.get("title") or "")
    source = item.get("source")
    url = item.get("url")
    src = next((s for s in SOURCES if s["name"] == source), None)
    reliability = item.get("reliability")
    if reliability is None:
        reliability = src["reliability"] if src else 0.7
    reliability = float(reliability)

    risk = 0.0

    letters = [ch for ch in title if ch.isalpha()]
    if letters and sum(1 for ch in letters if ch.isupper()) / len(letters) > 0.6:
        risk += 0.3

    if title.count("!") >= 3:
        risk += 0.25

    low = title.lower()
    if any(w in low for w in SENSATIONAL_WORDS):
        risk += 0.3

    if not source or not url or reliability < 0.6:
        risk += 0.2

    source_type = (src or {}).get("type")
    impact = item.get("impact") or 0
    cross_ref = item.get("crossReference") or item.get("crossReferenceCount") or 0
    if source_type == "social" and impact > 0.8 and not cross_ref:
        risk += 0.25

    if risk == 0:
        risk = 0.1 * (1 - reliability) + 0.05
        if source_type == "official":
            risk = min(risk, 0.1)

    risk = min(risk, 0.95)
    return round(risk * 100) / 100


def detect_duplicate(item, existing_items=None):
    """Deterministic duplicate risk [0, 1] against a window of existing news items.

    Returns a (risk, matchedId) tuple; matchedId is set when an exact or near
    duplicate exists in the window.
    """
    existing_items = existing_items or []
    if not existing_items:
        return 0.0, None
    title = str(item.get("title") or "")
    fp = _title_fingerprint(title)
    kws = set(extract_keywords(title))
    best_risk = 0.0
    best_id = None
    for existing in existing_items:
        e_title = str(existing.get("title") or "")
        risk = 0.0
        if fp and _title_fingerprint(e_title) == fp:
            risk = 1.0
        else:
            e_kws = set(extract_keywords(e_title))
            union = kws | e_kws
            jaccard = (len(kws & e_kws) / len(union)) if union else 0.0
            if jaccard >= 0.8:
                risk = 0.9
            elif jaccard >= 0.6:
                risk = 0.6
            else:
                risk = jaccard * 0.6
            if existing.get("source") and existing.get("source") == item.get("source"):
                e_time = existing.get("time") or 0
                i_time = item.get("time") or 0
                if e_time and i_time and abs(e_time - i_time) <= 5 * 60 * 1000:
                    risk = min(1.0, risk + 0.3)
        if risk > best_risk:
            best_risk = risk
            best_id = existing.get("id") or existing.get("_id")
    return round(best_risk * 100) / 100, best_id


def verify_news_item(item):
    """Deterministic verification of a news item based on source type and risk signals."""
    src = next((s for s in SOURCES if s["name"] == item.get("source")), None)
    source_type = (src or {}).get("type")
    duplicate_risk = item.get("duplicateRisk")
    if duplicate_risk is None:
        duplicate_risk, _ = detect_duplicate(item)
    fake_news_risk = item.get("fakeNewsRisk")
    if fake_news_risk is None:
        fake_news_risk = detect_fake_news(item)

    cross_checked = item.get("sourcesCrossChecked")
    if cross_checked is None:
        refs = item.get("crossReference")
        if isinstance(refs, list):
            cross_checked = len(set(r for r in refs if r))
        else:
            cross_checked = item.get("crossReferenceCount") or (1 if item.get("source") else 0)
    cross_checked = max(0, int(cross_checked))

    evidence = []
    if source_type == "official":
        level = "official"
        verified = True
        evidence.append({"signal": "official-source", "detail": f"Source {item.get('source')} is an official channel"})
    elif duplicate_risk < 0.1 and cross_checked >= 2:
        level = "multi-source"
        verified = True
        evidence.append({"signal": "multi-source", "detail": f"{cross_checked} independent sources corroborate the report"})
    else:
        level = "single-source"
        verified = True
        evidence.append({"signal": "single-source", "detail": "No duplicate detected, relying on a single source"})

    if fake_news_risk > 0.5:
        verified = False
        level = "unverified"
        evidence.append({"signal": "fake-news-risk", "detail": f"Fake news risk {fake_news_risk:.2f} exceeds 0.5"})

    return {
        "verified": verified,
        "verificationLevel": level,
        "sourcesCrossChecked": cross_checked,
        "evidence": evidence,
    }


def _source_reliability(item, src):
    """0-1 source reliability from the item's explicit value or source mapping."""
    reliability = item.get("reliability")
    if reliability is None:
        reliability = src["reliability"] if src else 0.7
    return _clamp01(reliability)


def _verification_score(cross_checked, source_type, fake_news_risk=0.0):
    """0-1 verification score derived from the multi-source cross-reference count."""
    score = min(1.0, float(cross_checked) / 3.0)
    if source_type == "official":
        score = max(score, 0.85)
    if fake_news_risk > 0.5:
        score = min(score, 0.2)
    return _clamp01(score)


def _cross_check_score(cross_verified):
    """0-1 score from the cross-verified flag."""
    return 1.0 if cross_verified else 0.2


def _history_score(source):
    """0-1 historical accuracy of the source, defaulting to 0.8."""
    return _clamp01(SOURCE_HISTORY_ACCURACY.get(source, 0.8))


def _ai_score(item):
    """0-1 AI/NLP confidence (FinBERT-style) for the item, deterministically."""
    ai_conf = item.get("aiConfidence")
    if ai_conf is None:
        ai_block = item.get("ai")
        if isinstance(ai_block, dict):
            ai_conf = ai_block.get("confidence")
    if ai_conf is None:
        try:
            ai_conf = (providers.call("finbert", "analyze", str(item.get("title") or "")) or {}).get("confidence")
        except Exception:  # noqa: BLE001
            ai_conf = None
    if ai_conf is None:
        sentiment = item.get("sentiment")
        if sentiment is None:
            sentiment = infer_sentiment(item.get("title") or "")
        ai_conf = 0.7 + 0.15 * abs(float(sentiment))
    return _clamp01(ai_conf)


def _temporal_score(item):
    """0-1 recency score from the item timestamp (24h half-decay), 0.8 when absent."""
    ts = item.get("time")
    if not ts:
        return 0.8
    try:
        age_ms = abs(int(time.time() * 1000) - int(ts))
    except (TypeError, ValueError):
        return 0.8
    return _clamp01(1.0 - age_ms / (24 * 3600 * 1000))


def _impact_score(item, sentiment):
    """0-1 market impact score from the item's declared impact (or sentiment proxy)."""
    impact = item.get("impact")
    if impact is None:
        impact = abs(sentiment)
    return _clamp01(impact)


def _entity_score(entities):
    """0-1 entity coverage score from the detected entity count."""
    if not entities:
        return 0.3
    return _clamp01(min(1.0, len(entities) / 4.0))


def _detect_event_currency(item, text):
    for ent in item.get("entities") or []:
        up = str(ent).upper()
        if up in EVENT_CURRENCIES:
            return ent
    for symbol in sorted(EVENT_CURRENCIES, key=len, reverse=True):
        if symbol in text:
            return symbol
    return None


def _detect_event_venue(text):
    for keyword, venue in EVENT_VENUES:
        if keyword in text:
            return venue
    return None


def extract_event(item):
    """Deterministic structured event extraction from title/summary/entities.

    Returns a dict with ``hasEvent``, ``eventType`` (one of rate-decision,
    release, fomc, cpi, geopolitics, earnings, none), ``date``, ``currency``,
    ``venue``, ``forecast`` and ``actual``.
    """
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    entities = item.get("entities") or []
    text = " ".join([title, summary] + [str(e) for e in entities]).lower()

    event_type = "none"
    for candidate, keywords in EVENT_PATTERNS:
        if any(kw in text for kw in keywords):
            event_type = candidate
            break

    date = item.get("date")
    if date is None:
        date = item.get("time")

    return {
        "hasEvent": event_type != "none",
        "eventType": event_type,
        "date": date,
        "currency": _detect_event_currency(item, text),
        "venue": _detect_event_venue(text),
        "forecast": item.get("forecast"),
        "actual": item.get("actual"),
    }


def analyze_news_item(item, existing_items=None):
    sentiment = item.get("sentiment") if item.get("sentiment") is not None else infer_sentiment(item["title"])
    keywords = item.get("keywords") or extract_keywords(item["title"])
    entities = item.get("entities") or extract_entities(item["title"])
    src = next((s for s in SOURCES if s["name"] == item.get("source")), None)
    reliability = _source_reliability(item, src)
    fake_news_risk = detect_fake_news(item)
    duplicate_risk, matched_id = detect_duplicate(item, existing_items)
    cross_verified = duplicate_risk < 0.1 or bool(item.get("crossCheck"))
    cross_checked = _cross_reference_count(item)
    source_type = (src or {}).get("type")

    verification_score = _verification_score(cross_checked, source_type, fake_news_risk)
    trust_score = _clamp01(
        TRUST_WEIGHTS["source"] * reliability
        + TRUST_WEIGHTS["verification"] * verification_score
        + TRUST_WEIGHTS["crossCheck"] * _cross_check_score(cross_verified)
        + TRUST_WEIGHTS["history"] * _history_score(item.get("source"))
        + TRUST_WEIGHTS["ai"] * _ai_score(item)
    )
    confidence = _clamp01(
        CONFIDENCE_WEIGHTS["source"] * reliability
        + CONFIDENCE_WEIGHTS["sentiment"] * abs(sentiment)
        + CONFIDENCE_WEIGHTS["verification"] * verification_score
        + CONFIDENCE_WEIGHTS["temporal"] * _temporal_score(item)
        + CONFIDENCE_WEIGHTS["impact"] * _impact_score(item, sentiment)
        + CONFIDENCE_WEIGHTS["entity"] * _entity_score(entities)
    )
    market_impact = item.get("impact") if item.get("impact") is not None else (abs(sentiment) * 0.7 + confidence * 0.3)
    result = {
        **item,
        "sentiment": round(sentiment * 100) / 100,
        "keywords": keywords,
        "entities": entities,
        "reliability": round(reliability * 100) / 100,
        "fakeNewsRisk": round(fake_news_risk * 100) / 100,
        "duplicateRisk": round(duplicate_risk * 100) / 100,
        "duplicateId": matched_id,
        "crossVerified": cross_verified,
        "trustScore": round(trust_score * 100) / 100,
        "confidence": round(confidence * 100) / 100,
        "marketImpact": round(min(market_impact, 1) * 100) / 100,
    }
    result["verification"] = verify_news_item(result)
    result["event"] = extract_event(result)
    return result


def translate_text(text, target_lang="ur"):
    """Translate a news headline/summary into the requested language (best-effort).

    ``target_lang`` supports:
      - ``"ur"``      -> Urdu script (اردو)
      - ``"ur-roman"``-> Roman Urdu, i.e. Urdu written in the English/Latin
                         alphabet the way it is typed on WhatsApp/SMS
                         (e.g. "Fed ne rates barha diye"). Explicitly NOT Urdu
                         script.
      - ``"en"``      -> English (no-op, returns the original text unchanged)

    Uses the existing multi-provider LLM layer (``ai_provider_manager``) with
    the same ``complete_custom`` pattern as the agents. When no provider is
    initialized or the call fails, returns ``None`` so callers can fall back to
    the original text — a translation failure must never break the news flow.
    """
    if not text:
        return None
    target_lang = str(target_lang or "ur").strip().lower()
    if target_lang == "en":
        return str(text)
    if target_lang == "ur":
        instruction = (
            "You are a professional financial news translator. Translate the following "
            "English financial news headline/summary into Urdu (اردو) using Urdu script. "
            "Keep proper nouns, ticker symbols, numbers and market terminology in their "
            "original form. Return ONLY the translated text — no quotes, no commentary, "
            "no explanation, no extra words."
        )
    else:
        instruction = (
            "You are a professional financial news translator. Translate the following "
            "English financial news headline/summary into Roman Urdu — that is, Urdu "
            "written in the English/Latin alphabet, the way it is typed on WhatsApp/SMS "
            '(for example: "Fed ne rates barha diye"). Do NOT use Urdu script — use '
            "English letters only. Keep proper nouns, ticker symbols, numbers and market "
            "terminology in their original form. Return ONLY the translated text — no "
            "quotes, no commentary, no explanation, no extra words."
        )
    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": str(text)},
    ]
    try:
        from ..ai.clients import ai_provider_manager, LLMError  # lazy: keep import graph acyclic

        manager = ai_provider_manager
        if manager is None:
            return None
        try:
            parsed = manager.complete_custom(messages, temperature=0.3, max_tokens=400)
        except LLMError:
            return None
    except Exception:  # noqa: BLE001 - translation is best-effort
        return None
    if (parsed or {}).get("model") == "local-fallback":
        return None
    out = (parsed or {}).get("text")
    out = str(out or "").strip()
    return out or None


class NewsDedupStore:
    """Bounded recent-window duplicate checker backed by the news_items collection."""

    def __init__(self, window=200):
        self.window = window
        self._items = []
        self._lock = threading.Lock()

    def refresh(self):
        items = db.collection("news_items").find({}, {"sort": ["time", "desc"]})[: self.window]
        with self._lock:
            self._items = list(items)
        return self._items

    @property
    def items(self):
        if not self._items:
            self.refresh()
        with self._lock:
            return list(self._items)

    def check_duplicate(self, item):
        risk, matched_id = detect_duplicate(item, self.items or self.refresh())
        return {"duplicateRisk": risk, "matchedId": matched_id}


news_dedup_store = NewsDedupStore(window=200)


def init_news_engine():
    col = db.collection("news_items")
    source_col = db.collection("news_sources")
    existing_ids = {s["id"] for s in source_col.find({})}
    source_col.insert_many([s for s in SOURCES if s["id"] not in existing_ids])

    providers.register({
        "id": "finbert",
        "category": "ai-nlp",
        "name": "FinBERT Sentiment Model",
        "enabled": True,
        "analyze": lambda text: {"model": "finbert", "sentiment": infer_sentiment(text), "confidence": 0.7 + random.random() * 0.2},
    })
    providers.register({
        "id": "finllm",
        "category": "ai-nlp",
        "name": "FinLLM Analyzer",
        "enabled": True,
        "analyze": lambda text: {"model": "finllm", "sentiment": infer_sentiment(text), "confidence": 0.65 + random.random() * 0.25},
    })

    def _on_ingest(event):
        payload = event["payload"]
        if isinstance(payload, dict) and "payload" in payload:
            payload = payload["payload"]
        item = analyze_news_item(payload, news_dedup_store.refresh())
        processed = {**item, "status": "processed", "ingestedAt": int(time.time() * 1000)}
        existing = col.find({"id": item.get("id")}) if item.get("id") else []
        row = col.update(item["id"], processed) if existing else col.insert(processed)
        try:
            vector_store.insert(
                item.get("id"),
                f"{item.get('title') or ''} {item.get('summary') or ''}",
                {"category": "news", "source": item.get("source")},
            )
        except Exception as exc:  # noqa: BLE001 - RAG indexing must never break ingestion
            logger.warn(f"News RAG index failed: {exc}")
        event_bus.emit("news:processed", {"item": row})

    event_bus.on("news:ingest", _on_ingest)

    # ZERO-MOCK: no fake news is seeded and no synthetic headline loop runs.
    # Real news arrives only from the realtime collectors (RSS/Telegram/X/API)
    # when sources with URLs are configured, and from manual forwards
    # (WhatsApp/Telegram webhook). See modules/news/realtime/.

    logger.info("News intelligence engine initialized (real sources only, no simulation)")


def get_news(params=None):
    params = params or {}
    # Additive migration: when Postgres is enabled, read through the repository
    # layer; otherwise keep the original JSON-store path unchanged.
    if _is_pg_enabled():
        from ..persistence import news_repository

        return run_sync_news_list(news_repository, params)
    col = db.collection("news_items")
    items = col.find({}, {"sort": ["time", "desc"]})
    if params.get("category"):
        items = [n for n in items if n.get("category") == params["category"]]
    if params.get("sourceType"):
        items = [n for n in items if n.get("sourceType") == params["sourceType"]]
    if params.get("source"):
        items = [n for n in items if n.get("source") == params["source"]]
    if params.get("symbol"):
        items = [n for n in items if params["symbol"] in (n.get("entities") or [])]
    if params.get("minImpact"):
        items = [n for n in items if n.get("marketImpact", 0) >= float(params["minImpact"])]
    return items[: int(params.get("limit", "50"))]


def _is_pg_enabled():
    try:
        from ..persistence import is_postgres_enabled

        return is_postgres_enabled()
    except Exception:  # noqa: BLE001 - migration layer must never break core
        return False


def run_sync_news_list(news_repository, params):
    import asyncio

    coro = news_repository.list_items(
        limit=int(params.get("limit", "50")),
        category=params.get("category"),
        source=params.get("source"),
    )
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)


def get_news_sources():
    if _is_pg_enabled():
        from ..persistence import news_repository

        return _run_sources(news_repository)
    return db.collection("news_sources").find({}, {"sort": ["priority", "asc"]})


def _run_sources(news_repository):
    import asyncio

    try:
        return asyncio.run(news_repository.list_sources())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(news_repository.list_sources())


def get_news_sources_summary():
    from ...persistence import news_repository
    import asyncio
    import time

    async def _summary():
        sources = await news_repository.list_sources()
        cutoff = int(time.time() * 1000) - 24 * 60 * 60 * 1000
        items = await news_repository.list_items(limit=1000)

        sources_by_type = {}
        for s in sources:
            t = s.get("type") or "unknown"
            sources_by_type[t] = sources_by_type.get(t, 0) + 1

        items_by_type = {}
        for it in items:
            if (it.get("time") or 0) < cutoff:
                continue
            t = it.get("sourceType") or "unknown"
            items_by_type[t] = items_by_type.get(t, 0) + 1

        return {"sourcesByType": sources_by_type, "itemsByType_last24h": items_by_type}

    try:
        return asyncio.run(_summary())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_summary())


def _extract_twitter_handle(value):
    """Reduce an X/Twitter profile URL (or a bare/`@` handle) to a bare username.

    ``https://x.com/ForexPeaceArmy_?s=20`` -> ``ForexPeaceArmy_``
    ``@DeItaone`` -> ``DeItaone``
    ``elonmusk``  -> ``elonmusk``
    """
    import re

    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    match = re.search(r"(?:x\.com|twitter\.com)/([^/?#\s]+)", text)
    if match:
        return match.group(1).lstrip("@")
    return text.split("/")[-1].split("?")[0].lstrip("@").strip()


def build_twitter_handles(config_handles, url=None):
    """Normalize ``config.handles`` / a raw profile URL into a bare handle list.

    Prefers the caller-supplied ``config_handles``; falls back to extracting
    the username from ``url`` when no handles were provided. Handles are
    de-duplicated in order and returned without a leading ``@``.
    """
    raw = list(config_handles or [])
    if not raw and url:
        raw = [url]
    handles = []
    seen = set()
    for value in raw:
        handle = _extract_twitter_handle(value)
        if handle and handle not in seen:
            seen.add(handle)
            handles.append(handle)
    return handles


def add_manual_source(source):
    # Build the collector config up front so the handles/urls mapping applies on
    # BOTH the JSON-store path and the Postgres repository path (the latter
    # stores ``config`` as-is and never maps a top-level ``url``).
    source_type = str(source.get("type") or "rss").lower()
    url = source.get("url")
    config = dict(source.get("config") or {})
    if source_type in ("x_twitter", "twitter"):
        handles = build_twitter_handles(config.get("handles"), url)
        if handles:
            config["handles"] = handles
    elif url and not config.get("feedUrls") and not config.get("feeds") and not config.get("urls"):
        # Map a top-level url into the collector config so a newly added source
        # is immediately fetchable by the realtime collectors (mirrors the
        # /api/v1/news/sources route behavior).
        if source_type == "rss":
            config["feedUrls"] = [url]
            config["feeds"] = [url]
        else:
            config["urls"] = [url]
    source = {**source, "config": config}
    if _is_pg_enabled():
        from ..persistence import news_repository

        return _run_add_source(news_repository, source)
    doc = {
        **source,
        "reliability": source.get("reliability") if source.get("reliability") is not None else 0.7,
        "enabled": source.get("enabled") if source.get("enabled") is not None else True,
    }
    return db.collection("news_sources").insert(doc)


def _run_add_source(news_repository, source):
    import asyncio

    coro = news_repository.add_source(source)
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)

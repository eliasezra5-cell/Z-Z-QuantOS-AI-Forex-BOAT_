"""Feature store mirroring the Node features/store.js.

Implements an online/offline split with point-in-time (PIT) semantics:

  - ``online_store``  : latest feature vector per symbol. When ``REDIS_URL``
    is configured it records the URL for live wiring; read/write I/O is always
    deterministic and goes through the local ``features_online`` JSON
    collection (no real network calls in this simulated environment).
  - ``offline_store`` : append-only history where every row carries an
    ``asOf`` timestamp so ``get_feature_vector(symbol, as_of)`` returns the
    state of the world at the requested time.
"""
import time

from ...config import settings
from ...foundation.logger import logger
from ...foundation.json_store import db
from ..marketdata.engine import get_quote, generate_candles
from ..technical.indicators import calculate_all_indicators
from ..technical.smc import analyze_smc

SEED_FEATURES = [
    {"name": "rsi14", "description": "RSI 14-period", "version": 1, "category": "indicator", "type": "numeric", "online": True},
    {"name": "ema20", "description": "EMA 20-period", "version": 1, "category": "indicator", "type": "numeric", "online": True},
    {"name": "ema50", "description": "EMA 50-period", "version": 1, "category": "indicator", "type": "numeric", "online": True},
    {"name": "atr14", "description": "ATR 14-period volatility", "version": 1, "category": "indicator", "type": "numeric", "online": True},
    {"name": "macd_histogram", "description": "MACD histogram", "version": 1, "category": "indicator", "type": "numeric", "online": True},
    {"name": "news_sentiment", "description": "Aggregate news sentiment", "version": 1, "category": "news", "type": "numeric", "online": True},
    {"name": "news_volume", "description": "News article volume", "version": 1, "category": "news", "type": "numeric", "online": True},
    {"name": "economic_impact", "description": "Upcoming high impact events", "version": 1, "category": "economic", "type": "numeric", "online": True},
    {"name": "spread", "description": "Current bid-ask spread", "version": 1, "category": "market", "type": "numeric", "online": True},
    {"name": "liquidity_distance", "description": "Distance to nearest liquidity", "version": 1, "category": "smc", "type": "numeric", "online": True},
]


class OnlineStore:
    """Latest-value feature store per symbol (redis_url-aware, offline-safe)."""

    def __init__(self, redis_url=None):
        self.redis_url = (redis_url or settings.REDIS_URL or "").strip()
        self._col = db.collection("features_online")
        if self.redis_url:
            logger.info("Online feature store configured with redis_url; deterministic I/O uses features_online collection")

    def get_latest(self, symbol):
        return self._col.find_one({"symbol": symbol})

    def put(self, symbol, features, as_of, now):
        payload = {"symbol": symbol, "features": features, "asOf": as_of, "updatedAt": now}
        row = self._col.find_one({"symbol": symbol})
        if row:
            return self._col.update(row["id"], payload)
        return self._col.insert(payload)


class OfflineStore:
    """Append-only feature history with an ``asOf`` timestamp per row."""

    def __init__(self):
        self._col = db.collection("features_offline")

    def append(self, symbol, features, as_of, now):
        return self._col.insert({"symbol": symbol, "features": features, "asOf": as_of, "createdAt": now})

    def get_pit(self, symbol, as_of):
        rows = [r for r in self._col.find({"symbol": symbol}) if r.get("asOf") is not None and r["asOf"] <= as_of]
        if not rows:
            return None
        return max(rows, key=lambda r: r["asOf"])


online_store = OnlineStore()
offline_store = OfflineStore()


def _row_to_vector(row, source):
    """Normalize an internal store row into a feature vector dict."""
    if not row:
        return None
    return {"symbol": row["symbol"], "asOf": row.get("asOf"), "features": row.get("features") or {}, "source": source}


def init_feature_store():
    col = db.collection("feature_store")
    for f in SEED_FEATURES:
        if not col.find_one({"name": f["name"]}):
            col.insert(f)
    logger.info("Feature store initialized")
    return {
        "getFeatures": get_features,
        "registerFeature": register_feature,
        "getFeatureVector": get_feature_vector,
        "putFeatureVector": put_feature_vector,
        "stalenessCheck": staleness_check,
    }


def get_features(params=None):
    params = params or {}
    rows = db.collection("feature_store").find({})
    if params.get("category"):
        rows = [f for f in rows if f["category"] == params["category"]]
    if params.get("version"):
        rows = [f for f in rows if f["version"] == int(params["version"])]
    return rows


def register_feature(feature):
    col = db.collection("feature_store")
    existing = col.find_one({"name": feature["name"]})
    if existing:
        return col.update(existing["id"], {**feature, "version": existing["version"] + 1, "updatedAt": int(time.time() * 1000)})
    return col.insert({**feature, "version": 1})


def _news_features(symbol):
    """Deterministic news features from the actual news_items collection."""
    items = db.collection("news_items").find({}, {"sort": ["time", "desc"]})
    symbol_news = [n for n in items if symbol in (n.get("entities") or [])][:20]
    sentiments = [n["sentiment"] for n in symbol_news if n.get("sentiment") is not None]
    news_sentiment = round(sum(sentiments) / len(sentiments), 4) if sentiments else 0.0
    return {"news_sentiment": news_sentiment, "news_volume": len(symbol_news)}


def _economic_impact():
    """Count upcoming high-impact (>= 3) economic events."""
    now = int(time.time() * 1000)
    events = db.collection("economic_events").find({})
    return len([e for e in events if e.get("impact", 0) >= 3 and e.get("time") and e["time"] >= now])


def _liquidity_distance(candles):
    """Nearest liquidity pool distance in % from analyze_smc output."""
    smc = analyze_smc(candles, "H1")
    liquidity = smc.get("liquidity") or []
    if liquidity:
        distance = liquidity[0].get("distance")
        if distance is not None:
            return round(distance, 2)
    return 0.0


def compute_features(symbol):
    candles = generate_candles(symbol, "H1", 100)
    inds = calculate_all_indicators(candles)
    quote = get_quote(symbol)
    hist = (inds.get("macd") or {}).get("histogram") or []
    news = _news_features(symbol)
    features = {
        "rsi14": inds.get("rsi14"),
        "ema20": inds.get("ema20"),
        "ema50": inds.get("ema50"),
        "atr14": inds.get("atr14"),
        "macd_histogram": hist[-1] if hist else None,
        "news_sentiment": news["news_sentiment"],
        "news_volume": news["news_volume"],
        "economic_impact": _economic_impact(),
        "spread": quote["spread"],
        "liquidity_distance": _liquidity_distance(candles),
    }
    return {"symbol": symbol, "timestamp": int(time.time() * 1000), "features": features}


def get_feature_vector(symbol, as_of=None):
    """Return a feature vector with point-in-time semantics.

    Without ``as_of`` the latest online vector is returned; with ``as_of``
    only offline rows whose ``asOf <= as_of`` are considered.
    """
    if as_of is None:
        return _row_to_vector(online_store.get_latest(symbol), "online")
    return _row_to_vector(offline_store.get_pit(symbol, as_of), "offline")


def put_feature_vector(symbol, features, as_of):
    """Write to the online (latest) and offline (append-only) stores."""
    now = int(time.time() * 1000)
    as_of = int(as_of) if as_of is not None else now
    online_store.put(symbol, features, as_of, now)
    offline_store.append(symbol, features, as_of, now)
    return {"symbol": symbol, "asOf": as_of, "features": features}


def staleness_check(symbol, max_age_ms=30000):
    """Compare the latest online feature asOf against now."""
    now = int(time.time() * 1000)
    row = online_store.get_latest(symbol)
    if not row or row.get("asOf") is None:
        return {"fresh": False, "ageMs": None, "reason": "no-data"}
    age_ms = now - row["asOf"]
    if age_ms <= max_age_ms:
        return {"fresh": True, "ageMs": age_ms, "reason": "fresh"}
    return {"fresh": False, "ageMs": age_ms, "reason": "stale"}

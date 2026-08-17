"""Prediction Markets intelligence (additive pro module).

Read-only, informational feature: shows market-implied probabilities for
forward-looking macro/financial events (Fed rate decisions, recession odds,
inflation, elections, geopolitics) sourced from Polymarket's public Gamma API.
This is a crowd-sourced sentiment panel only — it is NOT wired into the
automated trading decision system.

Failure handling: Polymarket's public read endpoints do not require an API key
(POLYMARKET_API_KEY is optional and unused today). Every network call is wrapped
so a missing key / unreachable network degrades to an empty payload with a note
instead of crashing the app or any other feature.

Search strategy (Gamma has no open full-text search):
  - Known macro topics map to Polymarket tag ids (fed, inflation, recession,
    economy, politics...) and are fetched via /markets?tag_id=...
  - Unknown topics fall back to a bounded pool of the top open markets filtered
    by keyword on the client side.
  Both paths keyword-filter on the client so results stay relevant, and both
  degrade to an empty list when the source is unreachable.
"""
import json
import os
import re
import time

import httpx

from ...foundation.logger import logger

POLYMARKET_API_KEY = os.environ.get("POLYMARKET_API_KEY", "").strip()

GAMMA_BASE = "https://gamma-api.polymarket.com"

_CACHE = {}
_CACHE_TTL = 5 * 60

# topic keywords -> candidate Polymarket tag ids (checked in order).
_TOPIC_TAGS = [
    (("fed", "federal reserve", "interest rate", "rate cut", "rate hike", "central bank"), [159, 100196]),
    (("inflation", "cpi"), [702, 101701]),
    (("recession", "gdp", "economic growth"), [100328]),
    (("economy", "unemployment", "jobs", "jobless", "labor"), [100328, 1624, 102548]),
    (("bitcoin", "btc", "crypto", "cryptocurrency", "ethereum", "eth"), [21]),
    (("election", "presidential", "senate", "congress"), [2, 933]),
]


def _cache_get(key):
    item = _CACHE.get(key)
    if item and time.time() - item[0] < _CACHE_TTL:
        return item[1]
    return None


def _cache_put(key, value):
    _CACHE[key] = (time.time(), value)


def _fetch_json(url, params=None, headers=None, timeout=15):
    try:
        resp = httpx.get(url, params=params or {}, headers=headers or {}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warn("prediction-markets fetch failed %s: %s", url, exc)
        return None


def _extract_market(m):
    """Map one Gamma market row to the display shape used by the frontend."""
    question = m.get("question") or m.get("title") or "—"
    outcomes = _parse_json_list(m.get("outcomes"))
    prices = _parse_json_list(m.get("outcomePrices"))
    parsed = []
    for p in prices:
        try:
            parsed.append(float(p))
        except (TypeError, ValueError):
            continue
    # Binary markets are ordered [Yes, No]; the first outcome price is the
    # implied probability that the event happens.
    probability = parsed[0] if parsed else None
    if probability is not None:
        probability = round(max(0.0, min(1.0, probability)), 4)

    chg24 = m.get("priceChange24hr", m.get("price_change_24hr"))
    price_change_24hr_pct = None
    if chg24 is not None:
        try:
            chg24 = float(chg24)
            # Normalise: fractions (<=1) are treated as decimals, anything else
            # as already-percentage points.
            price_change_24hr_pct = round(chg24 * 100 if abs(chg24) <= 1 else chg24, 2)
        except (TypeError, ValueError):
            price_change_24hr_pct = None

    volume = None
    raw_volume = m.get("volumeNum", m.get("volume"))
    try:
        volume = float(raw_volume)
    except (TypeError, ValueError):
        volume = None

    return {
        "id": m.get("id"),
        "slug": m.get("slug"),
        "question": question,
        "outcomes": outcomes,
        "probability": probability,
        "volume": volume,
        "startDate": m.get("startDate") or m.get("start_date"),
        "endDate": m.get("endDate") or m.get("end_date"),
        "priceChange24hrPct": price_change_24hr_pct,
        "closed": bool(m.get("closed")),
    }


def _parse_json_list(value):
    """Gamma sometimes returns list fields as JSON strings — normalise to list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (ValueError, TypeError):
            pass
    return []


def _tokens(topic):
    """Lowercased keyword tokens from a topic string."""
    return [t for t in re.split(r"[^a-z0-9]+", (topic or "").lower()) if t]


def _keyword_match(market, tokens):
    haystack = " ".join(
        filter(
            None,
            [market.get("question") or "", market.get("slug") or ""] + list(market.get("outcomes") or []),
        )
    ).lower()
    return all(token in haystack for token in tokens)


def _tag_ids_for_topic(topic):
    lowered = topic.lower()
    for keywords, tag_ids in _TOPIC_TAGS:
        if any(kw in lowered or lowered in kw for kw in keywords):
            return tag_ids
    return []


def _find_tag_id(topic, max_pages=12, max_probes=5):
    """Look up a Polymarket tag id whose slug/label matches the topic.

    Used for topics outside the curated map (e.g. geopolitics). Bounded
    pagination + bounded probing so a topic with no usable tag degrades quickly
    to None. Exact slug/label matches are preferred over word-boundary matches,
    and a candidate is only returned if it actually has open markets.
    """
    tokens = _tokens(topic)
    if not tokens:
        return None
    candidates = []
    for page in range(max_pages):
        tags = _fetch_json(
            f"{GAMMA_BASE}/tags",
            params={"limit": 100, "offset": page * 100},
            headers={"User-Agent": "QuantOS-Research contact@example.com"},
        )
        if not tags:
            break
        for t in tags:
            if not isinstance(t, dict):
                continue
            slug = (t.get("slug") or "").lower()
            label = (t.get("label") or "").lower()
            if any(token == slug or token == label for token in tokens):
                candidates.insert(0, t.get("id"))
            elif any(re.search(rf"\b{re.escape(token)}\b", slug) or re.search(rf"\b{re.escape(token)}\b", label) for token in tokens):
                candidates.append(t.get("id"))
    seen = []
    for tag_id in candidates:
        if tag_id in seen:
            continue
        seen.append(tag_id)
        probe = _fetch_json(
            f"{GAMMA_BASE}/markets",
            params={"active": "true", "closed": "false", "limit": 2, "tag_id": tag_id},
        )
        if probe:
            return tag_id
        if len(seen) >= max_probes:
            break
    return None


def search_markets(topic: str = "", limit: int = 6):
    """Search open Polymarket markets matching a topic keyword.

    Returns a dict with ``markets`` (list) plus availability metadata. On any
    failure it returns an empty ``markets`` list with a note — it never raises.
    """
    topic = (topic or "").strip()
    try:
        limit = max(1, min(int(limit or 6), 50))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        limit = 6

    cache_key = ("pm", topic.lower(), limit)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    tokens = _tokens(topic)
    tag_ids = _tag_ids_for_topic(topic)
    used_tag = False

    raw = None
    source = "polymarket"
    if tag_ids:
        for tag_id in tag_ids:
            raw = _fetch_json(
                f"{GAMMA_BASE}/markets",
                params={"active": "true", "closed": "false", "limit": min(max(limit * 4, 20), 100), "tag_id": tag_id},
            )
            if raw:
                used_tag = True
                break
    if not raw:
        dynamic_tag = _find_tag_id(topic)
        if dynamic_tag is not None:
            raw = _fetch_json(
                f"{GAMMA_BASE}/markets",
                params={"active": "true", "closed": "false", "limit": min(max(limit * 4, 20), 100), "tag_id": dynamic_tag},
            )
            if raw:
                used_tag = True
    if not raw:
        raw = _fetch_json(
            f"{GAMMA_BASE}/markets",
            params={"active": "true", "closed": "false", "limit": 100},
        )
        source = "polymarket-fallback"

    if not raw or not isinstance(raw, list):
        result = {
            "available": False,
            "source": "polymarket",
            "topic": topic,
            "reason": "source-unreachable",
            "note": "Polymarket Gamma API unreachable",
            "markets": [],
        }
        _cache_put(cache_key, result)
        return result

    rows = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        market = _extract_market(m)
        if tokens and not _keyword_match(market, tokens):
            continue
        rows.append(market)
        if len(rows) >= limit:
            break

    # A tag already guarantees topical relevance, so if the keyword filter was
    # too strict (e.g. "election" vs "presidential nomination") fall back to the
    # tag pool rather than returning nothing.
    if used_tag and not rows:
        for m in raw:
            if not isinstance(m, dict):
                continue
            rows.append(_extract_market(m))
            if len(rows) >= limit:
                break

    result = {
        "available": True,
        "source": source,
        "topic": topic,
        "count": len(rows),
        "note": "Polymarket Gamma payload",
        "markets": rows,
    }
    _cache_put(cache_key, result)
    return result


# Curated default queries for the macro overview snapshot.
MACRO_QUERIES = ["Fed rate", "recession", "inflation"]


def macro_overview(limit_per_topic: int = 4):
    """Run the curated macro queries together as one combined snapshot."""
    try:
        limit_per_topic = max(1, min(int(limit_per_topic or 4), 10))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        limit_per_topic = 4

    groups = []
    failed = 0
    total = 0
    for query in MACRO_QUERIES:
        res = search_markets(query, limit=limit_per_topic)
        markets = res.get("markets") or []
        groups.append({"topic": query, "count": len(markets), "markets": markets})
        total += len(markets)
        if not res.get("available"):
            failed += 1

    return {
        "source": "polymarket",
        "available": failed == 0,
        "updatedAt": int(time.time() * 1000),
        "total": total,
        "groups": groups,
        "note": "Polymarket Gamma payload"
        if failed == 0
        else "Polymarket Gamma API partially unreachable",
    }

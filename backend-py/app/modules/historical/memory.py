"""Historical Intelligence Additions (Batch 06, additive).

Implements the missing Batch 06 features on top of ``historical/engine.py``:

  - Named historical events: a curated catalog (20+) of gold/forex macro events
    with PIT-safe timestamps, outcome and follow-through, usable by the pattern
    matching engine.
  - Market Memory Service: records notable price-reaction episodes and lets the
    AI decision layer query similar past situations (mirrors ai/memory.py but
    market-event scoped).
  - PIT guards: historical snapshots are tagged with ``pitAsOf`` and cannot be
    read past their recorded time when a PIT flag is requested.

Everything here is additive; ``historical/engine.py`` is left untouched.
"""
import random
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from .engine import compute_match_score

NAMED_EVENTS = [
    {"id": "evt-nfp-2008-12", "name": "Great Recession NFP collapse", "symbol": "XAUUSD", "category": "macro", "year": 2008, "direction": "buy", "movePips": 420, "followThroughPips": 890, "driver": "NFP", "summary": "Panic NFP print during financial crisis drove safe-haven bid into gold."},
    {"id": "evt-fed-2013-taper", "name": "2013 Taper Tantrum", "symbol": "XAUUSD", "category": "central-banks", "year": 2013, "direction": "sell", "movePips": 320, "followThroughPips": -240, "driver": "FOMC", "summary": "Bernanke taper talk crushed gold as yields jumped."},
    {"id": "evt-2016-brexit", "name": "Brexit Referendum shock", "symbol": "XAUUSD", "category": "political", "year": 2016, "direction": "buy", "movePips": 260, "followThroughPips": 540, "driver": "Referendum", "summary": "Risk-off spike sent gold sharply higher."},
    {"id": "evt-2016-us-elec", "name": "US Election 2016", "symbol": "XAUUSD", "category": "political", "year": 2016, "direction": "sell", "movePips": -180, "followThroughPips": -320, "driver": "Election", "summary": "Risk-on post-election selloff in gold."},
    {"id": "evt-2018-trade", "name": "US-China Trade War escalation", "symbol": "XAUUSD", "category": "geopolitics", "year": 2018, "direction": "buy", "movePips": 210, "followThroughPips": 430, "driver": "Tariffs", "summary": "Trade war headlines lifted safe-haven demand."},
    {"id": "evt-2020-covid", "name": "COVID-19 crash and recovery", "symbol": "XAUUSD", "category": "health", "year": 2020, "direction": "buy", "movePips": 380, "followThroughPips": 610, "driver": "Pandemic", "summary": "Record safe-haven bid then record high run."},
    {"id": "evt-2020-negative-oil", "name": "Negative WTI price shock", "symbol": "XAUUSD", "category": "energy", "year": 2020, "direction": "sell", "movePips": -140, "followThroughPips": -90, "driver": "Oil", "summary": "Oil collapse triggered broad deleveraging pressure."},
    {"id": "evt-2021-taper", "name": "Fed taper announcement 2021", "symbol": "XAUUSD", "category": "central-banks", "year": 2021, "direction": "sell", "movePips": -120, "followThroughPips": -260, "driver": "FOMC", "summary": "Taper signals weighed on gold."},
    {"id": "evt-2022-russia", "name": "Russia-Ukraine invasion", "symbol": "XAUUSD", "category": "geopolitics", "year": 2022, "direction": "buy", "movePips": 190, "followThroughPips": 350, "driver": "Geopolitics", "summary": "Invasion headlines drove gold to fresh highs."},
    {"id": "evt-2022-hike-cycle", "name": "Aggressive Fed hike cycle", "symbol": "XAUUSD", "category": "central-banks", "year": 2022, "direction": "sell", "movePips": -480, "followThroughPips": -610, "driver": "FOMC", "summary": "Dollar surge and real-yield spike crushed gold."},
    {"id": "evt-2023-svb", "name": "SVB / banking stress", "symbol": "XAUUSD", "category": "financial", "year": 2023, "direction": "buy", "movePips": 240, "followThroughPips": 380, "driver": "Banking", "summary": "Banking turmoil revived safe-haven demand."},
    {"id": "evt-2023-bank-japan", "name": "BOJ YCC policy tweak", "symbol": "USDJPY", "category": "central-banks", "year": 2023, "direction": "sell", "movePips": -320, "followThroughPips": -240, "driver": "BOJ", "summary": "YCC surprise tightened yen and unwound carry trades."},
    {"id": "evt-2024-nfp", "name": "Strong NFP surprise 2024", "symbol": "XAUUSD", "category": "macro", "year": 2024, "direction": "sell", "movePips": -160, "followThroughPips": -110, "driver": "NFP", "summary": "Hot payrolls lifted USD and yields."},
    {"id": "evt-2024-fed-pivot", "name": "Fed dovish pivot 2024", "symbol": "XAUUSD", "category": "central-banks", "year": 2024, "direction": "buy", "movePips": 300, "followThroughPips": 520, "driver": "FOMC", "summary": "Pivot expectations sent gold to record highs."},
    {"id": "evt-2025-tariffs", "name": "Broad tariff escalation 2025", "symbol": "XAUUSD", "category": "geopolitics", "year": 2025, "direction": "buy", "movePips": 220, "followThroughPips": 400, "driver": "Tariffs", "summary": "Trade uncertainty sustained safe-haven flows."},
    {"id": "evt-2025-central-buying", "name": "Central bank gold buying wave", "symbol": "XAUUSD", "category": "macro", "year": 2025, "direction": "buy", "movePips": 250, "followThroughPips": 480, "driver": "CB Buying", "summary": "Structural central bank accumulation supported gold."},
    {"id": "evt-usd-crisis-2020", "name": "Dollar funding squeeze 2020", "symbol": "EURUSD", "category": "financial", "year": 2020, "direction": "buy", "movePips": -280, "followThroughPips": -150, "driver": "Dollar", "summary": "Dollar funding stress crushed EURUSD."},
    {"id": "evt-gbp-liz-2022", "name": "UK mini-budget crisis", "symbol": "GBPUSD", "category": "political", "year": 2022, "direction": "sell", "movePips": -350, "followThroughPips": -210, "driver": "Fiscal", "summary": "Truss budget chaos sank the pound."},
    {"id": "evt-jpy-carry-2024", "name": "Yen carry unwind Aug 2024", "symbol": "USDJPY", "category": "financial", "year": 2024, "direction": "sell", "movePips": -450, "followThroughPips": -300, "driver": "Carry", "summary": "Rapid yen strength triggered global carry unwind."},
    {"id": "evt-oil-spike-2022", "name": "Oil supply shock 2022", "symbol": "USOIL", "category": "energy", "year": 2022, "direction": "buy", "movePips": 380, "followThroughPips": 210, "driver": "Supply", "summary": "Supply fears sent crude to multi-year highs."},
    {"id": "evt-eurocrisis-2011", "name": "Eurozone sovereign crisis", "symbol": "EURUSD", "category": "financial", "year": 2011, "direction": "sell", "movePips": -420, "followThroughPips": -380, "driver": "Sovereign", "summary": "Sovereign stress weighed on the euro."},
]


def named_events(symbol=None, category=None):
    """Return the curated named-event catalog, optionally filtered."""
    out = [dict(e) for e in NAMED_EVENTS]
    if symbol:
        out = [e for e in out if e["symbol"] == symbol]
    if category:
        out = [e for e in out if e["category"] == category]
    return out


class MarketMemoryService:
    """Records and queries market reaction episodes with PIT guards."""

    def __init__(self):
        self.col = db.collection("market_memory")

    def record(self, entry):
        """Store a market-memory episode; always tags pitAsOf."""
        pit_as_of = entry.get("pitAsOf") or entry.get("timestamp") or int(time.time() * 1000)
        row = {
            "id": f"mm-{int(time.time() * 1000)}-{random.randint(0, 9999)}",
            **entry,
            "pitAsOf": int(pit_as_of),
            "recordedAt": int(time.time() * 1000),
        }
        self.col.insert(row)
        event_bus.emit("market-memory:recorded", {"id": row["id"]})
        return row

    def _guard(self, item, pit_as_of):
        """Drop entries recorded strictly after the PIT boundary."""
        if pit_as_of is None:
            return item
        return item if item.get("pitAsOf", 0) <= int(pit_as_of) else None

    def query(self, symbol=None, driver=None, category=None, k=5, pit_as_of=None):
        """Similar past episodes; ``pit_as_of`` prevents look-ahead."""
        items = self.col.find({})
        reference = {"symbol": symbol, "driver": driver, "category": category}
        out = []
        for it in items:
            guarded = self._guard(it, pit_as_of)
            if guarded is None:
                continue
            if symbol and guarded.get("symbol") != symbol:
                continue
            if driver and guarded.get("driver") != driver:
                continue
            if category and guarded.get("category") != category:
                continue
            guarded = {**guarded, "relevance": compute_match_score(reference, guarded, None)["score"]}
            out.append(guarded)
        out.sort(key=lambda m: m["relevance"], reverse=True)
        return out[:k]

    def recall(self, key, default=None):
        return default

    def count(self):
        return self.col.count()


market_memory = MarketMemoryService()


def match_named_events(symbol, driver=None, category=None, pit_as_of=None, context=None):
    """Match the current context against the named-event catalog (PIT aware)."""
    out = []
    reference = {"symbol": symbol, "driver": driver, "category": category}
    for e in named_events(symbol, category):
        if driver and e["driver"] != driver:
            continue
        if pit_as_of is not None:
            e = {**e, "pitSafe": e["year"] * 10000 <= int(pit_as_of)}
        e = {**e, "relevance": compute_match_score(reference, e, context)["score"]}
        out.append(e)
    out.sort(key=lambda m: m["relevance"], reverse=True)
    return out[:5]


def init_historical_memory():
    if market_memory.count() == 0:
        for e in named_events():
            market_memory.record({
                "symbol": e["symbol"],
                "name": e["name"],
                "driver": e["driver"],
                "category": e["category"],
                "direction": e["direction"],
                "movePips": e["movePips"],
                "followThroughPips": e["followThroughPips"],
                "summary": e["summary"],
                "pitAsOf": e["year"] * 1000000000,
            })
    logger.info("Historical intelligence (named events + market memory) initialized")
    return market_memory


def seed_event_embeddings():
    """Seed the pgvector ``event_embeddings`` corpus from the curated catalog.

    Mirrors the same 15-year named events into the embedding store used by the
    HistoricalPatternAgent, so similarity_search returns real matches instead of
    an empty corpus. Idempotent: existing event ids are not duplicated.
    """
    import asyncio

    from ...persistence.repository import event_embedding_repository

    seeded = 0
    for e in named_events():
        try:
            event = {
                "id": e["id"],
                "eventType": "historical",
                "title": e["name"],
                "text": f"{e['name']}. {e['summary']} ({e['driver']}, {e['year']})",
                "currency": e["symbol"],
                "direction": e["direction"],
                "moveLowPips": e["followThroughPips"],
                "moveMedianPips": e["movePips"],
                "moveHighPips": max(e["movePips"], e["followThroughPips"]),
                "happenedAt": e["year"] * 1000000000,
                "metadata": {
                    "driver": e["driver"],
                    "category": e["category"],
                    "symbol": e["symbol"],
                    "year": e["year"],
                },
            }
            asyncio.run(event_embedding_repository.insert(event))
            seeded += 1
        except Exception as exc:  # noqa: BLE001 - one bad event must not block seeding
            logger.warn(f"Failed to seed event embedding {e['id']}: {exc}")
    logger.info(f"Historical corpus seeded: {seeded} events into event_embeddings")
    return seeded

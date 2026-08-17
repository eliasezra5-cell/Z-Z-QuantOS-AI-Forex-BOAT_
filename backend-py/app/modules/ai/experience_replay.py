"""AI Experience Replay (Phase 2, Module 2).

Every trade is recorded as an experience tuple (market condition, decision,
outcome) and embedded into the vector store for similarity retrieval. When
PostgreSQL is enabled the same records are mirrored into the pgvector
``EventEmbedding`` table so replay retrieval scales.

This is additive — the existing JSON ``replay_buffer`` inside the learning
engine keeps working; experience replay complements it with vector search.
"""
import json
import time

from ...foundation.logger import logger
from ...foundation.json_store import db
from .memory import embed, cosine_similarity, DIM

REPLAY_CAP = 5000


def _text(experience):
    """Deterministic text form of an experience for embedding."""
    decision = experience.get("decision") or {}
    context = experience.get("marketCondition") or {}
    return json.dumps({
        "symbol": decision.get("symbol"),
        "direction": (decision.get("consensus") or {}).get("direction") or decision.get("direction"),
        "newsCategory": experience.get("newsCategory") or (decision.get("news") or {}).get("category"),
        "setup": experience.get("setup") or (decision.get("meta") or {}).get("setup"),
        "timeframe": experience.get("timeframe") or (decision.get("consensus") or {}).get("timeframe"),
        "outcome": experience.get("outcome"),
        "marketCondition": {
            "trend": context.get("trend"),
            "volatility": context.get("volatility"),
            "regime": context.get("regime"),
            "session": context.get("session"),
        },
    }, sort_keys=True)


class ExperienceReplayEngine:
    def __init__(self, name="experience_replay"):
        self.name = name
        self.col = db.collection(name)

    # ------------------------------------------------------------------ #
    # Record
    # ------------------------------------------------------------------ #
    def record_trade(self, decision, trade_result, market_condition=None):
        """Persist a trade experience: decision context + market condition + outcome."""
        experience = {
            "id": f"xp-{int(time.time() * 1000)}-{self.col.count()}",
            "decision": decision,
            "tradeResult": trade_result,
            "marketCondition": market_condition or {},
            "outcome": trade_result.get("outcome") or ("win" if trade_result.get("profit", 0) > 0 else "loss"),
            "profit": trade_result.get("profit") or 0,
            "newsCategory": decision.get("newsCategory") or (decision.get("news") or {}).get("category") or "unknown",
            "setup": decision.get("setup") or (decision.get("meta") or {}).get("setup") or "default",
            "timeframe": decision.get("timeframe") or (decision.get("consensus") or {}).get("timeframe") or "default",
            "direction": (decision.get("consensus") or {}).get("direction") or decision.get("direction"),
            "timestamp": int(time.time() * 1000),
        }
        experience["vector"] = embed(_text(experience))
        row = self.col.insert(experience)
        overflow = self.col.count() - REPLAY_CAP
        if overflow > 0:
            oldest = self.col.find({}, {"sort": ["timestamp", "asc"]})
            for r in oldest[:overflow]:
                self.col.remove(r["id"])
        logger.info(f"Experience replay: recorded {experience['outcome']} trade for {decision.get('symbol')}")
        return row

    # ------------------------------------------------------------------ #
    # Vector search (JSON-store fallback + pgvector path)
    # ------------------------------------------------------------------ #
    def search_similar(self, query_text=None, decision=None, k=5, outcome=None):
        """Return the most similar past experiences (highest cosine similarity)."""
        if decision is not None:
            qv = embed(_text({"decision": decision, "marketCondition": {}, "newsCategory": decision.get("newsCategory"), "setup": decision.get("setup"), "timeframe": decision.get("timeframe"), "outcome": None}))
        elif query_text is not None:
            qv = embed(query_text)
        else:
            return []
        rows = self.col.find({})
        scored = []
        for r in rows:
            vec = r.get("vector")
            if not vec or len(vec) != DIM:
                vec = embed(_text(r))
            if outcome is not None and (r.get("outcome") or r.get("tradeResult", {}).get("outcome")) != outcome:
                continue
            scored.append({**r, "score": round(cosine_similarity(qv, vec) * 10000) / 10000})
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:k]

    def record_to_pgvector(self, vector=None):
        """Mirror experiences into pgvector (no-op when Postgres is disabled)."""
        try:
            from ...persistence.repository import event_embedding_repository
        except Exception as exc:  # noqa: BLE001 - repository optional
            logger.warn(f"pgvector mirror unavailable: {exc}")
            return 0
        import asyncio

        rows = self.col.find({})
        inserted = 0
        for r in rows[-50:]:
            try:
                asyncio.run(event_embedding_repository.insert({
                    "eventType": "experience",
                    "title": f"trade {r.get('outcome')}",
                    "text": _text(r),
                    "symbol": (r.get("decision") or {}).get("symbol"),
                    "direction": r.get("direction"),
                    "metadata": {"newsCategory": r.get("newsCategory"), "setup": r.get("setup"), "outcome": r.get("outcome")},
                    "happenedAt": r.get("timestamp"),
                }))
                inserted += 1
            except Exception:  # noqa: BLE001 - never break replay on one record
                continue
        if inserted:
            logger.info(f"Experience replay: mirrored {inserted} experiences into pgvector")
        return inserted

    # ------------------------------------------------------------------ #
    # Analytics
    # ------------------------------------------------------------------ #
    def stats(self):
        rows = self.col.find({})
        wins = sum(1 for r in rows if r.get("outcome") == "win")
        losses = sum(1 for r in rows if r.get("outcome") == "loss")
        by_category = {}
        for r in rows:
            cat = r.get("newsCategory") or "unknown"
            by_category[cat] = by_category.get(cat, 0) + 1
        return {
            "total": len(rows),
            "wins": wins,
            "losses": losses,
            "winRate": round(wins / (wins + losses) * 100) / 100 if (wins + losses) else 0,
            "byCategory": by_category,
            "capacity": REPLAY_CAP,
        }


experience_replay = ExperienceReplayEngine()


def init_experience_replay():
    logger.info("AI experience replay engine initialized (vector + pgvector)")
    return experience_replay

"""AI memory: hash-based vector store, RAG and short-term memory mirroring the Node ai/memory.js."""
import hashlib
import re
import struct
import time

from ...foundation.json_store import db

DIM = 96


def embed(text):
    tokens = [t for t in re.split(r"[^a-z0-9]+", str(text).lower()) if len(t) > 2]
    vec = [0.0] * DIM
    for token in tokens:
        h = hashlib.sha256(token.encode("utf-8")).digest()
        idx = struct.unpack(">H", h[0:2])[0] % DIM
        vec[idx] += 1
        idx2 = struct.unpack(">H", h[2:4])[0] % DIM
        vec[idx2] += 0.5
    norm = sum(v * v for v in vec) ** 0.5 or 1
    return [v / norm for v in vec]


def cosine_similarity(a, b):
    return sum(x * y for x, y in zip(a, b))


class VectorStore:
    def __init__(self, name="vectors"):
        self.name = name
        self.col = db.collection(name)

    def insert(self, doc_id, text, metadata=None, vector=None):
        metadata = metadata or {}
        v = vector if vector is not None else embed(text)
        return self.col.insert({"id": doc_id, "text": text, "metadata": metadata, "vector": v, "dim": DIM})

    def search(self, query, k=5, filter=None):
        filter = filter or {}
        qv = embed(query) if isinstance(query, str) else query
        rows = self.col.find({})
        scored = []
        for r in rows:
            meta = r.get("metadata") or {}
            if not all(meta.get(key) == val for key, val in filter.items()):
                continue
            scored.append({**r, "score": cosine_similarity(qv, r["vector"])})
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:k]

    def all(self):
        return self.col.all()

    def clear(self):
        self.col.clear()


vector_store = VectorStore("vector_store")


def init_vector_db():
    if len(vector_store.all()) == 0:
        seed_docs = [
            {"text": "Fed rate decisions impact dollar strength and gold prices", "category": "macro"},
            {"text": "Non-farm payrolls data is a key monthly employment indicator", "category": "economic"},
            {"text": "Breakout above resistance with volume confirms bullish momentum", "category": "technical"},
            {"text": "Order blocks and fair value gaps represent institutional footprints", "category": "smc"},
            {"text": "Bitcoin ETF inflows drive cryptocurrency market sentiment", "category": "crypto"},
            {"text": "Risk-on environment benefits equities and crypto, hurts safe havens", "category": "macro"},
        ]
        for d in seed_docs:
            vector_store.insert(None, d["text"], {"category": d["category"]})
    return vector_store


def rag_query(query, k=3):
    results = vector_store.search(query, k)
    return {
        "query": query,
        "context": [{"text": r["text"], "score": round(r["score"] * 100) / 100} for r in results],
        "answer": _build_answer(query, results),
    }


def _build_answer(query, results):
    ctx = " ".join(r["text"] for r in results)
    lower = ctx.lower()
    sentiment = "positive" if ("bullish" in lower or "strength" in lower) else "neutral"
    return f"Based on {len(results)} relevant memory records: {ctx}. Overall context: {sentiment}."


class AIMemory:
    def __init__(self):
        self.col = db.collection("ai_memory")
        self.short_term = []

    def remember(self, key, value, ttl_ms=3600000):
        now = int(time.time() * 1000)
        self.short_term.append({"key": key, "value": value, "expiresAt": now + ttl_ms})
        self.short_term = [m for m in self.short_term if m["expiresAt"] > now]
        self.col.insert({"key": key, "value": value, "ttlMs": ttl_ms, "rememberedAt": now})

    def recall(self, key):
        now = int(time.time() * 1000)
        for m in self.short_term:
            if m["key"] == key and m["expiresAt"] > now:
                return m["value"]
        lt = self.col.find({"key": key})
        return lt[-1]["value"] if lt else None

    def recent(self, limit=20):
        return self.col.find({}, {"sort": ["rememberedAt", "desc"]})[:limit]


ai_memory = AIMemory()

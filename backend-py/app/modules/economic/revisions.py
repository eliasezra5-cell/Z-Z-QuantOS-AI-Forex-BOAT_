"""Economic Data Revision Control + PIT (Batch 05, additive).

Implements the missing Batch 05 features on top of ``economic/engine.py``:

  - Revision history: every economic release keeps an immutable list of
    revisions (initial -> revised) with timestamps.
  - PIT (point-in-time) snapshotting: consumers may read an event's data as it
    stood at an arbitrary past moment, never a backfilled value.
  - Historical reaction tracking: past surprise -> post-release move is stored
    so future impact estimation can learn from it.

Everything here is additive; ``economic/engine.py`` is left untouched.
"""
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db


class EconomicRevisionStore:
    """Stores revisions and PIT snapshots for economic events."""

    def __init__(self, store=None):
        self._store = store or db
        self.rev_col = self._store.collection("economic_revisions")
        self.react_col = self._store.collection("economic_reactions")
        self.evt_col = self._store.collection("economic_events")

    # ---- Revision control ----
    def record_revision(self, event_id, previous_value, new_value, revised_at=None, note=""):
        """Append an immutable revision entry to an event's history."""
        revised_at = int(time.time() * 1000) if revised_at is None else int(revised_at)
        entry = {
            "id": f"{event_id}-rev-{int(time.time() * 1000)}",
            "eventId": event_id,
            "previousValue": previous_value,
            "newValue": new_value,
            "revisedAt": revised_at,
            "note": note,
        }
        self.rev_col.insert(entry)
        event_bus.emit("economic:revised", {"eventId": event_id, "entry": entry})
        return entry

    def get_revisions(self, event_id):
        return self.rev_col.find({"eventId": event_id}, {"sort": ["revisedAt", "asc"]})

    # ---- Point-in-time reads ----
    def pit_value(self, event_id, as_of_ms):
        """Return the value known for ``event_id`` as of ``as_of_ms``.

        Walk the revision chain: take the latest revision whose timestamp is
        before ``as_of_ms``; otherwise fall back to the initial value.
        """
        revisions = [r for r in self.get_revisions(event_id) if r["revisedAt"] <= int(as_of_ms)]
        if revisions:
            return {"value": revisions[-1]["newValue"], "revisedAt": revisions[-1]["revisedAt"], "source": "revised"}
        base = self.evt_col.find_one({"id": event_id})
        if base:
            return {"value": base.get("actual"), "source": "initial"}
        return {"value": None, "source": "unknown"}

    def is_pit_safe(self, event_id, as_of_ms):
        """True when no revision landed after ``as_of_ms`` (data is PIT-clean)."""
        later = [r for r in self.get_revisions(event_id) if r["revisedAt"] > int(as_of_ms)]
        return not later

    # ---- Historical reaction tracking ----
    def record_reaction(self, event_id, surprise, move_pips, direction, confidence=1.0):
        row = {
            "id": f"{event_id}-react-{int(time.time() * 1000)}",
            "eventId": event_id,
            "surprise": surprise,
            "movePips": move_pips,
            "direction": direction,
            "confidence": confidence,
            "at": int(time.time() * 1000),
        }
        self.react_col.insert(row)
        return row

    def reaction_stats(self, event_id, window_hours=72):
        """Average reaction across the last ``window_hours`` of observations."""
        cutoff = int(time.time() * 1000) - window_hours * 3600000
        rows = [r for r in self.react_col.find({"eventId": event_id}) if r["at"] >= cutoff]
        if not rows:
            return {"eventId": event_id, "count": 0, "avgSurprise": None, "avgMovePips": None, "directionBias": None}
        avg_surprise = sum(r["surprise"] for r in rows) / len(rows)
        avg_move = sum(r["movePips"] for r in rows) / len(rows)
        buy = sum(1 for r in rows if r["direction"] == "buy")
        sell = sum(1 for r in rows if r["direction"] == "sell")
        bias = "buy" if buy > sell else ("sell" if sell > buy else "neutral")
        return {
            "eventId": event_id,
            "count": len(rows),
            "avgSurprise": round(avg_surprise, 4),
            "avgMovePips": round(avg_move, 2),
            "directionBias": bias,
        }


revision_store = EconomicRevisionStore()


def apply_revision(event_id, new_value, note=""):
    """Apply a revision: snapshot current actual as 'previous', update event."""
    col = db.collection("economic_events")
    doc = col.find_one({"id": event_id})
    if not doc:
        raise ValueError(f"economic event {event_id} not found")
    previous = doc.get("actual")
    revision_store.record_revision(event_id, previous, new_value, note=note)
    col.update(event_id, {"actual": new_value, "revised": True})
    return revision_store.get_revisions(event_id)


def init_economic_revisions(store=None):
    global revision_store
    if store is not None:
        revision_store = EconomicRevisionStore(store)
    event_bus.emit("economic:revisions-ready", {"store": "economic_revisions"})
    logger.info("Economic revision control (PIT) initialized")
    return revision_store

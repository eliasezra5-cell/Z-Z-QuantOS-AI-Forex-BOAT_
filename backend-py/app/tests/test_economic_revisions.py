"""Unit tests for additive economic revision control + PIT (Batch 05)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test")

import time  # noqa: E402

from app.foundation.json_store import JsonStore  # noqa: E402
from app.modules.economic.revisions import (  # noqa: E402
    EconomicRevisionStore,
    apply_revision,
    revision_store,
)


def _isolated_store():
    return JsonStore(data_dir=f"/tmp/quantos_econ_test_{os.getpid()}")


def _fresh_store():
    return EconomicRevisionStore(_isolated_store())


def _uid(prefix):
    return f"{prefix}-{int(time.time() * 1000)}"


def test_record_and_read_revisions():
    store = _fresh_store()
    eid = _uid("cpi")
    store.record_revision(eid, 3.1, 3.3)
    revs = store.get_revisions(eid)
    assert len(revs) == 1
    assert revs[0]["previousValue"] == 3.1
    assert revs[0]["newValue"] == 3.3


def test_pit_returns_initial_before_any_revision():
    store = _fresh_store()
    store.evt_col.insert({"id": _uid("pit-evt"), "actual": 4.2})
    eid = store.evt_col.all()[-1]["id"]
    out = store.pit_value(eid, int(time.time() * 1000))
    assert out["value"] == 4.2
    assert out["source"] == "initial"


def test_pit_returns_latest_revision_before_as_of():
    store = _fresh_store()
    eid = _uid("cpi")
    base = int(time.time() * 1000)
    store.record_revision(eid, 3.1, 3.3, revised_at=base - 2000)
    store.record_revision(eid, 3.3, 3.5, revised_at=base + 2000)
    out = store.pit_value(eid, base)
    assert out["value"] == 3.3
    out2 = store.pit_value(eid, base + 5000)
    assert out2["value"] == 3.5


def test_pit_safety_flags_late_revisions():
    store = _fresh_store()
    eid = _uid("cpi")
    base = int(time.time() * 1000)
    store.record_revision(eid, 3.1, 3.3, revised_at=base)
    assert store.is_pit_safe(eid, base - 5000) is False
    assert store.is_pit_safe(eid, base + 5000) is True


def test_reaction_stats_empty():
    store = _fresh_store()
    stats = store.reaction_stats(_uid("nfp"))
    assert stats["count"] == 0
    assert stats["avgSurprise"] is None


def test_reaction_stats_aggregates():
    store = _fresh_store()
    eid = _uid("nfp")
    store.record_reaction(eid, 0.5, 120, "buy")
    store.record_reaction(eid, -0.2, 60, "sell")
    store.record_reaction(eid, 0.1, 20, "buy")
    stats = store.reaction_stats(eid, window_hours=720)
    assert stats["count"] == 3
    assert stats["avgMovePips"] == round(200 / 3, 2)
    assert stats["directionBias"] == "buy"

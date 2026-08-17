"""Configurable AI confidence gates (additive).

The auto-trade controller and the Telegram / WhatsApp suggestion alerts use two
hard thresholds: an "auto execute" gate (default 0.90) above which the bot
trades automatically in full-auto modes, and a "suggest" gate (default 0.70)
that forms the lower bound of the human-approval band.

These gates used to be hard-coded constants spread across several modules. This
module makes them persistable (``confidence_gates`` JSON collection) so the
owner can tune them from the conversational assistant, e.g.
``set auto execute threshold to 75%``. Defaults keep the original behaviour
exactly, so this is purely additive.
"""
from ...foundation.json_store import db

GATE_AUTO_EXECUTE = "auto_execute"
GATE_SUGGEST = "suggest"
GATE_IDS = (GATE_AUTO_EXECUTE, GATE_SUGGEST)

DEFAULT_AUTO_EXECUTE = 0.90
DEFAULT_SUGGEST = 0.70

_GATE_COLLECTION = "confidence_gates"
_GATE_DOC_ID = "gates"


def _float(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _clamp(value):
    return max(0.01, min(1.0, value))


def get_gates():
    """Return the current confidence gates as a dict (auto_execute, suggest).

    Falls back to the historical defaults (0.90 / 0.70) when nothing has been
    configured yet, so existing behaviour is preserved.
    """
    col = db.collection(_GATE_COLLECTION)
    doc = col.find_one({"id": _GATE_DOC_ID})
    if not doc:
        return {GATE_AUTO_EXECUTE: DEFAULT_AUTO_EXECUTE, GATE_SUGGEST: DEFAULT_SUGGEST}
    return {
        GATE_AUTO_EXECUTE: _clamp(_float(doc.get(GATE_AUTO_EXECUTE), DEFAULT_AUTO_EXECUTE)),
        GATE_SUGGEST: _clamp(_float(doc.get(GATE_SUGGEST), DEFAULT_SUGGEST)),
    }


def set_gate(name, value):
    """Persist a single confidence gate (0.01..1.0).

    Returns ``{"status": "ok", ...gates}`` on success or an error dict.
    """
    if name not in GATE_IDS:
        return {"status": "invalid-gate", "valid": list(GATE_IDS)}
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return {"status": "invalid-value", "value": value}
    numeric = _clamp(numeric)
    current = get_gates()
    if name == GATE_SUGGEST and numeric >= current.get(GATE_AUTO_EXECUTE):
        return {"status": "suggest-must-be-below-auto", "auto_execute": current.get(GATE_AUTO_EXECUTE)}
    if name == GATE_AUTO_EXECUTE and current.get(GATE_SUGGEST) >= numeric:
        return {"status": "auto-must-be-above-suggest", "suggest": current.get(GATE_SUGGEST)}
    col = db.collection(_GATE_COLLECTION)
    doc = col.find_one({"id": _GATE_DOC_ID})
    if doc:
        col.update(doc["id"], {name: numeric})
    else:
        gates = get_gates()
        gates.update({name: numeric})
        col.insert({"id": _GATE_DOC_ID, **gates})
    return {"status": "ok", **get_gates()}

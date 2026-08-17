"""Fixed Income / Rates engine (spec-aligned, additive).

Implements the spec-named surface: ``yield_curve()``, ``rates()`` and
``spreads()`` including the full overnight-rate set (SOFR, EFFR, ESTR, SONIA)
plus treasury-EFFR and HQM corporate spreads. Uses the FRED API
(``FRED_API_KEY``); when the key is missing or the network fails the functions
degrade to flagged simulator values so the endpoints never crash.
"""
import os
import time

import httpx

from ...foundation.logger import logger

FRED_API_KEY = os.environ.get("FRED_API_KEY", "").strip()
FRED_BASE = "https://api.stlouisfed.org/fred"

TREASURY_SERIES = {
    "us2y": "DGS2",
    "us5y": "DGS5",
    "us10y": "DGS10",
    "us30y": "DGS30",
}

OVERNIGHT_RATES = {
    "sofr": "SOFR",
    "effr": "EFFR",
    "estr": "ESTR",
    "sonia": "IUDSOIA",
}

_CACHE = {}
_CACHE_TTL = 30 * 60


def _fred_series(series_id, count=120):
    if not FRED_API_KEY:
        return []
    key = ("fred-engine", series_id, count)
    cached = _CACHE.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]
    try:
        resp = httpx.get(
            f"{FRED_BASE}/series/observations",
            params={"series_id": series_id, "api_key": FRED_API_KEY,
                    "file_type": "json", "sort_order": "asc",
                    "observation_start": "2015-01-01"},
            timeout=15,
        )
        resp.raise_for_status()
        out = []
        for o in resp.json().get("observations", []):
            v = o.get("value")
            if v is None or v == ".":
                continue
            try:
                out.append({"date": o["date"], "value": float(v)})
            except (TypeError, ValueError):
                continue
        out = out[-count:]
        _CACHE[key] = (time.time(), out)
        return out
    except Exception as exc:  # pragma: no cover - defensive
        logger.warn("FRED engine series %s failed: %s", series_id, exc)
        return []


def _latest(series):
    return series[-1] if series else None


def _sim_rates():
    return {
        "sofr": 5.31,
        "effr": 5.33,
        "estr": 3.85,
        "sonia": 4.85,
        "note": "FRED_API_KEY not configured — simulated overnight rates shown",
    }


def yield_curve():
    """Treasury yield curve (2Y, 5Y, 10Y, 30Y) from FRED."""
    now = int(time.time() * 1000)
    points = []
    source = "fred"
    for name, sid in TREASURY_SERIES.items():
        series = _fred_series(sid, count=5)
        latest = _latest(series)
        points.append({
            "maturity": name,
            "label": f"{name.upper()}",
            "yieldPct": latest["value"] if latest else None,
            "date": latest["date"] if latest else None,
            "source": source if latest else "simulator",
        })
    if all(p["yieldPct"] is None for p in points):
        source = "simulator"
        base = {"us2y": 4.31, "us5y": 4.18, "us10y": 4.28, "us30y": 4.58}
        for p in points:
            p["yieldPct"] = base[p["maturity"]]
            p["source"] = "simulator"
    return {"timestamp": now, "source": source, "curve": points,
            "note": "" if source == "fred" else "FRED_API_KEY not configured — simulated curve shown"}


def rates():
    """Overnight rates: SOFR, EFFR, ESTR, SONIA."""
    now = int(time.time() * 1000)
    out = {}
    source = "fred"
    for name, sid in OVERNIGHT_RATES.items():
        latest = _latest(_fred_series(sid, count=5))
        out[name] = {"value": latest["value"] if latest else None,
                     "date": latest["date"] if latest else None}
    if all(v["value"] is None for v in out.values()):
        source = "simulator"
        sim = _sim_rates()
        for name in OVERNIGHT_RATES:
            out[name] = {"value": sim[name], "date": None, "source": "simulator"}
    return {"timestamp": now, "source": source, "rates": out}


def spreads():
    """Treasury-EFFR spread and HQM corporate spread."""
    now = int(time.time() * 1000)
    us10 = _latest(_fred_series("DGS10", count=5))
    effr = _latest(_fred_series("EFFR", count=5))
    hqm = _latest(_fred_series("HQMCB10YR", count=5))

    def _val(item):
        return item["value"] if item else None

    treasuryEffr = round(_val(us10) - _val(effr), 3) if (us10 and effr) else None
    hqmSpread = round(_val(hqm) - _val(us10), 3) if (hqm and us10) else None

    source = "fred"
    if treasuryEffr is None or hqmSpread is None:
        source = "simulator"
        treasuryEffr = -1.02 if treasuryEffr is None else treasuryEffr
        hqmSpread = 0.84 if hqmSpread is None else hqmSpread

    return {
        "timestamp": now,
        "source": source,
        "spreads": {
            "treasuryEffr": treasuryEffr,
            "hqmCorporate": hqmSpread,
            "note": "" if source == "fred" else "FRED_API_KEY not configured — simulated spreads shown",
        },
    }

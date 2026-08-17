"""Fixed Income intelligence (additive pro module).

Sources from the St. Louis Fed FRED API (open source, ALPHA license) using
FRED_API_KEY. When the key is missing or the network is unreachable the module
degrades gracefully to simulator data flagged as such — the API never crashes.
"""
import os
import time

import httpx

from ...foundation.logger import logger

FRED_API_KEY = os.environ.get("FRED_API_KEY", "").strip()
FRED_BASE = "https://api.stlouisfed.org/fred"

TREASURY_SERIES = {
    "us1m": "DTB1M",
    "us3m": "DTB3M",
    "us6m": "DTB6M",
    "us1y": "DGS1",
    "us2y": "DGS2",
    "us3y": "DGS3",
    "us5y": "DGS5",
    "us7y": "DGS7",
    "us10y": "DGS10",
    "us20y": "DGS20",
    "us30y": "DGS30",
}

SPREAD_SERIES = {
    "2s10s": "T10Y2Y",
    "3m10y": "T10Y3M",
    "10s30s": "T10Y30Y",
}

MONEY_RATES = {
    "fedFunds": "DFF",
    "sOFR": "SOFR",
    "prime": "DPRIME",
    "libor3m": "USD3MTD156N",
}

COMMODITY_CPI = {
    "breakeven5y": "T5YIE",
    "breakeven10y": "T10YIE",
}

_CACHE = {}
_CACHE_TTL = 30 * 60


def _fred_series(series_id, count=120):
    """Fetch a FRED observation series. Returns list of {date, value} or []."""
    if not FRED_API_KEY:
        return []
    key = ("fred", series_id, count)
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
        data = resp.json()
        obs = data.get("observations", [])
        out = []
        for o in obs:
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
        logger.warn("FRED series %s failed: %s", series_id, exc)
        return []


def _latest(series):
    if not series:
        return None
    return series[-1]


def _simulate_yields():
    """Deterministic-ish simulated yield curve (used when FRED key missing)."""
    now = int(time.time() * 1000)
    base = {
        "us1m": 4.85, "us3m": 4.72, "us6m": 4.55, "us1y": 4.38,
        "us2y": 4.31, "us3y": 4.21, "us5y": 4.18, "us7y": 4.20,
        "us10y": 4.28, "us20y": 4.52, "us30y": 4.58,
    }
    curve = []
    for maturity, name in sorted(TREASURY_SERIES.items(), key=lambda kv: len(kv[0])):
        curve.append({
            "maturity": maturity,
            "label": f"{maturity.upper()}",
            "yieldPct": base[maturity],
            "source": "simulator",
        })
    return {
        "timestamp": now,
        "source": "simulator",
        "curve": curve,
        "spreads": {
            "2s10s": round(base["us10y"] - base["us2y"], 2),
            "3m10y": round(base["us10y"] - base["us3m"], 2),
            "10s30s": round(base["us30y"] - base["us10y"], 2),
        },
        "rates": {"fedFunds": 5.33, "sOFR": 5.31, "prime": 8.50},
        "note": "FRED_API_KEY not configured — showing simulated curve. Add FRED_API_KEY for live data.",
    }


def get_treasury_curve():
    """Full yield curve with spreads + money rates."""
    now = int(time.time() * 1000)
    series_map = {}
    for name, sid in TREASURY_SERIES.items():
        series_map[name] = _fred_series(sid)

    if not any(series_map.values()):
        return _simulate_yields()

    curve = []
    for maturity, sid in TREASURY_SERIES.items():
        series = series_map.get(maturity) or []
        latest = _latest(series)
        curve.append({
            "maturity": maturity,
            "label": sid,
            "yieldPct": latest["value"] if latest else None,
            "date": latest["date"] if latest else None,
            "source": "fred",
        })
    spreads = {}
    for name, sid in SPREAD_SERIES.items():
        series = _fred_series(sid)
        latest = _latest(series)
        spreads[name] = latest["value"] if latest else None
    rates = {}
    for name, sid in MONEY_RATES.items():
        series = _fred_series(sid)
        latest = _latest(series)
        rates[name] = latest["value"] if latest else None
    breakevens = {}
    for name, sid in COMMODITY_CPI.items():
        series = _fred_series(sid)
        latest = _latest(series)
        breakevens[name] = latest["value"] if latest else None
    return {
        "timestamp": now,
        "source": "fred",
        "curve": curve,
        "spreads": spreads,
        "rates": rates,
        "breakevens": breakevens,
        "note": "Live FRED data",
    }


def get_yield_curve_history(series_id="DGS10", count=250):
    """Historical yield series for charting."""
    now = int(time.time() * 1000)
    name = next((k for k, v in TREASURY_SERIES.items() if v == series_id), series_id)
    series = _fred_series(series_id, count)
    if not series:
        # simulated history for a smooth chart
        import random
        base = {"DGS10": 4.28, "DGS2": 4.31, "DGS30": 4.58, "DGS5": 4.18}.get(series_id, 4.2)
        ts = now
        hist = []
        for i in range(count, 0, -1):
            ts -= 86400000
            hist.append({"date": time.strftime("%Y-%m-%d", time.localtime(ts / 1000)),
                         "value": round(base + (random.random() - 0.5) * 0.8, 3)})
        return {"timestamp": now, "series": series_id, "name": name, "source": "simulator",
                "data": hist, "note": "Simulated history (FRED key missing or series unavailable)"}
    return {"timestamp": now, "series": series_id, "name": name, "source": "fred", "data": series}

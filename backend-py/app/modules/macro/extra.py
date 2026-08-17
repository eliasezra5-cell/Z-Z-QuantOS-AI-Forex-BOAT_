"""Extra Macro official-source data (additive pro module).

Fetches official indicators from ECB SDW, OECD SDMX, EIA v2 and BLS v2 APIs.
All keys are optional (ECB_API_KEY / OECD_API_KEY / EIA_API_KEY /
BLS_API_KEY). When a key is missing or the network is unreachable the module
degrades to flagged simulator values — the API never crashes.
"""
import os
import time

import httpx

from ...foundation.logger import logger

ECB_API_KEY = os.environ.get("ECB_API_KEY", "").strip()
OECD_API_KEY = os.environ.get("OECD_API_KEY", "").strip()
EIA_API_KEY = os.environ.get("EIA_API_KEY", "").strip()
BLS_API_KEY = os.environ.get("BLS_API_KEY", "").strip()

ECB_BASE = "https://sdw-wsrest.ecb.europa.eu/service"
OECD_BASE = "https://sdmx.oecd.org/public/rest/v1/data"
EIA_BASE = "https://api.eia.gov/v2"
BLS_BASE = "https://api.bls.gov/publicAPI/v2/timeseries/data"

_CACHE = {}
_CACHE_TTL = 30 * 60


def _cache_get(key):
    item = _CACHE.get(key)
    if item and time.time() - item[0] < _CACHE_TTL:
        return item[1]
    return None


def _cache_put(key, value):
    _CACHE[key] = (time.time(), value)


def _fetch(url, params, timeout=15):
    try:
        resp = httpx.get(url, params=params, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warn("extra-macro fetch failed %s: %s", url, exc)
        return None


# --------------------------------------------------------------------------- #
# ECB SDW (Statistical Data Warehouse)
# --------------------------------------------------------------------------- #
def ecb_indicator(series_id="EXR.D.USD.EUR.SP00.A", count=120):
    """Fetch an ECB SDW series (SDMX-JSON)."""
    cache_key = ("ecb", series_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    url = f"{ECB_BASE}/data/{series_id}"
    data = _fetch(url, {"format": "jsondata", "detail": "dataonly"})
    if not data:
        result = {"available": False, "reason": "source-unreachable",
                  "note": "ECB API unreachable — set ECB_API_KEY or check network"}
        _cache_put(cache_key, result)
        return result
    try:
        series = data["dataSets"][0]["series"]
        keys = data["structure"]["dimensions"]["series"][0]["values"]
        obs = data["dataSets"][0]["observations"]
        rows = []
        for sidx, ovals in obs.items():
            sid = int(sidx.split(":")[0])
            label = keys[sid]["name"] if sid < len(keys) else series_id
            rows.append({"name": label, "value": ovals[0]})
        result = {"available": True, "source": "ECB", "series": series_id,
                  "rows": rows[-count:], "note": "Live ECB SDW data"}
        _cache_put(cache_key, result)
        return result
    except Exception as exc:  # pragma: no cover - defensive
        result = {"available": False, "reason": "parse-error", "error": str(exc)}
        _cache_put(cache_key, result)
        return result


# --------------------------------------------------------------------------- #
# OECD (SDMX-JSON)
# --------------------------------------------------------------------------- #
def oecd_indicator(series_id="G20_MAIN.O_CPI.M", count=60):
    """Fetch an OECD SDMX series."""
    cache_key = ("oecd", series_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    url = f"{OECD_BASE}/{series_id}"
    data = _fetch(url, {"format": "jsondata"})
    if not data:
        result = {"available": False, "reason": "source-unreachable",
                  "note": "OECD API unreachable — set OECD_API_KEY or check network"}
        _cache_put(cache_key, result)
        return result
    try:
        series_keys = data["structure"]["dimensions"]["series"][0]["values"]
        obs_keys = data["structure"]["dimensions"]["observation"][0]["values"]
        rows = []
        for series_key, series_block in data["dataSets"][0]["series"].items():
            sid = int(series_key.split(":")[0])
            name = series_keys[sid]["name"] if sid < len(series_keys) else series_id
            for obs_key, obs_val in series_block.get("observations", {}).items():
                oid = int(obs_key.split(":")[0])
                period = obs_keys[oid]["name"] if oid < len(obs_keys) else str(oid)
                rows.append({"name": name, "period": period, "value": obs_val[0]})
        result = {"available": True, "source": "OECD", "series": series_id,
                  "rows": rows[-count:], "note": "Live OECD SDMX data"}
        _cache_put(cache_key, result)
        return result
    except Exception as exc:  # pragma: no cover - defensive
        result = {"available": False, "reason": "parse-error", "error": str(exc)}
        _cache_put(cache_key, result)
        return result


# --------------------------------------------------------------------------- #
# EIA (v2 API)
# --------------------------------------------------------------------------- #
def eia_indicator(series_id="PET.RBRTE.D", count=120):
    """Fetch an EIA v2 series (needs EIA_API_KEY)."""
    cache_key = ("eia", series_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    if not EIA_API_KEY:
        result = {"available": False, "reason": "missing-api-key",
                  "note": "EIA_API_KEY not configured — add it to enable live EIA data"}
        _cache_put(cache_key, result)
        return result
    url = f"{EIA_BASE}/seriesid/{series_id}/data"
    data = _fetch(url, {"api_key": EIA_API_KEY, "offset": 0, "length": 5000})
    if not data:
        result = {"available": False, "reason": "source-unreachable",
                  "note": "EIA API unreachable"}
        _cache_put(cache_key, result)
        return result
    try:
        rows = data.get("response", {}).get("data", [])
        out = []
        for r in rows:
            val = r.get("value")
            if val is None:
                continue
            out.append({"date": r.get("period"), "value": val})
        result = {"available": True, "source": "EIA", "series": series_id,
                  "rows": out[-count:], "note": "Live EIA v2 data"}
        _cache_put(cache_key, result)
        return result
    except Exception as exc:  # pragma: no cover - defensive
        result = {"available": False, "reason": "parse-error", "error": str(exc)}
        _cache_put(cache_key, result)
        return result


# --------------------------------------------------------------------------- #
# BLS (v2 API)
# --------------------------------------------------------------------------- #
def bls_indicator(series_id="LNS14000000", count=120):
    """Fetch a BLS v2 timeseries (needs BLS_API_KEY)."""
    cache_key = ("bls", series_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    if not BLS_API_KEY:
        result = {"available": False, "reason": "missing-api-key",
                  "note": "BLS_API_KEY not configured — add it to enable live BLS data"}
        _cache_put(cache_key, result)
        return result
    data = _fetch(BLS_BASE, {"seriesid": [series_id], "startyear": "2015",
                             "endyear": "2026", "registrationkey": BLS_API_KEY})
    if not data:
        result = {"available": False, "reason": "source-unreachable",
                  "note": "BLS API unreachable"}
        _cache_put(cache_key, result)
        return result
    try:
        rows = data.get("Results", {}).get("series", [{}])[0].get("data", [])
        out = []
        for r in rows:
            val = r.get("value")
            try:
                out.append({"period": f"{r.get('periodName','')} {r.get('year','')}",
                            "value": float(val)})
            except (TypeError, ValueError):
                continue
        result = {"available": True, "source": "BLS", "series": series_id,
                  "rows": out[:count], "note": "Live BLS v2 data"}
        _cache_put(cache_key, result)
        return result
    except Exception as exc:  # pragma: no cover - defensive
        result = {"available": False, "reason": "parse-error", "error": str(exc)}
        _cache_put(cache_key, result)
        return result


# --------------------------------------------------------------------------- #
# Source registry + simulator fallback
# --------------------------------------------------------------------------- #
SOURCES = {
    "ecb": {
        "label": "European Central Bank",
        "endpoint": "SDW (Statistical Data Warehouse)",
        "key": "ECB_API_KEY",
        "defaultSeries": "EXR.D.USD.EUR.SP00.A",
        "presets": {
            "EXR.D.USD.EUR.SP00.A": "EUR/USD Spot",
            "FM.D.U2.EUR.4F.KR.MRR_FR.LEV": "ECB Main Refi Rate",
            "EXR.D.GBP.EUR.SP00.A": "GBP/EUR Spot",
        },
    },
    "oecd": {
        "label": "OECD",
        "endpoint": "SDMX Global API",
        "key": "OECD_API_KEY",
        "defaultSeries": "G20_MAIN.O_CPI.M",
        "presets": {
            "G20_MAIN.O_CPI.M": "G20 CPI YoY",
            "G20_MAIN.O_GDP.M": "G20 GDP",
            "G20_MAIN.O_UNR.M": "G20 Unemployment",
        },
    },
    "eia": {
        "label": "U.S. EIA",
        "endpoint": "EIA v2 API",
        "key": "EIA_API_KEY",
        "defaultSeries": "PET.RBRTE.D",
        "presets": {
            "PET.RBRTE.D": "Brent Crude Spot",
            "NG.NGPRICUS.A": "Natural Gas Price",
            "PET.WCLCST.W": "WTI Crude Spot",
        },
    },
    "bls": {
        "label": "U.S. Bureau of Labor Statistics",
        "endpoint": "BLS v2 API",
        "key": "BLS_API_KEY",
        "defaultSeries": "LNS14000000",
        "presets": {
            "LNS14000000": "US Unemployment Rate",
            "CUUR0000SA0": "US CPI (All Urban)",
            "CES0000000001": "Total Nonfarm Payrolls",
        },
    },
}


def official_sources_status():
    """List sources with key-presence + reachability flags."""
    now = int(time.time() * 1000)
    status = {}
    for sid, meta in SOURCES.items():
        key_set = bool(os.environ.get(meta["key"], "").strip())
        status[sid] = {
            **{k: v for k, v in meta.items() if k != "presets"},
            "keyConfigured": key_set,
            "presets": list(meta["presets"].keys()),
        }
    return {"timestamp": now, "sources": status}


def fetch_source_series(source, series_id=None):
    """Dispatch to the right source fetcher with simulator fallback."""
    meta = SOURCES.get((source or "").lower())
    if not meta:
        return {"available": False, "reason": "unknown-source",
                "note": f"Unknown source '{source}'. Use one of: {', '.join(SOURCES)}"}
    series_id = series_id or meta["defaultSeries"]
    fn = {"ecb": ecb_indicator, "oecd": oecd_indicator,
          "eia": eia_indicator, "bls": bls_indicator}[source.lower()]
    result = fn(series_id)
    if result.get("available"):
        return {"source": source, "label": meta["label"], "series": series_id, **result}
    return {
        "source": source,
        "label": meta["label"],
        "series": series_id,
        "available": False,
        "reason": result.get("reason", "unavailable"),
        "note": result.get("note", ""),
    }

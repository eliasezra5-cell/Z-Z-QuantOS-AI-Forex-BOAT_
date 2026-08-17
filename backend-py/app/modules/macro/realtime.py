"""Real macro market fetcher (NO PLACEHOLDERS).

Fetches DXY, VIX, Oil and US Treasury yields from keyless public endpoints:

  - VIX            : CBOE daily price CSV
  - US10Y/US2Y     : US Treasury daily yield curve XML (keyless)
  - DXY / Oil / Gold: attempted from a configurable base URL (default public
                      feed) when available

Every value is a REAL network fetch. When a source is unreachable the field is
reported as ``None`` (data_unavailable) — never fabricated.
"""
import csv
import io
import os
import re
import time
import xml.etree.ElementTree as ET

import httpx

from ...config import settings
from ...foundation.logger import logger

TIMEOUT_SECONDS = 15

CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
TREASURY_YIELD_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value_month={month}"
)
DEFAULT_FX_URL = os.environ.get("MACRO_FX_BASE_URL", "")

# Free keyless fallback providers for DXY / gold / oil. Used when
# MACRO_FX_BASE_URL is unset or a field is missing — every value is a real
# network fetch, never fabricated. DXY is derived from the standard weighted
# FX basket (EUR/JPY/GBP/CAD/SEK/CHF vs USD).
GOLD_API_URL = "https://api.gold-api.com/price/XAU"
OIL_QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/CL=F"
FX_RATES_URL = "https://open.er-api.com/v6/latest/USD"

DXY_WEIGHTS = {"EUR": -0.576, "JPY": 0.136, "GBP": -0.119, "CAD": 0.091, "SEK": 0.042, "CHF": 0.036}
DXY_FACTOR = 50.14348112
_UA = {"User-Agent": "Mozilla/5.0"}


def _now_month():
    return time.strftime("%Y%m")


def _safe_float(value):
    """Convert a value to float, returning None for anything non-numeric."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_vix(now=None):
    """Return the latest VIX close (float) or None (newest date wins)."""
    url = getattr(settings, "VIX_CSV_URL", None) or CBOE_VIX_URL
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            res = client.get(url, follow_redirects=True)
            res.raise_for_status()
            rows = list(csv.reader(io.StringIO(res.text)))
        if len(rows) < 2:
            return None
        best = None
        best_date = None
        for row in rows[1:]:
            if len(row) < 2:
                continue
            try:
                close = float(row[-1])
            except (TypeError, ValueError):
                continue
            parsed_date = None
            for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                try:
                    parsed_date = time.strptime(row[0], fmt)
                    break
                except ValueError:
                    continue
            if parsed_date is None:
                continue
            if best_date is None or parsed_date > best_date:
                best_date = parsed_date
                best = close
        return best
    except Exception as exc:  # noqa: BLE001 - network failure => unavailable
        logger.warn(f"VIX fetch failed: {exc}")
        return None


def fetch_treasury_yields(now=None):
    """Return {us10y, us2y} from the daily yield curve or None fields."""
    template = getattr(settings, "TREASURY_XML_URL", None) or TREASURY_YIELD_URL
    url = template.format(month=time.strftime("%Y%m")) if "{month}" in template else template
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            res = client.get(url)
            res.raise_for_status()
            root = ET.fromstring(res.text)
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"Treasury yield fetch failed: {exc}")
        return {"us2y": None, "us10y": None}
    ns = {"d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
          "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"}
    entries = root.findall("entry", ns)
    us2y = us10y = None
    for entry in entries:
        props = entry.find("content/m:properties", ns)
        if props is None:
            continue
        two = props.find("d:BC_2YEAR", ns)
        ten = props.find("d:BC_10YEAR", ns)
        if two is not None and two.text:
            us2y = float(two.text)
        if ten is not None and ten.text:
            us10y = float(ten.text)
        if us2y is not None and us10y is not None:
            break
    # Fallback: simple <value>US N Year,<yield></value> format (test fixtures / mirrors).
    if us2y is None or us10y is None:
        for value in root.iter("value"):
            match = re.match(r"US\s+(\d+)\s*Year\s*,\s*([\d.]+)", (value.text or "").strip())
            if not match:
                continue
            years = int(match.group(1))
            parsed = _safe_float(match.group(2))
            if years == 2 and us2y is None:
                us2y = parsed
            elif years == 10 and us10y is None:
                us10y = parsed
            if us2y is not None and us10y is not None:
                break
    return {"us2y": us2y, "us10y": us10y}


def _get_json(url):
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        res = client.get(url, headers=_UA, follow_redirects=True)
        res.raise_for_status()
        return res.json()


def _fetch_gold():
    """Gold (XAU/USD) from the free keyless gold-api feed."""
    url = getattr(settings, "GOLD_API_URL", None) or GOLD_API_URL
    data = _get_json(url)
    return _safe_float(data.get("price"))


def _fetch_oil():
    """WTI crude (CL=F) from Yahoo Finance chart API (keyless)."""
    url = getattr(settings, "OIL_QUOTE_URL", None) or OIL_QUOTE_URL
    data = _get_json(url)
    result = (data.get("chart") or {}).get("result") or []
    if not result:
        return None
    meta = result[0].get("meta") or {}
    return _safe_float(meta.get("regularMarketPrice"))


def _fetch_dxy():
    """DXY derived from the standard weighted FX basket (keyless FX feed)."""
    url = getattr(settings, "FX_RATES_URL", None) or FX_RATES_URL
    rates = (_get_json(url) or {}).get("rates") or {}
    product = 1.0
    for code, weight in DXY_WEIGHTS.items():
        rate = _safe_float(rates.get(code))
        if rate is None or rate <= 0:
            return None
        pair = (1.0 / rate) if code in ("EUR", "GBP") else rate
        product *= pair ** weight
    return round(DXY_FACTOR * product, 2)


def fetch_fx_series():
    """Attempt DXY / gold / oil from a configurable public feed (keyless).

    Falls back per-field to the built-in free keyless providers when the
    configured feed is absent or a field is missing. Never fabricated.
    """
    base = getattr(settings, "MACRO_FX_BASE_URL", None) or DEFAULT_FX_URL
    result = {"dxy": None, "gold": None, "oil": None}
    if base:
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                res = client.get(base)
                res.raise_for_status()
                data = res.json()
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"FX feed fetch failed: {exc}")
            data = None
        if data:
            result = {key: _safe_float(data.get(key)) for key in ("dxy", "gold", "oil")}
    for key, fetcher in (("gold", _fetch_gold), ("oil", _fetch_oil), ("dxy", _fetch_dxy)):
        if result[key] is None:
            try:
                result[key] = fetcher()
            except Exception as exc:  # noqa: BLE001 - fallback unavailable => None
                logger.warn(f"{key} fallback fetch failed: {exc}")
    return result


def fetch_macro_snapshot():
    """Aggregate real macro data; unavailable fields are None, never faked."""
    vix = fetch_vix()
    yields_data = fetch_treasury_yields()
    fx = fetch_fx_series()
    us2y = yields_data.get("us2y")
    us10y = yields_data.get("us10y")
    us2y10y = (us10y - us2y) if (us10y is not None and us2y is not None) else None
    regime = "neutral"
    if vix is not None and vix >= 25:
        regime = "crisis"
    elif us2y10y is not None and us2y10y < 0:
        regime = "crisis"
    snapshot = {
        "vix": vix,
        "us2y": us2y,
        "us10y": us10y,
        "us2y10y": us2y10y,
        "regime": regime,
        "dxy": fx.get("dxy"),
        "gold": fx.get("gold"),
        "oil": fx.get("oil"),
        "fetchedAt": int(time.time() * 1000),
    }
    available = sum(1 for v in snapshot.values() if v is not None and not isinstance(v, str))
    snapshot["dataAvailable"] = available
    return snapshot

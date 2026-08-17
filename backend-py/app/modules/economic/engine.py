"""Economic calendar engine mirroring the Node economic/engine.js."""
import math
import random
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db

EVENTS = [
    {"id": "cpi", "name": "Consumer Price Index", "currency": "USD", "country": "US", "impact": 3, "frequency": "monthly"},
    {"id": "ppi", "name": "Producer Price Index", "currency": "USD", "country": "US", "impact": 2, "frequency": "monthly"},
    {"id": "gdp", "name": "Gross Domestic Product", "currency": "USD", "country": "US", "impact": 3, "frequency": "quarterly"},
    {"id": "pmi", "name": "Manufacturing PMI", "currency": "USD", "country": "US", "impact": 2, "frequency": "monthly"},
    {"id": "nfp", "name": "Non-Farm Payrolls", "currency": "USD", "country": "US", "impact": 3, "frequency": "monthly"},
    {"id": "adp", "name": "ADP Employment Change", "currency": "USD", "country": "US", "impact": 2, "frequency": "monthly"},
    {"id": "fomc", "name": "FOMC Interest Rate Decision", "currency": "USD", "country": "US", "impact": 3, "frequency": "quarterly"},
    {"id": "interest_rate_us", "name": "Fed Interest Rate Decision", "currency": "USD", "country": "US", "impact": 3, "frequency": "monthly"},
    {"id": "fed_speech", "name": "Fed Chair Speech", "currency": "USD", "country": "US", "impact": 3, "frequency": "ad-hoc"},
    {"id": "ecb_rate", "name": "ECB Interest Rate Decision", "currency": "EUR", "country": "EU", "impact": 3, "frequency": "monthly"},
    {"id": "ecb_speech", "name": "ECB President Speech", "currency": "EUR", "country": "EU", "impact": 2, "frequency": "ad-hoc"},
    {"id": "boj_rate", "name": "BOJ Interest Rate Decision", "currency": "JPY", "country": "JP", "impact": 3, "frequency": "monthly"},
    {"id": "boe_rate", "name": "BOE Interest Rate Decision", "currency": "GBP", "country": "UK", "impact": 3, "frequency": "monthly"},
    {"id": "unemployment_us", "name": "US Unemployment Rate", "currency": "USD", "country": "US", "impact": 2, "frequency": "monthly"},
    {"id": "retail_sales", "name": "US Retail Sales", "currency": "USD", "country": "US", "impact": 2, "frequency": "monthly"},
    {"id": "inflation_eu", "name": "Eurozone Inflation Rate", "currency": "EUR", "country": "EU", "impact": 3, "frequency": "monthly"},
    {"id": "employment_uk", "name": "UK Employment Change", "currency": "GBP", "country": "UK", "impact": 2, "frequency": "monthly"},
    {"id": "trade_balance_cn", "name": "China Trade Balance", "currency": "CNY", "country": "CN", "impact": 2, "frequency": "monthly"},
]

FORECASTS = {
    "cpi": 3.2, "ppi": 2.1, "gdp": 2.4, "pmi": 51.2, "nfp": 185, "adp": 160, "fomc": 5.5, "interest_rate_us": 5.5,
    "fed_speech": None, "ecb_rate": 4.0, "ecb_speech": None, "boj_rate": 0.0, "boe_rate": 5.25, "unemployment_us": 3.9,
    "retail_sales": 0.3, "inflation_eu": 2.4, "employment_uk": 95, "trade_balance_cn": 68.5,
}

USD_DIRECTION_IDS = ["cpi", "ppi", "nfp", "gdp", "retail_sales"]

IMPACT_SCALES = {"high": 1.0, "medium": 0.6, "low": 0.3}
RISK_REGIMES = ("risk_on", "risk_off")
GOLD_BEARISH_EVENT_IDS = {"cpi", "nfp"}
GOLD_BULLISH_CATEGORIES = ("geopolit", "political", "conflict", "war", "health", "pandemic", "supply", "crisis", "terror")


def _impact_tier(event):
    impact = event.get("impact")
    if isinstance(impact, str):
        tier = str(impact).lower()
        return tier if tier in IMPACT_SCALES else "medium"
    impact = impact or 0
    if impact >= 3:
        return "high"
    if impact == 2:
        return "medium"
    return "low"


def _surprise(actual, forecast):
    if actual is not None and forecast is not None and forecast != 0:
        return (actual - forecast) / abs(forecast)
    return 0.0


def _hist_surprise_values(hist_events):
    values = []
    for e in hist_events or []:
        if isinstance(e, (int, float)):
            values.append(float(e))
        elif isinstance(e, dict):
            if e.get("actual") is not None and e.get("forecast") not in (None, 0):
                values.append((e["actual"] - e["forecast"]) / abs(e["forecast"]))
    return values


def _market_regime(market_regime):
    if market_regime:
        return str(market_regime)
    try:
        from ..macro.engine import detect_regime
        return detect_regime().get("regime")
    except Exception:  # noqa: BLE001
        return None


def surprise_normalization(event, actual, forecast, hist_events=None, market_regime=None, positioning=None):
    """Normalize an economic surprise against its own historical distribution."""
    surprise = _surprise(actual, forecast)
    hist = _hist_surprise_values(hist_events)
    if hist:
        mean = sum(hist) / len(hist)
        variance = sum((v - mean) ** 2 for v in hist) / len(hist)
        std = math.sqrt(variance)
        divisor = std if std > 1e-12 else 1.0
        z_score = (surprise - mean) / divisor
        dispersion = (std / abs(mean)) if mean != 0 else 0.0
    else:
        z_score = surprise
        dispersion = 0.0
    event_scale = IMPACT_SCALES[_impact_tier(event)]
    regime = _market_regime(market_regime)
    regime_adjustment = 0.7 if regime in RISK_REGIMES else 1.0
    positioning_adjustment = 1.0
    if positioning is not None:
        position = max(0.0, min(1.0, float(positioning)))
        positioning_adjustment = 1.0 - 0.5 * position
    dispersion_factor = 1.0 + min(dispersion, 1.0)
    normalized_impact = z_score * event_scale * regime_adjustment * positioning_adjustment * dispersion_factor
    normalized_impact = max(-3.0, min(3.0, normalized_impact))
    return {
        "zScore": round(z_score, 4),
        "eventScale": round(event_scale, 4),
        "dispersion": round(dispersion, 4),
        "regimeAdjustment": round(regime_adjustment, 4),
        "positioning": round(positioning_adjustment, 4),
        "normalizedImpact": round(normalized_impact, 4),
    }


def gold_impact(event, actual, forecast, gold_price=None, hist_events=None, market_regime=None, positioning=None):
    """Commodity-correlation gold read for an economic release."""
    surprise = _surprise(actual, forecast)
    norm = surprise_normalization(event, actual, forecast, hist_events, market_regime, positioning)
    z_score = norm["zScore"]
    category = str(event.get("category") or "").lower()
    eid = str(event.get("id") or "").lower()
    currency = event.get("currency")
    tier = _impact_tier(event)
    if gold_price is None:
        gold_price = 0

    direction = "neutral"
    if any(k in category for k in GOLD_BULLISH_CATEGORIES):
        direction = "bullish"
    elif eid in GOLD_BEARISH_EVENT_IDS or (currency == "USD" and tier == "high"):
        if surprise > 0.01:
            direction = "bearish"
        elif surprise < -0.01:
            direction = "bullish"

    sign = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}[direction]
    magnitude = round(min(abs(z_score), 3.0) * norm["eventScale"] * 100) / 100
    if magnitude == 0:
        magnitude = round(norm["eventScale"] * 0.5 * 100) / 100
    return {
        "goldImpact": round(sign * magnitude * 100) / 100,
        "goldDirection": direction,
        "magnitude": magnitude,
    }


def _lookup_hist_events(event):
    try:
        eid = event.get("id")
        if not eid:
            return []
        items = db.collection("economic_events").find({"id": eid})
        return [e for e in items if e.get("status") == "released" and e.get("actual") is not None]
    except Exception:  # noqa: BLE001
        return []


def ai_impact_analysis(event, actual, forecast, hist_events=None, market_regime=None, positioning=None):
    if actual is not None and forecast is not None and forecast != 0:
        surprise = (actual - forecast) / abs(forecast)
    else:
        surprise = 0
    volatility_expectation = min(abs(surprise) * 2.5 + 0.5, 3)
    direction = "neutral"
    if surprise > 0.01 and event["id"] in USD_DIRECTION_IDS:
        direction = "bearish-usd"
    if surprise < -0.01 and event["id"] in USD_DIRECTION_IDS:
        direction = "bullish-usd"
    if hist_events is None:
        hist_events = _lookup_hist_events(event)
    norm = surprise_normalization(event, actual, forecast, hist_events, market_regime, positioning)
    gold = gold_impact(event, actual, forecast, None, hist_events, market_regime, positioning)
    return {
        "surprise": round(surprise * 100) / 100,
        "volatilityExpectation": round(volatility_expectation * 100) / 100,
        "direction": direction,
        "affectedCurrencies": [event["currency"]],
        "affectedInstruments": _currency_to_instruments(event["currency"]),
        "reasoning": f"Actual {actual if actual is not None else 'n/a'} vs forecast {forecast if forecast is not None else 'n/a'} for {event['name']}",
        "confidence": round((0.5 + min(abs(surprise), 0.5)) * 100) / 100,
        "surprisePct": round(surprise * 100) / 100,
        "expectedVolatility": round(volatility_expectation * 100) / 100,
        "impactScore": round(min(abs(norm["zScore"]), 3.0) * 100) / 100,
        "zScore": norm["zScore"],
        "eventScale": norm["eventScale"],
        "dispersion": norm["dispersion"],
        "regimeAdjustment": norm["regimeAdjustment"],
        "positioning": norm["positioning"],
        "normalizedImpact": norm["normalizedImpact"],
        "goldImpact": gold,
    }


def with_ai_fields(event):
    """Surface the ai-derived surprise/gold fields on the event row itself."""
    ai = event.get("ai") or {}
    merged = dict(event)
    for key in (
        "surprise", "surprisePct", "expectedVolatility", "zScore", "eventScale",
        "dispersion", "regimeAdjustment", "positioning", "normalizedImpact", "impactScore",
        "direction", "confidence",
    ):
        if key in ai:
            merged[key] = ai[key]
    gold = ai.get("goldImpact")
    if isinstance(gold, dict):
        merged["goldImpact"] = gold.get("goldImpact")
        merged["goldDirection"] = gold.get("goldDirection")
        merged["magnitude"] = gold.get("magnitude")
    elif gold is not None:
        merged["goldImpact"] = gold
    return merged


def _currency_to_instruments(currency):
    mapping = {"USD": ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US500"], "EUR": ["EURUSD", "EURJPY"], "JPY": ["USDJPY", "EURJPY"], "GBP": ["GBPUSD"], "CNY": ["USDCNH"]}
    return mapping.get(currency) or [currency]


def init_economic_calendar():
    col = db.collection("economic_events")
    if col.count() == 0:
        now = int(time.time() * 1000)
        rows = []
        for day in range(-5, 10):
            for ev in EVENTS:
                if random.random() < 0.25:
                    t = now + day * 86400000 + random.randint(0, 15) * 3600000
                    forecast = FORECASTS[ev["id"]]
                    actual = forecast * (1 + (random.random() - 0.5) * 0.1) if day < 0 and forecast is not None else None
                    actual_rounded = round(actual * 100) / 100 if actual is not None else None
                    status = "released" if day < 0 else ("upcoming-today" if day == 0 else "upcoming")
                    rows.append({
                        **ev,
                        "time": t,
                        "forecast": forecast,
                        "actual": actual_rounded,
                        "previous": forecast * 0.98 if forecast is not None else None,
                        "status": status,
                        "ai": ai_impact_analysis(ev, actual, forecast),
                    })
        col.insert_many(rows)

    def _on_released(event):
        row = event["payload"]
        col.update(row["id"], {"status": "released", "actual": row.get("actual"), "ai": ai_impact_analysis(row, row.get("actual"), row.get("forecast"))})

    event_bus.on("economic:released", _on_released)
    logger.info("Economic calendar intelligence initialized")
    return get_economic_events


def get_economic_events(params=None):
    params = params or {}
    items = db.collection("economic_events").find({}, {"sort": ["time", "asc"]})
    if params.get("impact"):
        items = [e for e in items if e["impact"] >= int(params["impact"])]
    if params.get("currency"):
        items = [e for e in items if e["currency"] == params["currency"]]
    if params.get("status"):
        items = [e for e in items if e["status"] == params["status"]]
    return items[: int(params.get("limit", "60"))]


def get_high_impact_events():
    now = int(time.time() * 1000)
    items = db.collection("economic_events").find({})
    filtered = [e for e in items if e["impact"] == 3 and now - 3600000 <= e["time"] <= now + 72 * 3600000]
    return sorted(filtered, key=lambda e: e["time"])

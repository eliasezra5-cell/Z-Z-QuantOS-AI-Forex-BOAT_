"""Market data engine mirroring the Node marketdata/engine.js."""
import random
import re
import threading
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.provider_framework import providers
from .live_prices import get_live_quote, get_cached_candles, init_live_prices
from .quality_gates import validate_quote, cross_market_check, market_validation_context  # noqa: F401

INSTRUMENTS = [
    {"symbol": "EURUSD", "name": "Euro / US Dollar", "type": "forex", "pip": 0.0001, "digits": 5, "base": 1.1523, "volatility": 0.0009, "spread": 0.0001},
    {"symbol": "GBPUSD", "name": "British Pound / US Dollar", "type": "forex", "pip": 0.0001, "digits": 5, "base": 1.3454, "volatility": 0.0011, "spread": 0.00012},
    {"symbol": "USDJPY", "name": "US Dollar / Japanese Yen", "type": "forex", "pip": 0.01, "digits": 3, "base": 158.44, "volatility": 0.08, "spread": 0.012},
    {"symbol": "XAUUSD", "name": "Gold / US Dollar", "type": "commodities", "pip": 0.1, "digits": 2, "base": 4298.8, "volatility": 2.5, "spread": 0.2},
    {"symbol": "BTCUSD", "name": "Bitcoin / US Dollar", "type": "crypto", "pip": 1, "digits": 2, "base": 64578, "volatility": 220, "spread": 5},
    {"symbol": "ETHUSD", "name": "Ethereum / US Dollar", "type": "crypto", "pip": 0.1, "digits": 2, "base": 1911, "volatility": 14, "spread": 0.5},
    {"symbol": "US500", "name": "S&P 500 Index", "type": "stocks", "pip": 0.1, "digits": 2, "base": 7703, "volatility": 4.5, "spread": 0.3},
    {"symbol": "NAS100", "name": "Nasdaq 100 Index", "type": "stocks", "pip": 0.1, "digits": 2, "base": 26324, "volatility": 18, "spread": 1},
    {"symbol": "US30", "name": "Dow Jones 30 Index", "type": "stocks", "pip": 0.1, "digits": 2, "base": 53895, "volatility": 30, "spread": 2},
    {"symbol": "WTI", "name": "West Texas Intermediate Crude", "type": "commodities", "pip": 0.01, "digits": 2, "base": 77.66, "volatility": 0.09, "spread": 0.01},
    {"symbol": "AAPL", "name": "Apple Inc.", "type": "stocks", "pip": 0.01, "digits": 2, "base": 311.35, "volatility": 0.12, "spread": 0.01},
    {"symbol": "TSLA", "name": "Tesla Inc.", "type": "stocks", "pip": 0.01, "digits": 2, "base": 317.4, "volatility": 0.4, "spread": 0.02},
]

price_cache = {}
_price_lock = threading.Lock()
_last_quote = {}


def init_market_data():
    init_live_prices()
    providers.register({
        "id": "simulator",
        "category": "market-data",
        "name": "Simulated Market Data Provider",
        "enabled": True,
        "getPrice": lambda symbol: get_quote(symbol),
    })
    providers.register({
        "id": "mt5",
        "category": "market-data",
        "name": "MetaTrader 5 Provider",
        "enabled": False,
        "getPrice": _mt5_disabled,
    })
    for provider_id in ["binance", "bybit", "coinbase", "kraken", "oanda", "yahoo", "polygon", "alphavantage", "finnhub", "twelvedata"]:
        providers.register({
            "id": provider_id,
            "category": "market-data",
            "name": f"{provider_id[0].upper()}{provider_id[1:]} Market Provider",
            "enabled": False,
            "getPrice": _provider_requires_key(provider_id),
        })
    logger.info("Market data engine initialized with simulated provider")
    return get_quote


def _mt5_disabled():
    raise RuntimeError("MT5 provider disabled in demo mode")


def _provider_requires_key(provider_id):
    def _get_price():
        raise RuntimeError(f"{provider_id} provider requires API key")
    return _get_price


def get_instrument(symbol):
    for i in INSTRUMENTS:
        if i["symbol"] == symbol:
            return i
    return INSTRUMENTS[0]


def _seed_state(symbol):
    inst = get_instrument(symbol)
    return {
        "price": inst["base"] * (1 + (random.random() - 0.5) * 0.01),
        "lastTick": int(time.time() * 1000),
        "volatility": inst["volatility"],
        "drift": (random.random() - 0.5) * inst["volatility"] * 0.15,
    }


def _get_state(symbol):
    with _price_lock:
        if symbol not in price_cache:
            price_cache[symbol] = _seed_state(symbol)
        return price_cache[symbol]


def _next_price(symbol, state):
    live = get_live_quote(symbol)
    now = int(time.time() * 1000)
    if live and now - live["fetchedAt"] < 60000:
        state["price"] = live["price"]
        state["lastTick"] = now
        return state["price"]
    inst = get_instrument(symbol)
    dt = (now - state["lastTick"]) / 1000
    state["lastTick"] = now
    vol = state["volatility"] * (min(dt, 5) / 5) ** 0.5
    noise = (random.random() - 0.5) * 2 * vol
    shock = (random.random() - 0.5) * vol * 4 if random.random() < 0.005 else 0
    state["price"] += state["drift"] * min(dt, 60) + noise + shock
    state["price"] = max(state["price"], inst["base"] * 0.5)
    return state["price"]


def get_quote(symbol):
    inst = get_instrument(symbol)
    state = _get_state(symbol)
    live = get_live_quote(symbol)
    live_fresh = live and (int(time.time() * 1000) - live["fetchedAt"] < 60000)
    mid = live["price"] if live_fresh else _next_price(symbol, state)
    spread = inst["spread"]
    has_live_book = bool(live_fresh and live.get("bid") and live.get("ask") and live["ask"] > live["bid"])
    bid = live["bid"] if has_live_book else mid - spread / 2
    ask = live["ask"] if has_live_book else mid + spread / 2
    rounded = lambda v: round(v, inst["digits"])
    change24h = None
    if live_fresh and live.get("change24h") is not None:
        change24h = round(live["change24h"], 3)
    else:
        change24h = round((mid - inst["base"]) / inst["base"] * 100, 3)
    quote = {
        "symbol": symbol,
        "bid": rounded(bid),
        "ask": rounded(ask),
        "price": rounded(mid),
        "spread": round(spread, inst["digits"]),
        "change24h": change24h,
        "source": live["source"] if live_fresh else "simulator",
        "volume": random.randint(500, 5500),
        "timestamp": int(time.time() * 1000),
    }
    return _annotate_quality_gates(quote)


def _annotate_quality_gates(quote):
    """Add additive quality-gate metadata to a quote.

    Failing hard gates only flag the quote (qualityGates / gateFailures /
    qualityOk) — the quote is still returned so callers can fall back to it.
    """
    with _price_lock:
        prev = _last_quote.get(quote["symbol"])
        res = validate_quote(quote, prev)
        _last_quote[quote["symbol"]] = quote
    quote["qualityGates"] = res["gates"]
    quote["gateFailures"] = res["failedGates"]
    quote["qualityOk"] = res["valid"]
    return quote


def get_order_book(symbol, depth=10):
    quote = get_quote(symbol)
    bids = []
    asks = []
    for i in range(1, depth + 1):
        bids.append({"price": quote["bid"] - i * quote["spread"], "size": random.randint(5, 55)})
        asks.append({"price": quote["ask"] + i * quote["spread"], "size": random.randint(5, 55)})
    return {"symbol": symbol, "timestamp": int(time.time() * 1000), "bids": bids, "asks": asks}


def get_trades(symbol, count=50):
    trades = []
    state = _get_state(symbol)
    price = state["price"]
    inst = get_instrument(symbol)
    now = int(time.time() * 1000)
    for i in range(count):
        price += (random.random() - 0.5) * inst["volatility"] * 0.4
        t = now - (count - i) * 1000
        trades.append({
            "symbol": symbol,
            "price": round(price, inst["digits"]),
            "size": random.randint(1, 21),
            "side": "buy" if random.random() > 0.5 else "sell",
            "time": t,
            "id": f"{symbol}-{t}",
        })
    return trades


def tf_to_ms(tf):
    units = {"M": 60000, "H": 3600000, "D": 86400000, "W": 604800000}
    m = re.search(r"(\d+)([MHDW])", str(tf))
    if not m:
        return 3600000
    num = int(m.group(1))
    unit = m.group(2)
    return num * units.get(unit, 60000)


def generate_candles(symbol, timeframe="H1", count=300):
    real = get_cached_candles(symbol, timeframe, count)
    if real and len(real) >= min(count, 20):
        return real[-count:]
    inst = get_instrument(symbol)
    tf_ms = tf_to_ms(timeframe)
    candles = []
    price = inst["base"] * (1 + (random.random() - 0.5) * 0.01)
    now = int(time.time() * 1000)
    vol_scale = (tf_ms / 3600000) ** 0.5
    trend = (random.random() - 0.5) * inst["volatility"] * 0.1
    for i in range(count, 0, -1):
        t = now - i * tf_ms
        open_price = price
        if random.random() < 0.05:
            trend = (random.random() - 0.5) * inst["volatility"] * 0.2
        drift = trend
        move = drift + (random.random() - 0.5) * inst["volatility"] * 2 * vol_scale
        price = max(open_price + move, inst["base"] * 0.2)
        wick = (random.random() - 0.5) * inst["volatility"] * 0.8 * vol_scale
        high = max(open_price, price) + abs(wick) * 0.6
        low = min(open_price, price) - abs(wick) * 0.6
        volume = random.randint(800, 4800) * vol_scale
        candles.append({
            "time": t,
            "open": round(open_price, inst["digits"]),
            "high": round(high, inst["digits"]),
            "low": round(low, inst["digits"]),
            "close": round(price, inst["digits"]),
            "volume": volume,
            "symbol": symbol,
            "timeframe": timeframe,
        })
    return candles


def get_market_session():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    utc = now.hour + now.minute / 60.0
    sessions = [
        {"name": "Sydney", "open": 21, "close": 6, "active": utc >= 21 or utc < 6},
        {"name": "Tokyo", "open": 0, "close": 9, "active": 0 <= utc < 9},
        {"name": "London", "open": 7, "close": 16, "active": 7 <= utc < 16},
        {"name": "New York", "open": 12, "close": 21, "active": 12 <= utc < 21},
    ]
    return {
        "utcTime": f"{utc:.1f}",
        "sessions": sessions,
        "activeSessions": [s["name"] for s in sessions if s["active"]],
    }


_loop_started = False


def generate_market_data_loop():
    global _loop_started
    if _loop_started:
        return
    _loop_started = True

    def _tick_loop():
        while True:
            time.sleep(1)
            for inst in INSTRUMENTS:
                quote = get_quote(inst["symbol"])
                event_bus.emit("market:tick", quote)

    t = threading.Thread(target=_tick_loop, daemon=True)
    t.start()
    logger.info("Market data live stream started (1s ticks)")

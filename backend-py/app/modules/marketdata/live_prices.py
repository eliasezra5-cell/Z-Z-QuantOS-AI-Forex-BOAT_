"""Live price providers (Binance + Yahoo Finance) mirroring livePrices.js."""
import threading
import time

import httpx

from ...foundation.logger import logger

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

LIVE_MAP = {
    "EURUSD": {"yahoo": "EURUSD=X", "binance": None, "type": "forex"},
    "GBPUSD": {"yahoo": "GBPUSD=X", "binance": None, "type": "forex"},
    "USDJPY": {"yahoo": "USDJPY=X", "binance": None, "type": "forex"},
    "XAUUSD": {"yahoo": "GC=F", "binance": None, "type": "commodity"},
    "BTCUSD": {"yahoo": None, "binance": "BTCUSDT", "type": "crypto"},
    "ETHUSD": {"yahoo": None, "binance": "ETHUSDT", "type": "crypto"},
    "US500": {"yahoo": "^GSPC", "binance": None, "type": "index"},
    "NAS100": {"yahoo": "^IXIC", "binance": None, "type": "index"},
    "US30": {"yahoo": "^DJI", "binance": None, "type": "index"},
    "WTI": {"yahoo": "CL=F", "binance": None, "type": "commodity"},
    "AAPL": {"yahoo": "AAPL", "binance": None, "type": "stock"},
    "TSLA": {"yahoo": "TSLA", "binance": None, "type": "stock"},
}

quote_cache = {}
candle_cache = {}
_quote_lock = threading.Lock()
_candle_lock = threading.Lock()
QUOTE_TTL = 30000
CANDLE_TTL = 300000


def _now_ms():
    return int(time.time() * 1000)


def fetch_json(url, timeout_ms=12000):
    with httpx.Client(timeout=timeout_ms / 1000.0, follow_redirects=True) as client:
        res = client.get(url, headers={"User-Agent": UA, "Accept": "application/json"})
        res.raise_for_status()
        return res.json()


def _fetch_binance_quotes():
    pairs = [(sym, m["binance"]) for sym, m in LIVE_MAP.items() if m.get("binance")]
    if not pairs:
        return {}
    symbols_json = "[" + ",".join(f'"{b}"' for _, b in pairs) + "]"
    url = f"https://api.binance.com/api/v3/ticker/24hr?symbols={symbols_json}"
    try:
        tickers = fetch_json(url)
    except Exception:
        return {}
    if not isinstance(tickers, list):
        return {}
    out = {}
    for sym, b in pairs:
        t = next((x for x in tickers if x.get("symbol") == b), None)
        if not t:
            continue
        try:
            price = float(t.get("lastPrice") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out[sym] = {
            "price": price,
            "bid": _safe_float(t.get("bidPrice"), price),
            "ask": _safe_float(t.get("askPrice"), price),
            "prevClose": _safe_float(t.get("prevClosePrice"), price),
            "change24h": _safe_float(t.get("priceChangePercent"), 0),
            "source": "binance",
            "fetchedAt": _now_ms(),
        }
    return out


def _safe_float(value, fallback):
    try:
        v = float(value)
        return v if v is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _fetch_yahoo_quote(sym, yahoo_sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}?interval=1d&range=2d"
    try:
        j = fetch_json(url)
    except Exception:
        return None
    try:
        meta = j["chart"]["result"][0]["meta"]
    except (KeyError, IndexError, TypeError):
        return None
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    prev = meta.get("chartPreviousClose") or meta.get("previousClose") or price
    try:
        price = float(price)
        prev = float(prev)
    except (TypeError, ValueError):
        return None
    return {
        "price": price,
        "bid": price,
        "ask": price,
        "prevClose": prev,
        "change24h": ((price - prev) / prev) * 100 if prev else 0,
        "source": "yahoo",
        "fetchedAt": _now_ms(),
    }


def refresh_quotes():
    results = {}
    for sym, m in LIVE_MAP.items():
        if m.get("binance"):
            continue
        try:
            q = _fetch_yahoo_quote(sym, m["yahoo"])
            if q:
                results[sym] = q
        except Exception:
            pass
    try:
        results.update(_fetch_binance_quotes())
    except Exception:
        pass
    now = _now_ms()
    with _quote_lock:
        for sym, q in results.items():
            if 0 < q["price"] < 1e7:
                quote_cache[sym] = {**q, "fetchedAt": now}
    if results:
        logger.info(f"Live prices refreshed: {len(results)} symbols")
    return results


TF_INTERVAL = {
    "M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
    "H1": "60m", "H4": "60m",
    "D1": "1d", "W1": "1wk",
}
TF_RANGE = {
    "M1": "1d", "M5": "5d", "M15": "5d", "M30": "5d",
    "H1": "3mo", "H4": "3mo",
    "D1": "1y", "W1": "5y",
}

_prefetch_queue = set()


def normalize_tf(timeframe):
    import re
    tf = str(timeframe or "H1").upper()
    m = re.match(r"^(\d+)?([MHDW])$", tf)
    if not m:
        return "H1"
    num = int(m.group(1) or "1")
    unit = m.group(2)
    if unit == "M" and num < 60:
        return f"M{num}"
    if unit == "M":
        return "H1"
    if unit == "H":
        return "H1" if num <= 1 else ("H4" if num <= 4 else "D1")
    if unit == "D":
        return "D1"
    return "W1"


def _fetch_candles_into_cache(symbol, tf):
    meta = LIVE_MAP.get(symbol)
    if not meta or not meta.get("yahoo"):
        return
    key = f"{symbol}|{tf}"
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{meta['yahoo']}"
        f"?interval={TF_INTERVAL[tf]}&range={TF_RANGE[tf]}&includePrePost=false"
    )
    try:
        j = fetch_json(url)
    except Exception:
        return
    try:
        r = j["chart"]["result"][0]
    except (KeyError, IndexError, TypeError):
        return
    ts = r.get("timestamp") or []
    quote = (r.get("indicators", {}).get("quote") or [None])[0]
    if not quote or not ts:
        return
    candles = []
    for i in range(len(ts)):
        o, h, l = quote.get("open"), quote.get("high"), quote.get("low")
        c = quote.get("close")
        try:
            o, h, l, c = float(o[i]), float(h[i]), float(l[i]), float(c[i])
        except (TypeError, IndexError, ValueError):
            continue
        if o == 0:
            continue
        v = quote.get("volume")
        volume = float(v[i]) if (v and v[i] is not None) else 0
        candles.append({
            "time": ts[i] * 1000,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": volume,
            "symbol": symbol,
            "timeframe": tf,
            "source": "yahoo",
        })
    if candles:
        with _candle_lock:
            candle_cache[key] = {"at": _now_ms(), "data": candles}


PREFETCH_TFS = ["H1", "D1"]


def get_cached_candles(symbol, timeframe="H1", count=200):
    meta = LIVE_MAP.get(symbol)
    if not meta or not meta.get("yahoo"):
        return None
    tf = normalize_tf(timeframe)
    key = f"{symbol}|{tf}"
    with _candle_lock:
        cached = candle_cache.get(key)
    if cached and _now_ms() - cached["at"] < CANDLE_TTL:
        return cached["data"][-count:]
    if key not in _prefetch_queue:
        _prefetch_queue.add(key)

        def _done():
            _prefetch_queue.discard(key)

        try:
            _fetch_candles_into_cache(symbol, tf)
        except Exception:
            pass
        finally:
            _done()
    return None


def get_live_quote(symbol):
    q = quote_cache.get(symbol)
    if not q:
        return None
    if _now_ms() - q["fetchedAt"] > QUOTE_TTL * 3:
        return None
    return q


def get_live_status():
    all_quotes = list(quote_cache.values())
    return {
        "enabled": True,
        "symbols": list(quote_cache.keys()),
        "source": "binance+yahoo",
        "refreshMs": QUOTE_TTL,
        "fetchedAt": all_quotes[0]["fetchedAt"] if all_quotes else None,
    }


def prefetch_candles():
    for sym in LIVE_MAP.keys():
        for tf in PREFETCH_TFS:
            get_cached_candles(sym, tf, 200)


_started = False
_startup_lock = threading.Lock()


def init_live_prices():
    global _started
    with _startup_lock:
        if _started:
            return
        _started = True
    try:
        refresh_quotes()
    except Exception:
        pass

    def _quote_loop():
        while True:
            time.sleep(QUOTE_TTL / 1000.0)
            try:
                refresh_quotes()
            except Exception:
                pass

    def _candle_loop():
        while True:
            time.sleep(CANDLE_TTL / 1000.0)
            try:
                prefetch_candles()
            except Exception:
                pass

    prefetch_candles()
    t1 = threading.Thread(target=_quote_loop, daemon=True)
    t1.start()
    t2 = threading.Thread(target=_candle_loop, daemon=True)
    t2.start()
    logger.info("Live price provider started (Binance + Yahoo Finance, 30s refresh)")

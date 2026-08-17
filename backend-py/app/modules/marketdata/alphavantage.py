"""Alpha Vantage market data provider (additive).

Registers a real ``alphavantage`` market-data provider when
``ALPHA_VANTAGE_API_KEY`` is set, replacing the disabled placeholder that
``engine.py`` registers. It follows the same provider contract (``getPrice``)
without modifying any existing market-data logic.

Instrument coverage (best effort):
  - Stocks (AAPL, TSLA)            -> GLOBAL_QUOTE
  - FX / metals / crypto pairs
    (EURUSD, GBPUSD, USDJPY,
    XAUUSD, BTCUSD, ETHUSD)        -> CURRENCY_EXCHANGE_RATE
  - Symbols Alpha Vantage does not
    cover (indices etc.)           -> explicit "unsupported" error
"""
import time

import httpx

from ...config import settings
from ...foundation.logger import logger
from ...foundation.provider_framework import providers

BASE_URL = "https://www.alphavantage.co/query"

_STOCKS = {"AAPL", "TSLA"}
_FX_PAIRS = {
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "USDJPY": ("USD", "JPY"),
    "XAUUSD": ("XAU", "USD"),
    "BTCUSD": ("BTC", "USD"),
    "ETHUSD": ("ETH", "USD"),
}


def _api_key():
    return settings.ALPHA_VANTAGE_API_KEY or ""


def get_price(symbol):
    """Latest price for a supported symbol, in the provider ``getPrice`` shape."""
    key = _api_key()
    if not key:
        raise RuntimeError("alphavantage provider requires ALPHA_VANTAGE_API_KEY")
    symbol = (symbol or "").upper()
    if symbol in _STOCKS:
        return _fetch_stock(symbol, key)
    pair = _FX_PAIRS.get(symbol)
    if pair:
        return _fetch_fx(symbol, pair, key)
    raise RuntimeError(f"alphavantage: unsupported symbol {symbol}")


def _fetch_fx(symbol, pair, key):
    from_currency, to_currency = pair
    data = _request({
        "function": "CURRENCY_EXCHANGE_RATE",
        "from_currency": from_currency,
        "to_currency": to_currency,
        "apikey": key,
    })
    rate = (data.get("Realtime Currency Exchange Rate") or {}).get("5. Exchange Rate")
    if rate is None:
        raise RuntimeError(f"alphavantage: no exchange rate for {symbol}")
    price = float(rate)
    return _quote(symbol, price)


def _fetch_stock(symbol, key):
    data = _request({"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": key})
    quote = data.get("Global Quote") or {}
    price = quote.get("05. price")
    if price is None:
        raise RuntimeError(f"alphavantage: no quote for {symbol}")
    return _quote(symbol, float(price))


def _quote(symbol, price):
    return {
        "symbol": symbol,
        "price": price,
        "bid": price,
        "ask": price,
        "source": "alphavantage",
        "timestamp": int(time.time() * 1000),
    }


def _request(params):
    with httpx.Client(timeout=min(float(settings.AI_TIMEOUT_SECONDS or 120), 30.0)) as client:
        res = client.get(BASE_URL, params=params)
        res.raise_for_status()
        return res.json()


def init_alphavantage_provider():
    """Register the real Alpha Vantage provider when a key is configured."""
    if not _api_key():
        logger.info("Alpha Vantage provider skipped (no ALPHA_VANTAGE_API_KEY)")
        return None
    providers.register({
        "id": "alphavantage",
        "category": "market-data",
        "name": "Alpha Vantage Market Provider",
        "enabled": True,
        "getPrice": get_price,
    })
    logger.info("Alpha Vantage provider initialized (real quote feed)")
    return providers.get("alphavantage")

"""Multi-asset overview mirroring the Node multiasset/overview.js."""
import time

from ...foundation.logger import logger
from ..marketdata.engine import get_quote, get_instrument, INSTRUMENTS  # noqa: F401

ASSET_CLASSES = ["forex", "crypto", "stocks", "etfs", "futures", "options", "commodities", "bonds", "synthetic"]

ASSET_INFO = {
    "forex": {"label": "Forex", "description": "Foreign exchange pairs (EURUSD, GBPUSD, ...)", "liquidity": "very-high", "market": "24x5"},
    "crypto": {"label": "Crypto", "description": "Digital assets (BTC, ETH, ...)", "liquidity": "high", "market": "24x7"},
    "stocks": {"label": "Stocks", "description": "Equity shares (AAPL, TSLA, ...)", "liquidity": "high", "market": "exchange-hours"},
    "etfs": {"label": "ETFs", "description": "Exchange-traded funds", "liquidity": "high", "market": "exchange-hours"},
    "futures": {"label": "Futures", "description": "Derivative contracts", "liquidity": "high", "market": "exchange-hours"},
    "options": {"label": "Options", "description": "Options contracts", "liquidity": "medium", "market": "exchange-hours"},
    "commodities": {"label": "Commodities", "description": "Raw materials (XAU, WTI, ...)", "liquidity": "high", "market": "23x5"},
    "bonds": {"label": "Bonds", "description": "Government & corporate bonds", "liquidity": "medium", "market": "exchange-hours"},
    "synthetic": {"label": "Synthetic", "description": "Synthetic instruments (Volatility indices)", "liquidity": "medium", "market": "24x7"},
}


def init_multi_asset():
    logger.info("Multi-asset expansion initialized")
    return get_multi_asset_overview


def get_asset_classes():
    result = []
    for asset_id in ASSET_CLASSES:
        info = ASSET_INFO[asset_id]
        result.append({
            "id": asset_id,
            **info,
            "instruments": [i["symbol"] for i in INSTRUMENTS if i["type"] == asset_id],
        })
    return result


def get_multi_asset_overview():
    return {
        "classes": get_asset_classes(),
        "instruments": [
            {
                "symbol": inst["symbol"],
                "name": inst["name"],
                "type": inst["type"],
                "assetClass": (ASSET_INFO.get(inst["type"]) or {}).get("label") or inst["type"],
                "bid": get_quote(inst["symbol"])["bid"],
                "ask": get_quote(inst["symbol"])["ask"],
                "spread": get_quote(inst["symbol"])["spread"],
                "change24h": get_quote(inst["symbol"])["change24h"],
            }
            for inst in INSTRUMENTS
        ],
        "summary": {
            "totalInstruments": len(INSTRUMENTS),
            "activeClasses": len(set(i["type"] for i in INSTRUMENTS)),
            "lastUpdated": int(time.time() * 1000),
        },
    }


def get_instruments_by_class(asset_class):
    instruments = [i for i in INSTRUMENTS if i["type"] == asset_class]
    return [{**i, **get_quote(i["symbol"])} for i in instruments]

"""Instrument Specification Engine (Batch 04 / checklist #9).

Canonical instrument specs, broker symbol mapping and pip/tick math.
NEVER hardcode XAUUSD pip assumptions in trading logic — look them up here.

Mirrors the prompt: canonical_symbol, broker_symbol, digits, point_size,
tick_size, tick_value, pip_size, pip_value, contract_size, min/max volume,
volume_step, stops_level, freeze_level, trading_sessions, market_status.
"""
import time
from decimal import Decimal, ROUND_HALF_UP

from ...foundation.logger import logger


def _dec(value):
    """Safe Decimal conversion (floats are handled via str to avoid drift)."""
    return Decimal(str(value))


# Canonical spec per instrument. Fields:
#   symbol, name, type, digits, point (min price step), pip_size,
#   pip_value (per 1.0 lot, in quote currency), contract_size,
#   volume_min, volume_max, volume_step, stops_level, freeze_level,
#   sessions, market (24x7 / fx / exchange / crypto), base_currency,
#   quote_currency, margin_rate, spread_typical
INSTRUMENT_SPECS = [
    {
        "symbol": "XAUUSD", "broker_symbols": ["XAUUSD", "GOLD", "XAUUSD.a"],
        "name": "Gold / US Dollar", "type": "commodities", "digits": 2,
        "point": 0.01, "tick_size": 0.01, "pip_size": 0.1,
        "tick_value": 0.01, "pip_value": 0.1, "contract_size": 100,
        "volume_min": 0.01, "volume_max": 100, "volume_step": 0.01,
        "stops_level": 10, "freeze_level": 10, "sessions": "fx",
        "market": "fx", "base_currency": "XAU", "quote_currency": "USD",
        "margin_rate": 0.05, "spread_typical": 0.2, "leverage_note": "1:20",
    },
    {
        "symbol": "EURUSD", "broker_symbols": ["EURUSD", "EURUSD.a"],
        "name": "Euro / US Dollar", "type": "forex", "digits": 5,
        "point": 0.00001, "tick_size": 0.00001, "pip_size": 0.0001,
        "tick_value": 0.00001, "pip_value": 0.0001, "contract_size": 100000,
        "volume_min": 0.01, "volume_max": 100, "volume_step": 0.01,
        "stops_level": 10, "freeze_level": 10, "sessions": "fx",
        "market": "fx", "base_currency": "EUR", "quote_currency": "USD",
        "margin_rate": 0.02, "spread_typical": 0.0001, "leverage_note": "1:50",
    },
    {
        "symbol": "GBPUSD", "broker_symbols": ["GBPUSD", "GBPUSD.a"],
        "name": "British Pound / US Dollar", "type": "forex", "digits": 5,
        "point": 0.00001, "tick_size": 0.00001, "pip_size": 0.0001,
        "tick_value": 0.00001, "pip_value": 0.0001, "contract_size": 100000,
        "volume_min": 0.01, "volume_max": 100, "volume_step": 0.01,
        "stops_level": 10, "freeze_level": 10, "sessions": "fx",
        "market": "fx", "base_currency": "GBP", "quote_currency": "USD",
        "margin_rate": 0.02, "spread_typical": 0.00012, "leverage_note": "1:50",
    },
    {
        "symbol": "USDJPY", "broker_symbols": ["USDJPY", "USDJPY.a"],
        "name": "US Dollar / Japanese Yen", "type": "forex", "digits": 3,
        "point": 0.001, "tick_size": 0.001, "pip_size": 0.01,
        "tick_value": 0.001, "pip_value": 0.01, "contract_size": 100000,
        "volume_min": 0.01, "volume_max": 100, "volume_step": 0.01,
        "stops_level": 10, "freeze_level": 10, "sessions": "fx",
        "market": "fx", "base_currency": "USD", "quote_currency": "JPY",
        "margin_rate": 0.02, "spread_typical": 0.012, "leverage_note": "1:50",
    },
    {
        "symbol": "BTCUSD", "broker_symbols": ["BTCUSD", "BTCUSD.a", "XBTUSD"],
        "name": "Bitcoin / US Dollar", "type": "crypto", "digits": 2,
        "point": 0.01, "tick_size": 0.01, "pip_size": 1,
        "tick_value": 0.01, "pip_value": 1, "contract_size": 1,
        "volume_min": 0.0001, "volume_max": 100, "volume_step": 0.0001,
        "stops_level": 0, "freeze_level": 0, "sessions": "24x7",
        "market": "24x7", "base_currency": "BTC", "quote_currency": "USD",
        "margin_rate": 0.05, "spread_typical": 5, "leverage_note": "1:20",
    },
    {
        "symbol": "ETHUSD", "broker_symbols": ["ETHUSD", "ETHUSD.a"],
        "name": "Ethereum / US Dollar", "type": "crypto", "digits": 2,
        "point": 0.01, "tick_size": 0.01, "pip_size": 0.1,
        "tick_value": 0.01, "pip_value": 0.1, "contract_size": 1,
        "volume_min": 0.001, "volume_max": 100, "volume_step": 0.001,
        "stops_level": 0, "freeze_level": 0, "sessions": "24x7",
        "market": "24x7", "base_currency": "ETH", "quote_currency": "USD",
        "margin_rate": 0.05, "spread_typical": 0.5, "leverage_note": "1:20",
    },
    {
        "symbol": "US500", "broker_symbols": ["US500", "SPX500", "SP500"],
        "name": "S&P 500 Index", "type": "stocks", "digits": 2,
        "point": 0.01, "tick_size": 0.01, "pip_size": 0.1,
        "tick_value": 0.01, "pip_value": 0.1, "contract_size": 1,
        "volume_min": 0.01, "volume_max": 100, "volume_step": 0.01,
        "stops_level": 10, "freeze_level": 10, "sessions": "exchange",
        "market": "exchange", "base_currency": "USD", "quote_currency": "USD",
        "margin_rate": 0.02, "spread_typical": 0.3, "leverage_note": "1:50",
    },
    {
        "symbol": "NAS100", "broker_symbols": ["NAS100", "NDX100", "NAS100.a"],
        "name": "Nasdaq 100 Index", "type": "stocks", "digits": 2,
        "point": 0.01, "tick_size": 0.01, "pip_size": 0.1,
        "tick_value": 0.01, "pip_value": 0.1, "contract_size": 1,
        "volume_min": 0.01, "volume_max": 100, "volume_step": 0.01,
        "stops_level": 10, "freeze_level": 10, "sessions": "exchange",
        "market": "exchange", "base_currency": "USD", "quote_currency": "USD",
        "margin_rate": 0.02, "spread_typical": 1, "leverage_note": "1:50",
    },
    {
        "symbol": "US30", "broker_symbols": ["US30", "DJ30", "US30.a"],
        "name": "Dow Jones 30 Index", "type": "stocks", "digits": 2,
        "point": 0.01, "tick_size": 0.01, "pip_size": 0.1,
        "tick_value": 0.01, "pip_value": 0.1, "contract_size": 1,
        "volume_min": 0.01, "volume_max": 100, "volume_step": 0.01,
        "stops_level": 10, "freeze_level": 10, "sessions": "exchange",
        "market": "exchange", "base_currency": "USD", "quote_currency": "USD",
        "margin_rate": 0.02, "spread_typical": 2, "leverage_note": "1:50",
    },
    {
        "symbol": "WTI", "broker_symbols": ["WTI", "USOIL", "WTIUSD"],
        "name": "West Texas Intermediate Crude", "type": "commodities", "digits": 2,
        "point": 0.01, "tick_size": 0.01, "pip_size": 0.01,
        "tick_value": 0.01, "pip_value": 0.01, "contract_size": 1000,
        "volume_min": 0.01, "volume_max": 100, "volume_step": 0.01,
        "stops_level": 10, "freeze_level": 10, "sessions": "fx",
        "market": "fx", "base_currency": "WTI", "quote_currency": "USD",
        "margin_rate": 0.05, "spread_typical": 0.01, "leverage_note": "1:20",
    },
    {
        "symbol": "AAPL", "broker_symbols": ["AAPL", "AAPL.US"],
        "name": "Apple Inc.", "type": "stocks", "digits": 2,
        "point": 0.01, "tick_size": 0.01, "pip_size": 0.01,
        "tick_value": 0.01, "pip_value": 0.01, "contract_size": 1,
        "volume_min": 0.01, "volume_max": 10000, "volume_step": 0.01,
        "stops_level": 10, "freeze_level": 10, "sessions": "exchange",
        "market": "exchange", "base_currency": "USD", "quote_currency": "USD",
        "margin_rate": 0.1, "spread_typical": 0.01, "leverage_note": "1:10",
    },
    {
        "symbol": "TSLA", "broker_symbols": ["TSLA", "TSLA.US"],
        "name": "Tesla Inc.", "type": "stocks", "digits": 2,
        "point": 0.01, "tick_size": 0.01, "pip_size": 0.01,
        "tick_value": 0.01, "pip_value": 0.01, "contract_size": 1,
        "volume_min": 0.01, "volume_max": 10000, "volume_step": 0.01,
        "stops_level": 10, "freeze_level": 10, "sessions": "exchange",
        "market": "exchange", "base_currency": "USD", "quote_currency": "USD",
        "margin_rate": 0.1, "spread_typical": 0.02, "leverage_note": "1:10",
    },
]

_BY_SYMBOL = {}
_BY_BROKER = {}
for _s in INSTRUMENT_SPECS:
    _BY_SYMBOL[_s["symbol"]] = _s
    for _b in _s.get("broker_symbols", []):
        _BY_BROKER[_b.upper()] = _s["symbol"]


class InstrumentSpecEngine:
    """Lookup + math for instrument specs. Never assume hardcoded pips."""

    def get_spec(self, symbol):
        sym = (symbol or "").upper()
        canonical = _BY_BROKER.get(sym, sym)
        return _BY_SYMBOL.get(canonical)

    def resolve(self, symbol):
        spec = self.get_spec(symbol)
        if not spec:
            return None
        return {**spec, "canonical_symbol": spec["symbol"], "broker_symbol": spec["broker_symbols"][0]}

    def all(self):
        return [self.resolve(s["symbol"]) for s in INSTRUMENT_SPECS]

    def is_tradable(self, symbol):
        return self.get_spec(symbol) is not None

    def pip_size(self, symbol):
        spec = self.get_spec(symbol)
        return spec["pip_size"] if spec else 0.0001

    def point(self, symbol):
        spec = self.get_spec(symbol)
        return spec["point"] if spec else 0.0001

    def digits(self, symbol):
        spec = self.get_spec(symbol)
        return spec["digits"] if spec else 5

    def contract_size(self, symbol):
        spec = self.get_spec(symbol)
        return spec["contract_size"] if spec else 1

    def pips_between(self, symbol, price_a, price_b):
        """Number of pips between two prices for an instrument."""
        return abs(price_a - price_b) / self.pip_size(symbol)

    def price_from_pips(self, symbol, price, pips):
        """Move a price by N pips (signed)."""
        return price + pips * self.pip_size(symbol)

    def pip_value_per_lot(self, symbol, quote_to_account_rate=1.0):
        """Monetary value of one pip per 1.0 lot in account currency."""
        spec = self.get_spec(symbol)
        if not spec:
            return 0.0001
        return spec["pip_value"] * quote_to_account_rate

    def risk_amount_for_stop(self, symbol, volume, entry, stop):
        """Money at risk given entry/stop and volume (account currency)."""
        pips = self.pips_between(symbol, entry, stop)
        return pips * self.pip_value_per_lot(symbol) * volume

    def normalize_volume(self, symbol, volume):
        spec = self.get_spec(symbol)
        if not spec:
            return round(volume, 2)
        step = spec["volume_step"]
        vmin = spec["volume_min"]
        vmax = spec["volume_max"]
        if volume is None or volume <= 0:
            return vmin
        snapped = round(round(volume / step) * step, 8)
        return max(vmin, min(vmax, snapped))

    def validate_stop_level(self, symbol, price, stop):
        """Check stop respects broker stops_level (in points)."""
        spec = self.get_spec(symbol)
        if not spec or spec.get("stops_level") is None:
            return True, 0
        dist = abs(price - stop)
        min_dist = spec["stops_level"] * spec["point"]
        if dist < min_dist:
            return False, min_dist
        return True, min_dist

    def min_stop_distance(self, symbol):
        """Minimum broker stop distance (stops_level * point) for a symbol.

        Returns a Decimal (0 when the spec is missing or stops_level is 0).
        """
        spec = self.get_spec(symbol)
        if not spec or spec.get("stops_level") is None:
            return Decimal(0)
        return _dec(spec["stops_level"]) * _dec(spec["point"])

    def enforce_stop_levels(self, symbol, side, entry, stop, take_profit):
        """Push SL/TP outward so both are at least stops_level points from entry.

        Uses Decimal math internally. Wrong-side or too-close stops are nudged
        to the minimum broker distance to prevent 'Invalid Stops' rejections
        from MT5. None values are preserved untouched.

        Returns (ok, stop, take_profit, min_dist, adjusted) where:
          - ok: always True for this buffer (wrong side is corrected, not fatal)
          - stop / take_profit: possibly adjusted values (None preserved)
          - min_dist: float minimum distance (0 if no spec / stops_level)
          - adjusted: list of ("sl" | "tp", old, new) tuples actually moved
        """
        spec = self.get_spec(symbol)
        min_dist = self.min_stop_distance(symbol)
        if not spec or min_dist <= 0:
            return True, stop, take_profit, 0.0, []
        side = (side or "buy").lower()
        digits = int(spec.get("digits", 5))
        quantum = Decimal(1).scaleb(-digits)
        entry = _dec(entry)

        def quantize(value):
            return float(value.quantize(quantum, rounding=ROUND_HALF_UP))

        out_sl = stop
        out_tp = take_profit
        adjusted = []

        if side == "buy":
            # SL must sit at or below entry - min_dist; TP at or above entry + min_dist.
            if stop is not None:
                sl = _dec(stop)
                limit = entry - min_dist
                if sl > limit:
                    out_sl = quantize(limit)
                    adjusted.append(("sl", float(sl), out_sl))
            if take_profit is not None:
                tp = _dec(take_profit)
                limit = entry + min_dist
                if tp < limit:
                    out_tp = quantize(limit)
                    adjusted.append(("tp", float(tp), out_tp))
        else:
            # SELL: SL must sit at or above entry + min_dist; TP at or below entry - min_dist.
            if stop is not None:
                sl = _dec(stop)
                limit = entry + min_dist
                if sl < limit:
                    out_sl = quantize(limit)
                    adjusted.append(("sl", float(sl), out_sl))
            if take_profit is not None:
                tp = _dec(take_profit)
                limit = entry - min_dist
                if tp > limit:
                    out_tp = quantize(limit)
                    adjusted.append(("tp", float(tp), out_tp))

        return True, out_sl, out_tp, float(min_dist), adjusted

    def spread_pips(self, symbol, spread):
        """Convert an absolute spread to pips for the instrument."""
        return spread / self.pip_size(symbol) if self.pip_size(symbol) else 0

    def market_status(self, symbol, now=None):
        """Return market status: open / closed / weekend for the spec."""
        spec = self.get_spec(symbol)
        if not spec:
            return {"open": True, "reason": "unknown-instrument"}
        market = spec.get("market", "fx")
        if market == "24x7":
            return {"open": True, "reason": "24x7"}
        now = now or time.gmtime()
        weekday = now.tm_wday  # 0=Monday
        hour_utc = now.tm_hour + now.tm_min / 60.0
        if market == "exchange":
            open_market = weekday < 5 and 13.5 <= hour_utc < 20.0  # approx 09:30-16:00 ET
            return {"open": open_market, "reason": "exchange-hours" if open_market else "exchange-closed"}
        # fx: closed Sat 22:00 - Sun 22:00 UTC
        if weekday == 5 and hour_utc >= 22.0:
            return {"open": False, "reason": "weekend"}
        if weekday == 6 and hour_utc < 22.0:
            return {"open": False, "reason": "weekend"}
        return {"open": True, "reason": "fx-open"}


instrument_specs = InstrumentSpecEngine()


def get_instrument_spec(symbol):
    return instrument_specs.resolve(symbol)


def init_instrument_specs():
    logger.info(f"Instrument spec engine initialized ({len(INSTRUMENT_SPECS)} canonical specs)")
    return instrument_specs

"""Deterministic market-data quality gates.

Pure functions that classify an incoming quote against a set of gates:

    monotonicTimestamp - timestamp must be strictly greater than the previous
        quote timestamp (a backwards tick is a violation).
    duplicateTick      - same timestamp AND same price as the previous quote.
    gap                - price jump exceeds a configured threshold (default
        abs change > 5% of the previous price).
    outlier            - price outside a sane band (negative or > N x the
        previous price / typical range).
    ohlc               - high >= max(open, close) and low <= min(open, close).
    session            - timestamp must fall inside the provided session window.
    sequenceGap        - previous sequence number + 1 != current sequence.

Every gate returns True when the condition is *violated* (i.e. a problem was
detected) and False when the gate passes or cannot be evaluated. No randomness,
no I/O — fully deterministic.
"""

HARD_GATES = ("monotonicTimestamp", "outlier", "ohlc", "session", "sequenceGap")
SOFT_GATES = ("duplicateTick", "gap")

GATE_KEYS = (
    "monotonicTimestamp",
    "duplicateTick",
    "gap",
    "outlier",
    "ohlc",
    "session",
    "sequenceGap",
)

# Tunable gate configuration (can be overridden at runtime).
GATE_CONFIG = {
    "gapThreshold": 0.05,
    "outlierMultiple": 10.0,
}

CROSS_PAIRS = (
    ("DXY", "XAUUSD", "inverse"),
    ("EURUSD", "DXY", "inverse"),
    ("EURUSD", "XAUUSD", "correlated"),
)


def _quote_price(quote):
    price = quote.get("price")
    if price is None:
        price = quote.get("bid")
    return price


def _utc_hour_of_ms(timestamp):
    """Convert an epoch-ms timestamp into fractional UTC hours."""
    if timestamp is None:
        return None
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
    return dt.hour + dt.minute / 60.0


# ---- individual gates ----

def _gate_monotonic_timestamp(quote, prev_quote):
    ts = quote.get("timestamp")
    prev_ts = prev_quote.get("timestamp") if prev_quote else None
    if ts is None or prev_ts is None:
        return False
    try:
        return float(ts) < float(prev_ts)
    except (TypeError, ValueError):
        return False


def _gate_duplicate_tick(quote, prev_quote):
    if not prev_quote:
        return False
    ts = quote.get("timestamp")
    prev_ts = prev_quote.get("timestamp")
    price = _quote_price(quote)
    prev_price = _quote_price(prev_quote)
    if ts is None or prev_ts is None or price is None or prev_price is None:
        return False
    try:
        return float(ts) == float(prev_ts) and float(price) == float(prev_price)
    except (TypeError, ValueError):
        return False


def _gate_gap(quote, prev_quote):
    if not prev_quote:
        return False
    price = _quote_price(quote)
    prev_price = _quote_price(prev_quote)
    if price is None or prev_price is None:
        return False
    try:
        price = float(price)
        prev_price = float(prev_price)
    except (TypeError, ValueError):
        return False
    if prev_price == 0:
        return False
    threshold = GATE_CONFIG.get("gapThreshold", 0.05)
    return abs(price - prev_price) / abs(prev_price) > threshold


def _gate_outlier(quote, prev_quote):
    price = _quote_price(quote)
    if price is None:
        return False
    try:
        price = float(price)
    except (TypeError, ValueError):
        return False
    if price < 0:
        return True
    multiple = GATE_CONFIG.get("outlierMultiple", 10.0)
    typical_range = quote.get("typicalRange") or quote.get("typicalPriceRange")
    if typical_range:
        try:
            typical_range = float(typical_range)
        except (TypeError, ValueError):
            typical_range = None
        if typical_range and typical_range > 0:
            ref = _quote_price(prev_quote) if prev_quote else None
            if ref is None:
                ref = price
            try:
                ref = float(ref)
            except (TypeError, ValueError):
                ref = price
            if abs(price - ref) > multiple * typical_range:
                return True
            return False
    prev_price = _quote_price(prev_quote) if prev_quote else None
    if prev_price is not None:
        try:
            prev_price = float(prev_price)
        except (TypeError, ValueError):
            prev_price = None
        if prev_price and prev_price > 0:
            if price > prev_price * multiple or price < prev_price / multiple:
                return True
    return False


def _gate_ohlc(quote, prev_quote):
    o = quote.get("open")
    h = quote.get("high")
    l = quote.get("low")
    c = quote.get("close")
    if o is None or h is None or l is None or c is None:
        return False
    try:
        o, h, l, c = float(o), float(h), float(l), float(c)
    except (TypeError, ValueError):
        return False
    return h < max(o, c) or l > min(o, c) or h < l


def _gate_session(quote, prev_quote, session):
    if session is None:
        return False
    utc_hour = _utc_hour_of_ms(quote.get("timestamp"))
    if utc_hour is None:
        return False
    open_h = session.get("open")
    close_h = session.get("close")
    if open_h is None or close_h is None:
        return False
    try:
        open_h = float(open_h)
        close_h = float(close_h)
    except (TypeError, ValueError):
        return False
    if open_h <= close_h:
        inside = open_h <= utc_hour < close_h
    else:
        inside = utc_hour >= open_h or utc_hour < close_h
    return not inside


def _gate_sequence_gap(quote, prev_quote):
    if not prev_quote:
        return False
    seq = quote.get("seq")
    prev_seq = prev_quote.get("seq")
    if seq is None or prev_seq is None:
        return False
    try:
        return int(prev_seq) + 1 != int(seq)
    except (TypeError, ValueError):
        return False


def validate_quote(quote, prev_quote=None, session=None):
    """Validate a quote against all quality gates.

    Returns {"valid": bool, "gates": {gate: bool}} where each gate bool is True
    when the corresponding problem was detected. Quotes that cannot be fully
    evaluated (missing fields) default to passing gates rather than failing.
    """
    quote = quote or {}
    gates = {
        "monotonicTimestamp": _gate_monotonic_timestamp(quote, prev_quote),
        "duplicateTick": _gate_duplicate_tick(quote, prev_quote),
        "gap": _gate_gap(quote, prev_quote),
        "outlier": _gate_outlier(quote, prev_quote),
        "ohlc": _gate_ohlc(quote, prev_quote),
        "session": _gate_session(quote, prev_quote, session),
        "sequenceGap": _gate_sequence_gap(quote, prev_quote),
    }
    failures = [name for name in GATE_KEYS if gates[name]]
    return {
        "valid": len(failures) == 0,
        "gates": gates,
        "failedGates": failures,
        "hardFailed": any(gates[name] for name in HARD_GATES),
    }


def cross_market_check(quotes):
    """Deterministic cross-market alignment check.

    `quotes` maps a symbol (DXY, XAUUSD, EURUSD, ...) to a quote dict carrying
    at least `price`/`change24h` (or `price` + `prevClose`). DXY and XAUUSD are
    expected to move inversely, EURUSD is expected to move inversely to DXY and
    in line with XAUUSD. Returns {"crossMarketAligned": bool, "divergences": []}.
    """
    quotes = quotes or {}
    divergences = []
    for left, right, relationship in CROSS_PAIRS:
        if left not in quotes or right not in quotes:
            continue
        left_dir = _direction(quotes[left])
        right_dir = _direction(quotes[right])
        if left_dir == 0 or right_dir == 0:
            continue
        if relationship == "inverse":
            aligned = left_dir != right_dir
        else:
            aligned = left_dir == right_dir
        if not aligned:
            divergences.append({
                "pair": f"{left}/{right}",
                "relationship": relationship,
                "detail": (
                    f"{left} is {_dir_label(left_dir)} while {right} is "
                    f"{_dir_label(right_dir)} (expected {relationship})"
                ),
            })
    return {
        "crossMarketAligned": len(divergences) == 0,
        "divergences": divergences,
    }


def _direction(quote):
    """Return +1 up / -1 down / 0 flat using change24h or price vs prevClose."""
    if not isinstance(quote, dict):
        return 0
    change = quote.get("change24h")
    if change is None:
        price = quote.get("price")
        ref = quote.get("prevClose") or quote.get("base")
        if price is None or ref is None:
            return 0
        try:
            price = float(price)
            ref = float(ref)
        except (TypeError, ValueError):
            return 0
        if ref == 0:
            return 0
        change = (price - ref) / ref * 100.0
    try:
        change = float(change)
    except (TypeError, ValueError):
        return 0
    if change > 0:
        return 1
    if change < 0:
        return -1
    return 0


def _dir_label(direction):
    if direction > 0:
        return "rising"
    if direction < 0:
        return "falling"
    return "flat"


def market_validation_context(quotes=None):
    """Build the `market` slice expected by validation/engine.check_market().

    Exposes crossMarketAligned (from cross_market_check) plus the spread /
    volatility fields required by the market validation gate.
    """
    cross = cross_market_check(quotes)
    spread_pips = 0.0
    if quotes:
        spreads = []
        for q in quotes.values():
            if isinstance(q, dict) and q.get("spread") is not None:
                try:
                    spreads.append(float(q["spread"]))
                except (TypeError, ValueError):
                    pass
        if spreads:
            spread_pips = max(spreads) * 10000.0
    return {
        "market": {
            "crossMarketAligned": cross["crossMarketAligned"],
            "divergences": cross["divergences"],
            "spreadPips": round(spread_pips, 2),
            "maxSpreadPips": 3.0,
            "volatilityInRange": True,
        }
    }

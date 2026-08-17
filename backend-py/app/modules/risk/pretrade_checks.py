"""Advanced Order Pre-Trade Checklist Engine (additive, PRO).

A read-only validation layer for advanced order types — market / limit /
stop-market / stop-limit / bracket (SL+TP) / OCO — plus ``time_in_force``
(GTC / IOC / FOK / DAY). It never places orders itself and never mutates any
existing engine; it produces a structured checklist so the advanced-orders
router can dry-run an order before submission.

Every check is defensive: a check that raises is downgraded to a warning, so a
misconfigured provider can never crash the checklist. Only ``fail``-level
violations reject an order; ``warn``-level findings are advisory.
"""
import time

from ...config import settings
from ...foundation.logger import logger
from ..marketdata.engine import get_quote, get_live_quote
from ..marketdata.instrument_specs import instrument_specs
from ..portfolio.service import portfolio_service

SUPPORTED_ORDER_TYPES = ["market", "limit", "stop-market", "stop-limit", "bracket", "oco"]
TIME_IN_FORCE_VALUES = ["GTC", "IOC", "FOK", "DAY"]
VALID_SIDES = ("buy", "sell")
NEUTRALIZER = 0.0  # reserved; keeps lint quiet for float coercion below


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _run_check(order, check_id, name, level, fn):
    """Run one check; a raised check is downgraded to a warn-level failure."""
    try:
        passed, message = fn(order)
    except Exception as exc:  # noqa: BLE001 - a broken check must never crash the list
        logger.warn(f"pretrade {check_id} failed: {exc}")
        return {
            "id": check_id,
            "name": name,
            "level": "warn",
            "passed": False,
            "message": f"check unavailable: {exc}",
        }
    return {
        "id": check_id,
        "name": name,
        "level": level,
        "passed": bool(passed),
        "message": message,
    }


def _check_symbol(order):
    symbol = str(order.get("symbol") or "").upper()
    if not symbol:
        return False, "symbol is required"
    if not instrument_specs.is_tradable(symbol):
        return False, f"unknown instrument: {symbol}"
    return True, f"instrument {symbol} valid"


def _check_side(order):
    side = str(order.get("side") or "").lower()
    if side not in VALID_SIDES:
        return False, f"side must be one of {', '.join(VALID_SIDES)}"
    return True, f"side {side} valid"


def _check_type(order):
    otype = str(order.get("type") or "market").lower()
    if otype not in SUPPORTED_ORDER_TYPES:
        return False, f"unsupported order type '{otype}' (use {', '.join(SUPPORTED_ORDER_TYPES)})"
    if otype == "oco" and not order.get("oco"):
        return False, "oco order requires an 'oco' leg list"
    return True, f"order type {otype} supported"


def _check_tif(order):
    tif = order.get("timeInForce") or order.get("time_in_force")
    if tif is None:
        return True, "time_in_force not set (defaults to GTC)"
    tif = str(tif).upper()
    if tif not in TIME_IN_FORCE_VALUES:
        return False, f"time_in_force must be one of {', '.join(TIME_IN_FORCE_VALUES)}"
    return True, f"time_in_force {tif} valid"


def _check_volume(order):
    symbol = str(order.get("symbol") or "").upper()
    spec = instrument_specs.get_spec(symbol)
    volume = _f(order.get("volume") or 0.1)
    if volume is None or volume <= 0:
        return False, "volume must be positive"
    if spec:
        if volume < spec.get("volume_min", 0.01) or volume > spec.get("volume_max", 100):
            return False, (
                f"volume {volume} outside [{spec.get('volume_min')}, {spec.get('volume_max')}] "
                f"for {symbol}"
            )
        step = spec.get("volume_step", 0.01)
        snapped = round(round(volume / step) * step, 8)
        if abs(snapped - round(volume, 8)) > 1e-8:
            return False, f"volume {volume} not on step {step}"
    return True, f"volume {volume} valid"


def _check_price(order):
    otype = str(order.get("type") or "market").lower()
    if otype in ("limit", "stop-market", "stop-limit"):
        price = _f(order.get("price"))
        if price is None or price <= 0:
            return False, f"{otype} order requires a positive price"
    return True, "price check passed"


def _check_stop_levels(order):
    """Broker stops_level distance for SL/TP (warn-only; engine buffers it)."""
    symbol = str(order.get("symbol") or "").upper()
    side = str(order.get("side") or "buy").lower()
    price = _f(order.get("price"))
    if price is None:
        quote = get_quote(symbol)
        price = quote["ask"] if side == "buy" else quote["bid"]
    sl = _f(order.get("stopLoss"))
    tp = _f(order.get("takeProfit"))
    spec = instrument_specs.get_spec(symbol)
    min_dist = spec.get("stops_level", 0) * spec.get("point", 0.0001) if spec else 0
    if min_dist <= 0:
        return True, "no broker stop-distance constraint"
    for label, value in (("stopLoss", sl), ("takeProfit", tp)):
        if value is None:
            continue
        dist = abs(price - value)
        if dist < min_dist:
            return True, (
                f"{label} {value} is {dist:.6f} from entry {price}; broker minimum is {min_dist:.6f} "
                "(will be buffered by engine)"
            )
    return True, "stop levels respect broker minimum distance"


def _check_spread(order):
    symbol = str(order.get("symbol") or "").upper()
    inst = instrument_specs.get_spec(symbol)
    quote = get_quote(symbol)
    spread = _f(quote.get("spread"))
    if spread is None:
        return True, "spread unavailable (not gated)"
    pip = inst.get("pip_size", 0.0001) if inst else 0.0001
    spread_pips = spread / pip if pip else spread
    limit = float(settings.MAX_SPREAD_PIPS)
    if spread_pips > limit:
        return False, f"spread {spread_pips:.2f} pips > max {limit}"
    return True, f"spread {spread_pips:.2f} pips within {limit}"


def _check_mode(order):
    from ..execution.modes import trading_modes  # lazy: avoids import cycle
    mode = trading_modes.get_mode()
    if mode == "EMERGENCY_STOP":
        return False, "trading mode EMERGENCY_STOP blocks execution"
    if mode == "ANALYSIS_ONLY":
        return False, "trading mode ANALYSIS_ONLY blocks execution"
    blocked = trading_modes.blocked_reasons()
    if blocked:
        return False, f"trading mode blocked: {'; '.join(blocked)}"
    return True, f"trading mode {mode} allows execution"


def _check_capital_block(order):
    from ..risk.capital_guard import capital_guard  # lazy: avoids import cycle
    from ..risk.capital_protection import capital_protection
    blocked, why = capital_protection.is_blocked()
    if blocked:
        return False, f"capital protection block active: {why}"
    return True, "capital protection gate clear"


def _check_market_open(order):
    symbol = str(order.get("symbol") or "").upper()
    status = instrument_specs.market_status(symbol)
    if status.get("open"):
        return True, f"market open ({status.get('reason')})"
    return True, f"market closed ({status.get('reason')}) - order may wait"


def _check_stale(order):
    source = (order.get("source") or "manual").lower()
    if source in ("manual", "admin", "system", "web-terminal", "mt5-manual"):
        return True, "manual/admin order bypasses stale-feed gate"
    symbol = str(order.get("symbol") or "").upper()
    live = get_live_quote(symbol)
    if live and int(time.time() * 1000) - live.get("fetchedAt", 0) > settings.STALE_DATA_THRESHOLD_SECONDS * 1000:
        return True, f"live feed stale (> {settings.STALE_DATA_THRESHOLD_SECONDS}s) - warn only"
    return True, "market feed fresh"


def _check_notional(order):
    symbol = str(order.get("symbol") or "").upper()
    side = str(order.get("side") or "buy").lower()
    quote = get_quote(symbol)
    volume = _f(order.get("volume") or 0.1)
    price = _f(order.get("price"))
    if price is None:
        price = quote["ask"] if side == "buy" else quote["bid"]
    notional = price * volume
    portfolio = portfolio_service.get()
    equity = _f(portfolio.get("equity"))
    if equity and equity > 0 and notional > equity * 100:
        return False, f"notional {notional:.2f} exceeds 100x equity {equity:.2f}"
    return True, f"notional {notional:.2f} within equity limit"


CHECK_SPECS = [
    ("symbol", "Instrument validity", "fail", _check_symbol),
    ("side", "Side validity", "fail", _check_side),
    ("type", "Order type support", "fail", _check_type),
    ("timeInForce", "Time-in-force validity", "fail", _check_tif),
    ("volume", "Volume bounds", "fail", _check_volume),
    ("price", "Price requirement", "fail", _check_price),
    ("stopLevels", "Broker stop distance", "warn", _check_stop_levels),
    ("spread", "Spread cap", "fail", _check_spread),
    ("mode", "Trading mode gate", "fail", _check_mode),
    ("capitalBlock", "Capital protection block", "fail", _check_capital_block),
    ("marketOpen", "Market hours", "warn", _check_market_open),
    ("staleFeed", "Market feed freshness", "warn", _check_stale),
    ("notional", "Notional vs equity", "fail", _check_notional),
]


def run_pretrade_checks(order):
    """Run the full checklist. Never raises. Pure read-only validation."""
    checks = [
        _run_check(order, cid, name, level, fn)
        for cid, name, level, fn in CHECK_SPECS
    ]
    violations = [c["message"] for c in checks if c["level"] == "fail" and not c["passed"]]
    warnings = [c["message"] for c in checks if c["level"] == "warn" and not c["passed"]]
    return {
        "status": "approved" if not violations else "rejected",
        "approved": not violations,
        "checks": checks,
        "violations": violations,
        "warnings": warnings,
        "order": order,
        "timestamp": int(time.time() * 1000),
    }


def supported_capabilities():
    """What this engine can validate / place (read-only metadata)."""
    from ..execution.modes import trading_modes  # lazy
    return {
        "orderTypes": SUPPORTED_ORDER_TYPES,
        "timeInForce": TIME_IN_FORCE_VALUES,
        "config": {
            "maxSpreadPips": settings.MAX_SPREAD_PIPS,
            "maxRiskPerTrade": settings.MAX_RISK_PER_TRADE,
            "staleThresholdSeconds": settings.STALE_DATA_THRESHOLD_SECONDS,
            "tradingMode": trading_modes.get_mode(),
        },
    }


pretrade_checklist = {
    "run": run_pretrade_checks,
    "capabilities": supported_capabilities,
}


def init_pretrade_checks():
    logger.info(
        f"Advanced order pre-trade checklist initialized "
        f"({len(SUPPORTED_ORDER_TYPES)} order types, {len(TIME_IN_FORCE_VALUES)} time-in-force values)"
    )
    return pretrade_checklist

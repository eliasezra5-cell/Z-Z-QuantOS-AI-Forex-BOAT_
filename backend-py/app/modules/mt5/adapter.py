"""MT5 adapter mirroring the Node mt5/adapter.js."""
import asyncio
import time

import httpx

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...config import settings
from ..marketdata.engine import get_quote, INSTRUMENTS
from ..trading.engine import trading_engine
from ..portfolio.service import portfolio_service


def _mt5_config():
    providers = settings.providers or {}
    base = providers.get("mt5") if isinstance(providers, dict) else None
    return {**(base or {}), **(_runtime_mt5_config or {})}


# Runtime credentials applied from the dashboard "Connect to MT5" form. Purely
# additive: when empty, the adapter behaves exactly as before (env-only config).
_runtime_mt5_config = {}


def apply_runtime_mt5_config(fields):
    """Merge dashboard-provided MT5 fields into the runtime config (additive).

    Does not touch the env-based settings; it only overrides them at runtime so
    a user can connect from the UI without restarting the backend.
    """
    fields = fields or {}
    merged = dict(_runtime_mt5_config)
    for key in ("login", "password", "server", "bridgeUrl", "mode", "host", "port"):
        value = fields.get(key)
        if value not in (None, ""):
            merged[key] = str(value).strip()
    if merged.get("bridgeUrl") and not merged.get("mode"):
        merged["mode"] = "live"
    _runtime_mt5_config.clear()
    _runtime_mt5_config.update(merged)
    return dict(_runtime_mt5_config)


async def connect_with_credentials(fields):
    """Save (encrypted) + apply dashboard MT5 credentials, then ping the bridge.

    Additive entrypoint used by the new ``POST /integrations/mt5/connect`` route.
    Returns the truthful MT5 status: connected only when the bridge is reachable
    and reports a real terminal connection — never a fake "Connected".
    """
    fields = fields or {}
    try:
        from ...persistence.mt5_connection_repository import mt5_connection_repository

        await mt5_connection_repository.save(fields)
    except Exception:  # noqa: BLE001 - persist best-effort; connection proceeds regardless
        logger.warn("MT5 credentials persistence failed", {"error": "exception"})
    apply_runtime_mt5_config(fields)
    if not _live_mode():
        simulate_connection()
        return {"connected": False, "detail": "bridge URL required to enable live mode", **mt5_state.to_dict()}
    try:
        await connect_live()
    except Exception:  # noqa: BLE001 - bridge unreachable, report disconnected truthfully
        mt5_state.connected = False
        mt5_state.account = None
        mt5_state.mode = "demo"
        mt5_state.bridge = _bridge_url()
        logger.warn("MT5 bridge unreachable from dashboard connect - reporting disconnected (no fake connection)")
    return {**mt5_state.to_dict(), "detail": "connected" if mt5_state.connected else "bridge unreachable or terminal not connected"}


class Mt5State:
    def __init__(self):
        self.connected = False
        self.account = None
        self.mode = "demo"
        self.latency = 0
        self.last_sync = None
        self.bridge = None

    def to_dict(self):
        return {
            "connected": self.connected,
            "account": self.account,
            "mode": self.mode,
            "latency": self.latency,
            "lastSync": self.last_sync,
            "bridge": self.bridge,
        }


mt5_state = Mt5State()


def _live_mode():
    cfg = _mt5_config()
    return bool(cfg.get("mode") == "live" and cfg.get("bridgeUrl"))


def _bridge_url():
    if not _live_mode():
        return None
    return _mt5_config()["bridgeUrl"].rstrip("/")


async def bridge_fetch(path, method="GET", body=None, timeout_ms=8000):
    url = f"{_bridge_url()}{path}"
    async with httpx.AsyncClient(timeout=timeout_ms / 1000) as client:
        res = await client.request(method, url, json=body, headers={"Content-Type": "application/json"})
        res.raise_for_status()
        return res.json()


def simulate_connection():
    """Truthful demo-mode status: no fake MT5 account is presented.

    Previously this faked a connected ICMarkets-Demo account. That is mock
    data and is now removed — when the live bridge is not configured or the
    terminal is not connected we report ``connected=False`` (demo/disconnected)
    exactly as the UI expects (yellow banner, never a fake "Connected").
    """
    mt5_state.connected = False
    mt5_state.latency = 0
    mt5_state.last_sync = int(time.time() * 1000)
    mt5_state.account = None
    mt5_state.mode = "demo"
    event_bus.emit("mt5:status", {"state": mt5_state.to_dict()})
    logger.info("MT5 adapter running in DEMO mode - no live MT5 account connected (no fake account presented)")
    return mt5_state.to_dict()


async def connect_live():
    data = await bridge_fetch("/status")
    mt5_state.connected = bool(data.get("connected"))
    mt5_state.latency = data.get("latency") or 0
    mt5_state.last_sync = int(time.time() * 1000)
    mt5_state.account = data.get("account") or None
    if mt5_state.connected:
        event_bus.emit("mt5:connected", {"state": mt5_state})
        logger.info("MT5 adapter connected via live bridge")
    else:
        logger.warn("MT5 bridge reachable but terminal not connected")
    return mt5_state.to_dict()


def sync_state():
    portfolio = portfolio_service.get()
    if mt5_state.account:
        mt5_state.account = {
            **mt5_state.account,
            "balance": portfolio["balance"],
            "equity": portfolio["equity"],
            "margin": portfolio["marginUsed"],
            "marginFree": portfolio["marginFree"],
            "openPositions": portfolio["openPositions"],
        }
    mt5_state.last_sync = int(time.time() * 1000)
    return mt5_state.to_dict()


# Keep references to scheduled background tasks so they are never garbage
# collected mid-flight (dropped tasks would silently never run).
_background_tasks = set()


def _schedule_live_connect_guard():
    """Run ``_live_connect_guard`` without orphaning its coroutine.

    The naive ``asyncio.create_task(coro())`` pattern creates the coroutine
    before ``create_task`` can raise ``RuntimeError`` when no loop is running,
    leaving the coroutine unawaited (RuntimeWarning at GC). Probe for a running
    loop first; only create the coroutine inside the branch that will consume
    it: schedule a kept-referenced task when a loop is running, otherwise run
    it synchronously with ``asyncio.run``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_live_connect_guard())
        return
    task = asyncio.create_task(_live_connect_guard())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _init_mt5_async():
    """Async init used when a running event loop is present.

    Loads + applies the saved dashboard MT5 credentials, then runs the live
    connect guard (or demo simulate) without ever orphaning a coroutine —
    ``run_sync`` would raise here, and ``asyncio.run`` cannot run from a running
    loop, so both the repository read and the guard are awaited directly.
    """
    try:
        from ...persistence.mt5_connection_repository import mt5_connection_repository

        saved = await mt5_connection_repository.get()
    except Exception:  # noqa: BLE001 - no saved connection is not an error
        saved = None
    if saved:
        apply_runtime_mt5_config(saved)
    if _live_mode():
        await _live_connect_guard()
    else:
        simulate_connection()


def _init_mt5_sync():
    """Sync init used when no event loop is running (module import / plain threads)."""
    try:
        from ...persistence.mt5_connection_repository import mt5_connection_repository
        from ...persistence.repository import run_sync

        saved = run_sync(mt5_connection_repository.get())
        if saved:
            apply_runtime_mt5_config(saved)
    except Exception:  # noqa: BLE001 - no saved connection is not an error
        pass
    if _live_mode():
        asyncio.run(_live_connect_guard())
    else:
        simulate_connection()


def init_mt5():
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        _init_mt5_sync()
    else:
        task = asyncio.create_task(_init_mt5_async())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    logger.info("MT5 integration initialized")

    return {
        "connect": _connect,
        "disconnect": _disconnect,
        "getStatus": _get_status,
        "getOrders": _get_orders,
        "getPositions": _get_positions,
        "getHistory": _get_history,
        "placeOrder": _place_order,
        "closePosition": _close_position,
        "getSymbols": _get_symbols,
    }


async def _live_connect_guard():
    try:
        await connect_live()
    except Exception:
        mt5_state.connected = False
        mt5_state.account = None
        logger.warn("MT5 live bridge unreachable - run bridge/mt5_bridge.py on your MT5 terminal machine")


async def _connect():
    if _live_mode():
        try:
            await connect_live()
        except Exception:
            mt5_state.connected = False
            mt5_state.account = None
            logger.warn("MT5 live bridge unreachable - reporting disconnected (no fake connection)")
    else:
        # Demo mode: always report the truthful demo/disconnected state.
        simulate_connection()
    return mt5_state.to_dict()


async def _disconnect():
    if _live_mode():
        try:
            await bridge_fetch("/disconnect", method="POST")
        except Exception:
            pass
    mt5_state.connected = False
    event_bus.emit("mt5:disconnected", {})
    return mt5_state.to_dict()


async def _get_status():
    if _live_mode() and mt5_state.connected:
        try:
            return await connect_live()
        except Exception:
            mt5_state.connected = False
    sync_state()
    return mt5_state.to_dict()


async def _get_orders():
    if _live_mode():
        try:
            return await bridge_fetch("/orders")
        except Exception:
            return trading_engine.get_orders({"limit": 50})
    return trading_engine.get_orders({"limit": 50})


async def _get_positions():
    if _live_mode():
        try:
            return await bridge_fetch("/positions")
        except Exception:
            return db.collection("positions").find({"status": "open"})
    return db.collection("positions").find({"status": "open"})


async def _get_history():
    def _history():
        return sorted(db.collection("positions").find({"status": "closed"}), key=lambda p: p["closedAt"], reverse=True)[:100]
    if _live_mode():
        try:
            return await bridge_fetch("/history")
        except Exception:
            return _history()
    return _history()


async def _place_order(order, time_in_force=None):
    if time_in_force:
        order = {**order, "timeInForce": str(time_in_force).upper()}
    if _live_mode():
        try:
            return await bridge_fetch("/orders", method="POST", body=order)
        except Exception:
            return trading_engine.place_order({**order, "source": "mt5"})
    return trading_engine.place_order({**order, "source": "mt5"})


async def _close_position(position_id):
    if _live_mode():
        try:
            return await bridge_fetch(f"/positions/{position_id}/close", method="POST")
        except Exception:
            return trading_engine.close_position(position_id, "mt5-manual")
    return trading_engine.close_position(position_id, "mt5-manual")


def _get_symbols():
    return [
        {
            "symbol": i["symbol"],
            "name": i["name"],
            "bid": get_quote(i["symbol"])["bid"],
            "ask": get_quote(i["symbol"])["ask"],
            "spread": get_quote(i["symbol"])["spread"],
            "digits": i["digits"],
            "source": get_quote(i["symbol"])["source"],
        }
        for i in INSTRUMENTS
    ]

"""Additive API router for the AI Brain execution core.

Mounted alongside the main router at /api. Provides read/scan endpoints for
the confidence monitor and kill-switch monitor without touching existing routes.
"""
import time

from fastapi import APIRouter, Request

from ..modules.execution.brain_monitor import (
    brain_status,
    kill_switch_monitor,
    recent_rescores,
    run_brain_scan,
)


def _qint(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def create_brain_router():
    router = APIRouter()

    @router.get("/brain/status")
    def status():
        return {"status": "ok", "data": brain_status(), "timestamp": int(time.time() * 1000)}

    @router.post("/brain/scan")
    def scan():
        return run_brain_scan()

    @router.get("/brain/confidence")
    def confidence(request: Request):
        limit = _qint(request.query_params.get("limit"), 50)
        return {"items": recent_rescores(limit), "count": len(recent_rescores(limit))}

    @router.get("/brain/kill-switches")
    def kill_switches():
        return {"detected": kill_switch_monitor.status()}

    @router.post("/brain/kill-switch/{switch}/trigger")
    def trigger_kill_switch(switch: str, request: Request):
        from ..modules.execution.brain_monitor import (
            _now_ms,  # local import to avoid cycle risk
        )
        from ..modules.execution.modes import KILL_SWITCHES, trading_modes
        if switch not in KILL_SWITCHES:
            return {"status": "invalid-switch", "valid": KILL_SWITCHES}
        trading_modes.trigger_kill_switch(switch, True, "manual trigger via /brain/kill-switch")
        return {"status": "ok", "switch": switch, "at": _now_ms(), "killSwitches": trading_modes.kill_switches_status()}

    @router.post("/brain/kill-switch/{switch}/clear")
    def clear_kill_switch(switch: str, request: Request):
        from ..modules.execution.modes import KILL_SWITCHES, trading_modes
        if switch not in KILL_SWITCHES:
            return {"status": "invalid-switch", "valid": KILL_SWITCHES}
        trading_modes.trigger_kill_switch(switch, False, "manual clear via /brain/kill-switch")
        return {"status": "ok", "switch": switch, "killSwitches": trading_modes.kill_switches_status()}

    @router.post("/brain/pause/{condition}")
    def set_pause(condition: str, request: Request):
        from ..modules.execution.brain_monitor import _now_ms
        from ..modules.execution.modes import KILL_SWITCHES
        if condition not in KILL_SWITCHES:
            return {"status": "invalid-condition", "valid": KILL_SWITCHES}
        minutes = _qint(request.query_params.get("minutes"), 30)
        until = _now_ms() + minutes * 60 * 1000
        kill_switch_monitor.pauses[condition] = until
        return {"status": "ok", "condition": condition, "until": until}

    @router.post("/brain/pause/{condition}/clear")
    def clear_pause(condition: str):
        if condition in kill_switch_monitor.pauses:
            del kill_switch_monitor.pauses[condition]
        return {"status": "ok", "condition": condition}

    return router

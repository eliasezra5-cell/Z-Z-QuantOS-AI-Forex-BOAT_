"""Additive MT5 connection router for the dashboard "Connect to MT5" form.

Mounted at ``/api`` before the generic api router (same as the connections
router) so the new endpoints are never shadowed by the legacy
``POST /integrations/{integration_id}/test`` wildcard. Provides:

  - ``POST /integrations/mt5/connect``  save (encrypted) + apply + ping bridge
  - ``GET  /integrations/mt5/connection``  saved credentials (password hidden)
"""
from fastapi import APIRouter
from pydantic import BaseModel

from ..modules.mt5.adapter import connect_with_credentials
from ..persistence.mt5_connection_repository import mt5_connection_repository


class MT5ConnectIn(BaseModel):
    login: str = ""
    password: str = ""
    server: str = ""
    bridgeUrl: str = ""
    mode: str = ""


def _clean(fields):
    return {k: v for k, v in fields.items() if v not in (None, "")}


def create_mt5_router():
    router = APIRouter()

    @router.post("/integrations/mt5/connect")
    async def mt5_connect(body: MT5ConnectIn):
        fields = _clean(body.dict())
        status = await connect_with_credentials(fields)
        return {
            "status": status,
            "saved": {
                "login": body.login,
                "server": body.server,
                "bridgeUrl": body.bridgeUrl,
                "mode": body.mode,
            },
        }

    @router.get("/integrations/mt5/connection")
    async def mt5_connection():
        saved = await mt5_connection_repository.get()
        if not saved:
            return {"connection": None}
        return {
            "connection": {
                "login": saved.get("login") or "",
                "server": saved.get("server") or "",
                "bridgeUrl": saved.get("bridgeUrl") or "",
                "mode": saved.get("mode") or "live",
                "configured": True,
            }
        }

    return router

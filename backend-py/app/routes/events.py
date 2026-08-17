"""Additive API router for the distributed event bus.

Mounted alongside the main router at /api. Exposes bus status, durable
outbox/inbox inspection and a publish endpoint without touching existing routes.
"""
import time

from fastapi import APIRouter

from ..foundation.distributed_event_bus import distributed_event_bus
from ..foundation.event_bus import get_event_history


def create_events_router():
    router = APIRouter()

    @router.get("/events/bus")
    def bus_status():
        return {"status": "ok", "data": distributed_event_bus.status(), "timestamp": int(time.time() * 1000)}

    @router.get("/events/outbox")
    def outbox(status: str = "PENDING"):
        rows = distributed_event_bus.outbox.find({"status": status.upper()})
        return {"count": len(rows), "items": rows[-100:]}

    @router.get("/events/inbox")
    def inbox(limit: int = 100):
        rows = distributed_event_bus.inbox.find({})
        return {"count": len(rows), "items": rows[-max(1, min(limit, 500)):]}

    @router.post("/events/publish")
    def publish(body: dict):
        topic = body.get("topic")
        if not topic:
            return {"status": "invalid-topic", "error": "topic is required"}
        event = distributed_event_bus.publish(topic, body.get("payload") or {}, body.get("meta") or {})
        return {"status": "ok", "event": event, "bus": distributed_event_bus.status()}

    @router.get("/events/history")
    def history(topic: str = "", limit: int = 200):
        rows = get_event_history(topic or None, max(1, min(limit, 1000)))
        return {"count": len(rows), "items": rows}

    return router

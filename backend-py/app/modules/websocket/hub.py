"""WebSocket hub mirroring the Node websocket/hub.js for FastAPI.

Adds optional JWT authentication (token via query param or first message),
per-user presence tracking with ``presence`` broadcasts, and a ``resume``
replay mechanism backed by a bounded in-hub event buffer keyed by event id.
"""
import asyncio
import itertools
import threading
import time

from fastapi import WebSocket

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.security import security

CHANNELS = [
    {"id": "market", "topic": "market:tick", "description": "Live market quotes"},
    {"id": "news", "topic": "news:processed", "description": "Live news items"},
    {"id": "orders", "topic": "trade:opened", "description": "Live orders"},
    {"id": "portfolio", "topic": "trade:closed", "description": "Portfolio updates"},
    {"id": "ai", "topic": "ai:decision", "description": "Live AI decisions"},
    {"id": "alerts", "topic": "alert:delivered", "description": "Live alerts"},
    {"id": "events", "topic": "economic:released", "description": "Economic calendar events"},
    {"id": "risk", "topic": "risk:assessed", "description": "Risk engine assessments"},
    {"id": "presence", "topic": "presence:update", "description": "Connected user presence"},
]

_TOPIC_TO_CHANNEL = {c["topic"]: c["id"] for c in CHANNELS}

_clients = {}
_presence = {}

EVENT_BUFFER_SIZE = 500
_event_buffer = {}
_event_order = []
_event_lock = threading.Lock()
_event_seq = itertools.count()

_MAIN_LOOP = None
_MAIN_LOOP_LOCK = threading.Lock()

ANONYMOUS_USER = "anonymous"


def _verify_token(token):
    """Validate a JWT via the shared REST security mechanism; return the user id."""
    if not token:
        return None
    try:
        payload = security.verify_token(token)
    except Exception:  # noqa: BLE001
        return None
    return payload.get("username") or payload.get("sub")


def _assign_event_id(event):
    eid = event.get("id") or (event.get("meta") or {}).get("eventId")
    if not eid:
        eid = f"{event.get('timestamp') or int(time.time() * 1000):020d}-{next(_event_seq):06d}"
    return eid


def _buffer_event(event):
    """Store an event keyed by id in the bounded buffer, returning it with an id."""
    eid = _assign_event_id(event)
    buffered = {**event, "id": eid}
    with _event_lock:
        if eid not in _event_buffer:
            _event_buffer[eid] = buffered
            _event_order.append(eid)
        if len(_event_order) > EVENT_BUFFER_SIZE:
            oldest = _event_order.pop(0)
            _event_buffer.pop(oldest, None)
    return buffered


def _replay_events(last_event_id=None):
    """Return buffered events newer than ``last_event_id`` in chronological order."""
    with _event_lock:
        order = list(_event_order)
        buffer = dict(_event_buffer)
    if last_event_id and last_event_id in buffer:
        try:
            idx = order.index(last_event_id)
        except ValueError:
            idx = -1
        if idx >= 0:
            return [buffer[i] for i in order[idx + 1:]]
    pending = [buffer[i] for i in order]
    if last_event_id:
        pending = [e for e in pending if str(e["id"]) > str(last_event_id)]
    return pending


def presence():
    """Current presence snapshot: ``{count, users}`` keyed by authenticated user."""
    users = sorted(_presence.keys())
    return {"count": len(users), "users": users}


def _register_client(client_id, user):
    _presence.setdefault(user, []).append(client_id)


def _set_main_loop(loop):
    global _MAIN_LOOP
    with _MAIN_LOOP_LOCK:
        if _MAIN_LOOP is None or not _MAIN_LOOP.is_running():
            _MAIN_LOOP = loop


def _schedule_send(ws, message):
    """Schedule a ``send_json`` on the loop running in a background thread.

    ``call_soon_threadsafe`` ensures the coroutine is created on the owning
    event loop, never in the emitting (background) thread.
    """
    with _MAIN_LOOP_LOCK:
        loop = _MAIN_LOOP
    if loop is None or not loop.is_running():
        return

    def _enqueue():
        try:
            asyncio.create_task(ws.send_json(message))
        except Exception:  # noqa: BLE001 - a dead socket must never break a broadcast
            pass

    try:
        loop.call_soon_threadsafe(_enqueue)
    except Exception:  # noqa: BLE001
        pass


def _unregister_client(client_id, user):
    client_ids = _presence.get(user)
    if client_ids and client_id in client_ids:
        client_ids.remove(client_id)
    if not client_ids:
        _presence.pop(user, None)


def register_websocket(app):
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        _set_main_loop(asyncio.get_running_loop())
        client_host = websocket.client.host if websocket.client else "unknown"
        client_id = f"{client_host}:{int(time.time() * 1000)}"

        token = websocket.query_params.get("token")
        user = _verify_token(token) if token else None
        if token and user is None:
            await websocket.send_json({"type": "error", "message": "Invalid authentication token"})
            await websocket.close(code=4401)
            return
        if user is None:
            user = ANONYMOUS_USER

        _clients[client_id] = {"ws": websocket, "subscriptions": {"market", "presence"}, "user": user}
        _register_client(client_id, user)
        try:
            await websocket.send_json({"type": "connected", "clientId": client_id, "user": user, "channels": [c["id"] for c in CHANNELS]})
            _broadcast_presence()
            first_message = True
            while True:
                raw = await websocket.receive_text()
                try:
                    import json
                    msg = json.loads(raw)
                except Exception:  # noqa: BLE001
                    await websocket.send_json({"type": "error", "message": "Invalid message format"})
                    continue
                if first_message and msg.get("token"):
                    verified = _verify_token(msg["token"])
                    if verified is None:
                        await websocket.send_json({"type": "error", "message": "Invalid authentication token"})
                        await websocket.close(code=4401)
                        break
                    _unregister_client(client_id, user)
                    user = verified
                    _clients[client_id]["user"] = user
                    _register_client(client_id, user)
                    await websocket.send_json({"type": "authenticated", "user": user})
                    _broadcast_presence()
                first_message = False
                if msg.get("type") == "resume":
                    last_event_id = msg.get("lastEventId")
                    count = 0
                    for evt in _replay_events(last_event_id):
                        channel = _TOPIC_TO_CHANNEL.get(evt["topic"])
                        await websocket.send_json({
                            "type": "data",
                            "channel": channel,
                            "topic": evt["topic"],
                            "data": evt.get("payload"),
                            "timestamp": evt.get("timestamp"),
                            "eventId": evt["id"],
                            "replayed": True,
                        })
                        count += 1
                    await websocket.send_json({"type": "resumed", "lastEventId": last_event_id, "count": count})
                    continue
                if msg.get("type") == "subscribe":
                    _clients[client_id]["subscriptions"].add(msg["channel"])
                    await websocket.send_json({"type": "subscribed", "channel": msg["channel"]})
                if msg.get("type") == "unsubscribe":
                    _clients[client_id]["subscriptions"].discard(msg["channel"])
        except Exception:  # noqa: BLE001
            pass
        finally:
            _clients.pop(client_id, None)
            _unregister_client(client_id, user)
            _broadcast_presence()

    def _on_any(event):
        _buffer_event(event)
        channel = _TOPIC_TO_CHANNEL.get(event["topic"])
        if channel:
            _broadcast_sync(channel, event["topic"], event.get("payload"))

    event_bus.on_any(_on_any)
    logger.info(f"WebSocket server initialized ({len(CHANNELS)} channels)")
    return {
        "broadcast": _broadcast_sync,
        "channels": CHANNELS,
        "clientCount": lambda: len(_clients),
        "presence": presence,
    }


def _broadcast_presence():
    message = {"type": "presence", "data": presence(), "timestamp": int(time.time() * 1000)}
    for client_id in list(_clients.keys()):
        client = _clients.get(client_id)
        if not client:
            continue
        _schedule_send(client["ws"], message)


def _broadcast_sync(channel, topic, payload):
    message = {"type": "data", "channel": channel, "topic": topic, "data": payload, "timestamp": int(time.time() * 1000)}
    for client_id in list(_clients.keys()):
        client = _clients.get(client_id)
        if not client or channel not in client["subscriptions"]:
            continue
        _schedule_send(client["ws"], message)

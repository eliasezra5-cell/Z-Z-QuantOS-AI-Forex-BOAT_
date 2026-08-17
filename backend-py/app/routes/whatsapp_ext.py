"""Additive WhatsApp webhook + Connections Manager router.

Mounted under ``/api/v1`` (alongside the existing v1 router). Exposes:

  - ``GET  /integrations/whatsapp/webhook``  Meta hub.challenge verification
  - ``POST /integrations/whatsapp/webhook``  receive messages (X-Hub-Signature-256
    verified); replies "1" -> approve / "2" -> reject the most recent pending
    suggested trade through the auto trade controller
  - ``GET  /integrations/connections``       connection statuses for the sidebar
  - ``POST /integrations/connections``       save/update credentials (encrypted)
  - ``POST /integrations/connections/test``  send a test message

Approval still goes through ``approve_suggested`` / ``reject_suggested``; the
actual execution remains gated by the risk engine — nothing here bypasses it.
"""
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from ..modules.integrations.connections_manager import connections_manager, init_connections_manager
from ..modules.integrations.whatsapp_client import init_whatsapp_alerts, whatsapp_alert_client

router = APIRouter()


class ConnectionIn(BaseModel):
    api_token: str = ""
    phone_number_id: str = ""
    webhook_secret: str = ""
    admin_number: str = ""
    chat_id: str = ""
    host: str = ""
    port: str = ""
    user: str = ""
    password: str = ""
    from_addr: str = ""
    to_addr: str = ""
    is_active: bool = True


class ConnectionTestIn(BaseModel):
    provider: str = "whatsapp"
    chat_id: str = ""


# --------------------------------------------------------------------------- #
# WhatsApp webhook
# --------------------------------------------------------------------------- #
@router.get("/integrations/whatsapp/webhook")
async def whatsapp_webhook_verify(request: Request):
    """Meta subscription verification (hub.challenge handshake).

    Meta sends ``hub.mode``, ``hub.verify_token`` and ``hub.challenge`` as query
    params (with dots), so they are read from the raw query string.
    """
    qs = request.query_params
    mode = qs.get("hub.mode", "")
    verify_token = qs.get("hub.verify_token", "")
    challenge = qs.get("hub.challenge", "")
    if mode == "subscribe" and verify_token and whatsapp_alert_client.webhook_secret:
        if verify_token == whatsapp_alert_client.webhook_secret:
            return PlainTextResponse(challenge or "")
    return JSONResponse({"error": "verification failed"}, status_code=403)


@router.post("/integrations/whatsapp/webhook")
async def whatsapp_webhook_receive(request: Request):
    """Receive WhatsApp messages; verify X-Hub-Signature-256 before processing."""
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not whatsapp_alert_client.verify_signature(raw_body, signature):
        return JSONResponse({"error": "invalid signature"}, status_code=401)
    try:
        payload = json.loads(raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body)
    except (ValueError, TypeError):
        return JSONResponse({"error": "invalid payload"}, status_code=400)
    results = _process_webhook_payload(payload)
    return {"status": "ok", "results": results}


def _process_webhook_payload(payload):
    """Parse a Meta messages webhook payload and route 1/2 replies.

    Returns a list of per-message outcomes for observability.
    """
    results = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for message in value.get("messages", []) or []:
                from_number = message.get("from")
                text = ((message.get("text") or {}) or {}).get("body") or ""
                outcome = _handle_message(from_number, text.strip())
                results.append(outcome)
    return results


def _handle_message(from_number, text):
    """Route a single WhatsApp message.

    "1" -> approve / "2" -> reject the most recent pending suggested trade.
    ANY OTHER non-empty text is treated as a chat message and routed through
    the conversational assistant (preference training -> intent execution ->
    free-form AI reply).
    """
    raw_text = (text or "").strip()
    text = raw_text.lower()
    reply = None
    if text in ("1", "2"):
        from ..modules.execution.auto_controller import auto_trade_controller

        pending = [r for r in auto_trade_controller.suggested_trades(status="pending")]
        if not pending:
            reply = "No pending AI suggestion to review."
        else:
            latest = max(pending, key=lambda r: r.get("createdAt", 0))
            if text == "1":
                updated = auto_trade_controller.approve_suggested(latest["id"])
                action = "approved" if updated else "missing"
            else:
                updated = auto_trade_controller.reject_suggested(latest["id"])
                action = "rejected" if updated else "missing"
            reply = f"{latest.get('symbol')} {latest.get('side')} ({action})"
    elif raw_text.startswith("/"):
        # Telegram-style slash commands now work on WhatsApp too. The reply
        # text is produced by the shared bot handler (no Telegram send).
        from ..modules.integrations.telegram_bot import telegram_bot

        try:
            reply = telegram_bot.reply_for_command(raw_text, from_number)
        except Exception as err:  # noqa: BLE001 - never break webhook on command failure
            reply = f"Sorry, I couldn't process that: {err}"
    elif raw_text:
        # Manual-forward news ingestion: any non-command text is also pushed
        # through the news pipeline (persist + ws_news publish) so it appears in
        # the News Terminal AI News Feed. Never breaks webhook processing.
        from ..modules.news.whatsapp_manual import ingest_whatsapp_manual

        try:
            ingest_whatsapp_manual(from_number, raw_text)
        except Exception as err:  # noqa: BLE001 - news ingest must never break webhook
            reply = f"News ingest failed: {err}"
        from ..modules.ai.conversation import process_message

        try:
            reply = process_message(raw_text)
        except Exception as err:  # noqa: BLE001 - never break webhook on chat failure
            reply = f"Sorry, I couldn't process that: {err}"
    if reply and from_number:
        try:
            whatsapp_alert_client.send_text(from_number, reply)
        except Exception as err:  # noqa: BLE001 - never break webhook on send failure
            reply = f"{reply} (reply failed: {err})"
    return {"from": from_number, "text": text, "reply": reply, "at": int(time.time() * 1000)}


# --------------------------------------------------------------------------- #
# Connections Manager (sidebar)
# --------------------------------------------------------------------------- #
@router.get("/integrations/connections")
def list_connections():
    return {"connections": connections_manager.list_statuses()}


@router.post("/integrations/connections")
def save_connection(provider: str, body: ConnectionIn):
    if provider not in ("whatsapp", "telegram", "email", "mt5"):
        return JSONResponse({"error": f"unsupported provider {provider}"}, status_code=400)
    saved = connections_manager.save(provider, body.dict(exclude_unset=True))
    return {"connection": saved, "provider": provider}


@router.post("/integrations/connections/test")
def test_connection(body: ConnectionTestIn):
    result = connections_manager.test(body.provider, chat_id=body.chat_id)
    return {"provider": body.provider, "result": result}


def create_whatsapp_router() -> APIRouter:
    init_connections_manager()
    init_whatsapp_alerts()
    return router

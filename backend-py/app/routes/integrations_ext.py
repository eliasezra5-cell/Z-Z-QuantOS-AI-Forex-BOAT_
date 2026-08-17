"""Additive API router for real enterprise integrations.

Mounted alongside the main router at /api. Provides:
  - POST /integrations/tradingview/webhook  (secure, risk-gated external signals)
  - POST /integrations/telegram/command     (bot command dispatch)
  - POST /integrations/discord/send         (alert delivery)
  - GET  /integrations/real/status          (self-test summary)
"""
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..modules.integrations.tradingview_webhook import tradingview_webhook, TradingViewWebhookError
from ..modules.integrations.telegram_bot import telegram_bot
from ..modules.integrations.discord_client import discord_alert_client


def create_enterprise_integrations_router():
    router = APIRouter()

    @router.get("/integrations/real/status")
    def real_integrations_status():
        return {
            "status": "ok",
            "timestamp": int(time.time() * 1000),
            "integrations": {
                "tradingview": tradingview_webhook.self_test(),
                "telegram": telegram_bot.self_test(),
                "discord": discord_alert_client.self_test(),
            },
        }

    @router.post("/integrations/tradingview/webhook")
    async def tradingview_webhook_endpoint(request: Request):
        body = await request.body()
        signature = request.headers.get("x-webhook-signature") or request.headers.get("x-tradingview-signature") or ""
        timestamp = request.headers.get("x-webhook-timestamp")
        if not signature:
            return JSONResponse({"error": {"code": "MISSING_SIGNATURE", "message": "x-webhook-signature header required"}}, status_code=401)
        try:
            result = tradingview_webhook.process(body, signature, timestamp)
        except TradingViewWebhookError:
            return JSONResponse({"error": {"code": "INVALID_SIGNATURE", "message": "signature verification failed"}}, status_code=401)
        status = 202 if result["approved"] else 403
        return JSONResponse(result, status_code=status)

    @router.post("/integrations/telegram/command")
    def telegram_command(body: dict):
        text = body.get("text") or ""
        chat_id = body.get("chatId")
        out = telegram_bot.handle_command(text, chat_id)
        return {"status": "ok", "outbox": out, "timestamp": int(time.time() * 1000)}

    @router.post("/integrations/discord/send")
    def discord_send(body: dict):
        content = body.get("content") or ""
        url = body.get("url")
        username = body.get("username")
        out = discord_alert_client.send_alert(content, url=url, username=username)
        return {"status": "ok", "outbox": out, "timestamp": int(time.time() * 1000)}

    return router

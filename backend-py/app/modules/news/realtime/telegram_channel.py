"""Telegram auto-reader using the official Telegram Bot API (additive).

Two independent (but offset-shared) collectors:

- Channel posts: polls ``channel_post`` updates with a bot token
  (``config.botToken`` or the ``TELEGRAM_BOT_TOKEN`` env var). The bot must be
  an admin of each configured channel (``config.channels`` list of usernames or
  full ``t.me/...`` links).
- Private messages (``poll_manual_messages``): polls ``message`` updates and
  routes them to the manual-forward ingestion path. Only the token is needed
  (no channel source required).

Both consumers share the single ``_OFFSETS`` cursor per bot token so a process
never re-delivers a post or a message across poll cycles. Offset-based long
polling ensures each update is collected exactly once per running process. No
unofficial libraries are used.
"""
import json
import os
import time

import httpx

from ....foundation.logger import logger

BOT_API = "https://api.telegram.org/bot{token}/getUpdates"
TIMEOUT_SECONDS = 15

# Last consumed update_id per bot token, so a poll cycle never re-delivers
# posts that were already collected. Lives for the process lifetime; safe to
# reset (duplicates are caught by the ingest dedup store anyway).
_OFFSETS = {}


def _normalize_channel(channel):
    ch = str(channel).strip()
    ch = ch.split("?")[0]
    if "t.me/" in ch:
        ch = ch.rsplit("t.me/", 1)[-1]
    ch = ch.lstrip("@")
    return ch


class TelegramChannelRealtimeCollector:
    id = "telegram_channel"
    name = "Telegram Channels (Bot API)"
    collector_type = "telegram_channel"

    def __init__(self, config=None):
        self.config = config or {}
        self.bot_token = self.config.get("botToken") or os.environ.get("TELEGRAM_BOT_TOKEN", "")

    def collect(self, params=None):
        token = self.bot_token
        if not token:
            return []
        channels = [_normalize_channel(c) for c in (self.config.get("channels") or [])]
        channels = [c for c in channels if c]
        if not channels:
            return []
        limit = (params or {}).get("limit", 10)
        offset = _OFFSETS.get(token, 0)
        updates = self._get_updates(token)
        items = []
        for update in updates:
            if update.get("update_id", 0) < offset:
                continue
            post = update.get("channel_post") or update.get("message") or {}
            if not post:
                continue
            chat = post.get("chat") or {}
            chat_user = str(chat.get("username") or "").lstrip("@")
            chat_id = str(chat.get("id") or "")
            if chat_user not in channels and chat_id not in channels:
                continue
            text = (post.get("text") or post.get("caption") or "").strip()
            if not text:
                continue
            ch = chat_user or chat_id
            message_id = post.get("message_id")
            published_ms = int(post.get("date") or time.time()) * 1000
            items.append({
                "source": f"@{ch}",
                "sourceType": self.collector_type,
                "title": text[:300],
                "summary": text[:2000],
                "url": f"https://t.me/{ch}/{message_id}" if message_id else None,
                "category": "social",
                "impact": 0.3,
                "collector": self.id,
                "collectorType": self.collector_type,
                "channel": ch,
                "time": published_ms,
                "raw": {"sourceType": self.collector_type, "chatId": chat_id, "messageId": message_id},
            })
            if len(items) >= limit:
                break
        return items

    def _get_updates(self, token):
        url = BOT_API.format(token=token)
        params = {
            "offset": _OFFSETS.get(token, 0),
            "timeout": 0,
            "limit": 100,
            "allowed_updates": json.dumps(["channel_post", "message"]),
        }
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                res = client.get(url, params=params)
                if res.status_code == 401:
                    logger.warn("Telegram Bot API token invalid (401)")
                    return []
                res.raise_for_status()
                data = res.json()
        except Exception as exc:  # noqa: BLE001 - network failure is non-fatal
            logger.warn(f"Telegram getUpdates failed: {exc}")
            return []
        if not data.get("ok"):
            logger.warn(f"Telegram getUpdates error: {data.get('description')}")
            return []
        updates = data.get("result") or []
        if updates:
            _OFFSETS[token] = max(u.get("update_id", 0) for u in updates) + 1
        return updates


def poll_manual_messages(token=None):
    """Poll for private ``message`` updates routed to the manual-forward path.

    Works with only the bot token set (no channel source required). Reuses the
    same shared ``_OFFSETS`` cursor as the channel collector so a message is
    never re-delivered across poll cycles. Only the cursor is advanced past the
    ``message`` updates actually consumed; ``channel_post`` updates are left
    untouched for the per-source channel collector.

    Never raises: any network/API failure is logged and returns [] (the cursor
    is not advanced, so the same updates are retried next cycle).
    """
    token = (token or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
    if not token:
        return []
    url = BOT_API.format(token=token)
    params = {
        "offset": _OFFSETS.get(token, 0),
        "timeout": 0,
        "limit": 100,
        "allowed_updates": json.dumps(["channel_post", "message"]),
    }
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            res = client.get(url, params=params)
            if res.status_code == 401:
                logger.warn("Telegram Bot API token invalid (401)")
                return []
            res.raise_for_status()
            data = res.json()
    except Exception as exc:  # noqa: BLE001 - network failure is non-fatal
        logger.warn(f"Telegram manual-message poll failed: {exc}")
        return []
    if not data.get("ok"):
        logger.warn(f"Telegram getUpdates error: {data.get('description')}")
        return []
    updates = data.get("result") or []
    routed = []
    last_processed = _OFFSETS.get(token, 0)
    for update in updates:
        if update.get("update_id", 0) < last_processed:
            continue
        post = update.get("message")
        if not post:
            continue
        chat = post.get("chat") or {}
        if str(chat.get("type") or "").lower() != "private":
            continue
        text = (post.get("text") or post.get("caption") or "").strip()
        if not text:
            continue
        routed.append({"chat_id": str(chat.get("id") or ""), "text": text})
        last_processed = max(last_processed, update.get("update_id", 0))
    if routed:
        _OFFSETS[token] = last_processed + 1
    return routed


def register(config=None):
    return TelegramChannelRealtimeCollector(config or {})

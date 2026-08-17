"""Email manual-forward news ingestion (additive).

Mirrors ``whatsapp_manual.py`` / ``telegram_manual.py``: any inbound email that
is not a recognized bot command is treated as a news event. It is saved into the
same ``NewsItem`` store used by the realtime collectors, pushed through the
unified AI pipeline (``news:ingest`` -> analysis -> ``news:processed`` -> 5-agent
decision pipeline) and published to Redis Pub/Sub ``ws_news`` so the frontend
News Terminal picks it up in real time.
"""
import asyncio
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.redis_pubsub import redis_pubsub
from ...persistence import news_repository

SOURCE_TYPE = "email_manual"


def _publish_news(item):
    """Mirror the realtime registry's publish: ingest pipeline + ws_news."""
    event_bus.emit("news:ingest", {"payload": item})
    try:
        redis_pubsub.publish("ws_news", item)
    except Exception as exc:  # noqa: BLE001 - Redis is optional
        logger.warn(f"ws_news pub/sub publish failed: {exc}")


async def _persist_and_publish(item):
    row = await news_repository.insert_item(item)
    _publish_news(row or item)
    return row or item


def ingest_email_manual(sender, text):
    """Save a manual-forward email message as a news event.

    Returns the persisted item. When called from an async context the coroutine
    is scheduled on the running loop; otherwise it runs synchronously. Safe in
    both cases.
    """
    body = (text or "").strip()
    if not body:
        return None
    now_ms = int(time.time() * 1000)
    item = {
        "sourceId": None,
        "source": f"Email {sender}" if sender else "Email",
        "sourceType": SOURCE_TYPE,
        "title": body[:300],
        "summary": body[:2000],
        "url": None,
        "category": "social",
        "impact": 0.3,
        "collector": "email",
        "collectorType": SOURCE_TYPE,
        "channel": sender,
        "time": now_ms,
        "raw": {"sourceType": SOURCE_TYPE, "from": sender},
    }
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_persist_and_publish(item))
    asyncio.ensure_future(_persist_and_publish(item))
    return item

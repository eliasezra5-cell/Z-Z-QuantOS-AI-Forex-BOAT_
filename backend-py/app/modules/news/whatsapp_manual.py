"""WhatsApp manual-forward news ingestion (additive).

Any inbound WhatsApp message that is not the "1"/"2" trade-approval shorthand
is treated as a news event: it is saved into the same ``NewsItem`` store used
by the realtime collectors, pushed through the unified AI pipeline
(``news:ingest`` -> analysis -> ``news:processed`` -> 5-agent decision
pipeline), published to Redis Pub/Sub ``ws_news`` for the frontend News
Terminal, and acknowledged with an auto-reply.

The webhook handler calls :func:`ingest_whatsapp_manual` for non-1/2 text.
Persistence reuses ``news_repository.insert_item`` (same table as RSS/X/blog/
Telegram), so the frontend News Terminal and the AI pipeline treat manual
forwards identically to collected news.
"""
import asyncio
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.redis_pubsub import redis_pubsub
from ...persistence import news_repository

SOURCE_TYPE = "whatsapp_manual"
AUTO_REPLY = "News received. AI is analyzing..."


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


def ingest_whatsapp_manual(from_number, text):
    """Save a manual-forward WhatsApp message as a news event.

    Returns the persisted item. When called from an async context (webhook
    route) the coroutine is scheduled on the running loop; otherwise it runs
    synchronously. Safe in both cases.
    """
    body = (text or "").strip()
    if not body:
        return None
    now_ms = int(time.time() * 1000)
    item = {
        "sourceId": None,
        "source": f"WhatsApp {from_number}" if from_number else "WhatsApp",
        "sourceType": SOURCE_TYPE,
        "title": body[:300],
        "summary": body[:2000],
        "content": body[:20000],
        "url": None,
        "category": "social",
        "impact": 0.3,
        "collector": "whatsapp",
        "collectorType": SOURCE_TYPE,
        "channel": from_number,
        "time": now_ms,
        "raw": {"sourceType": SOURCE_TYPE, "from": from_number},
    }
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_persist_and_publish(item))
    asyncio.ensure_future(_persist_and_publish(item))
    return item

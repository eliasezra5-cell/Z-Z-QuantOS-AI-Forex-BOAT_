"""Realtime collector registry + autonomous polling.

Sources are loaded dynamically from the persistence repository (admin-created
sources via ``/api/v1/news/sources``). Each source maps to a collector by its
``type``. ``poll_all_collectors`` runs one autonomous poll cycle: it fetches
from every enabled source, normalizes items, dedups against the recent window,
persists through the repository, and publishes each item to the ingest
pipeline (``news:ingest``) and to Redis Pub/Sub ``ws_news`` for the frontend
News Terminal.
"""
import time

from ....foundation.event_bus import event_bus
from ....foundation.logger import logger
from ....persistence import news_repository
from .rss import RssRealtimeCollector
from .telegram import TelegramRealtimeCollector
from .telegram_channel import TelegramChannelRealtimeCollector, poll_manual_messages
from .x_twitter import XTwitterRealtimeCollector
from .web import WebRealtimeCollector
from .financial_api import FinancialApiRealtimeCollector
from .reddit import RedditRealtimeCollector

_COLLECTOR_TYPES = {
    "reddit": RedditRealtimeCollector,
    "rss": RssRealtimeCollector,
    "telegram": TelegramRealtimeCollector,
    "telegram_channel": TelegramChannelRealtimeCollector,
    "twitter": XTwitterRealtimeCollector,
    "x_twitter": XTwitterRealtimeCollector,
    "web": WebRealtimeCollector,
    "web_blog": WebRealtimeCollector,
    "website": WebRealtimeCollector,
    "financial_api": FinancialApiRealtimeCollector,
}

realtime_collectors_registry = {}


def register_realtime_collector(collector):
    realtime_collectors_registry[collector.id] = collector
    return collector


def _build_collector(source):
    source_type = source.get("type") or "rss"
    cls = _COLLECTOR_TYPES.get(source_type)
    if cls is None:
        logger.warn(f"No realtime collector for source type '{source_type}' (source {source.get('id')})")
        return None
    config = dict(source.get("config") or {})
    config.setdefault("sourceName", source.get("name"))
    return cls(config)


def _publish_news(item):
    """Publish a processed news item to the frontend pipeline + Redis Pub/Sub."""
    event_bus.emit("news:ingest", {"payload": item})
    try:
        from ....foundation.redis_pubsub import redis_pubsub

        redis_pubsub.publish("ws_news", item)
    except Exception as exc:  # noqa: BLE001 - Redis is optional
        logger.warn(f"ws_news pub/sub publish failed: {exc}")


async def _poll_telegram_manual_messages():
    """Poll Telegram DMs (only the token is needed) and route each message.

    Non-command texts are ingested through the manual-forward pipeline; commands
    (``/status``, ``/trades``, ``/approve``) are dispatched to the Telegram bot.
    Never raises: any Telegram failure is logged and skipped so a broken bot
    token can never stop the poll cycle.
    """
    import os

    from ...integrations.telegram_bot import telegram_bot

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return 0
    try:
        routed = poll_manual_messages(token)
    except Exception as exc:  # noqa: BLE001 - Telegram polling is best-effort
        logger.warn(f"Telegram manual-message poll failed: {exc}")
        return 0
    if not routed:
        return 0
    handled = 0
    for msg in routed:
        try:
            telegram_bot.handle_command(msg.get("text") or "", msg.get("chat_id"))
            handled += 1
        except Exception as exc:  # noqa: BLE001 - one bad message must not stop the cycle
            logger.warn(f"Telegram message routing failed (chat {msg.get('chat_id')}): {exc}")
    return handled


async def collect_from_sources(limit_per_source=10):
    """One autonomous polling cycle across all enabled repository sources."""
    sources = await news_repository.list_sources()
    collected = []
    errors = []
    for source in sources:
        if not source.get("enabled", True):
            continue
        collector = _build_collector(source)
        if collector is None:
            continue
        recent = []
        if isinstance(collector, WebRealtimeCollector):
            try:
                recent = await news_repository.list_items(source=source.get("name"), limit=5)
            except Exception as exc:  # noqa: BLE001 - dedupe lookup is best-effort
                logger.warn(f"Web dedupe lookup failed for {source.get('id')}: {exc}")
                recent = []
        try:
            items = collector.collect({"limit": limit_per_source, "recent": recent})
            for item in items:
                item["sourceId"] = source.get("id")
                collected.append(item)
            # Successful poll: clear any previously recorded fetch error so the
            # UI reliability list stops showing the red Error badge.
            if (source.get("config") or {}).get("lastError"):
                try:
                    clean = {k: v for k, v in (source.get("config") or {}).items() if k not in ("lastError", "lastErrorAt")}
                    await news_repository.update_source(source.get("id"), {"config": clean})
                except Exception as exc2:  # noqa: BLE001 - error surfacing must never break the poll cycle
                    logger.warn(f"Failed to clear source error for {source.get('id')}: {exc2}")
            # Persist the latest web content hash so the next cycle can skip an
            # unchanged page before it is re-inserted (per-source dedupe).
            if isinstance(collector, WebRealtimeCollector) and items:
                last_hash = next((it.get("contentHash") for it in reversed(items) if it.get("contentHash")), None)
                if last_hash:
                    try:
                        cfg = dict(source.get("config") or {})
                        cfg["lastContentHash"] = last_hash
                        await news_repository.update_source(source.get("id"), {"config": cfg})
                    except Exception as exc2:  # noqa: BLE001 - hash persistence is best-effort
                        logger.warn(f"Failed to persist web content hash for {source.get('id')}: {exc2}")
        except Exception as exc:  # noqa: BLE001 - a failing source must not stop the cycle
            errors.append({"source": source.get("id"), "error": str(exc)})
            logger.warn(f"Poll failed for source {source.get('id')}: {exc}")
            # Surface the failure on the source itself (stored in config) so the
            # UI Source Reliability list can show a red Error badge (no silent failures).
            try:
                err_cfg = dict(source.get("config") or {})
                err_cfg["lastError"] = str(exc)
                err_cfg["lastErrorAt"] = int(time.time() * 1000)
                await news_repository.update_source(source.get("id"), {"config": err_cfg})
            except Exception as exc2:  # noqa: BLE001 - error surfacing must never break the poll cycle
                logger.warn(f"Failed to record source error for {source.get('id')}: {exc2}")
    return {"collected": len(collected), "items": collected, "errors": errors}


async def poll_all_collectors(limit_per_source=10):
    """Poll all sources, then persist + publish each real item."""
    telegram_routed = await _poll_telegram_manual_messages()
    result = await collect_from_sources(limit_per_source)
    persisted = 0
    for item in result["items"]:
        row = await news_repository.insert_item(item)
        if row:
            persisted += 1
        _publish_news(row or item)
        event_bus.emit("news:raw-collected", {"item": item})
    result["persisted"] = persisted
    result["cycleAt"] = int(time.time() * 1000)
    result["telegramMessagesRouted"] = telegram_routed
    return result


def register_default_realtime_collectors():
    for cid, cls in _COLLECTOR_TYPES.items():
        if cid not in realtime_collectors_registry:
            register_realtime_collector(cls({}))


def init_realtime_news_collectors():
    register_default_realtime_collectors()
    logger.info(f"Realtime news collectors initialized: {list(realtime_collectors_registry)}")
    event_bus.emit("news:realtime-collectors-ready", {"collectors": list(realtime_collectors_registry)})
    return realtime_collectors_registry

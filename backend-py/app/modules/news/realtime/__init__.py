"""Real news collectors (NO PLACEHOLDERS).

Replaces the placeholder ``[RSS pending]`` / ``[Telegram pending]`` collectors
with real network fetches (RSS, Telegram, X, web, financial API). Sources are
read dynamically from the persistence repository, so admin-created sources
drive autonomous polling. Every collector normalizes output to the same raw
news payload the ingestion/analysis pipeline expects.
"""
from .registry import (
    realtime_collectors_registry,
    register_realtime_collector,
    collect_from_sources,
    poll_all_collectors,
)
from .rss import RssRealtimeCollector
from .telegram import TelegramRealtimeCollector
from .telegram_channel import TelegramChannelRealtimeCollector
from .x_twitter import XTwitterRealtimeCollector
from .web import WebRealtimeCollector
from .financial_api import FinancialApiRealtimeCollector

__all__ = [
    "realtime_collectors_registry",
    "register_realtime_collector",
    "collect_from_sources",
    "poll_all_collectors",
    "RssRealtimeCollector",
    "TelegramRealtimeCollector",
    "TelegramChannelRealtimeCollector",
    "XTwitterRealtimeCollector",
    "WebRealtimeCollector",
    "FinancialApiRealtimeCollector",
]

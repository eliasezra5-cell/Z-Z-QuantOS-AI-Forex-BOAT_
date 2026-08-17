"""Seed default news sources on first boot."""

from app.persistence import news_repository

DEFAULT_SOURCES = [
    {
        "name": "Investing.com — Commodities",
        "type": "rss",
        "config": {
            "feedUrls": ["https://www.investing.com/rss/news_11.rss"],
            "sourceName": "Investing.com — Commodities",
        },
    },
    {
        "name": "Investing.com — Forex",
        "type": "rss",
        "config": {
            "feedUrls": ["https://www.investing.com/rss/news_1.rss"],
            "sourceName": "Investing.com — Forex",
        },
    },
    {
        "name": "FXStreet — News",
        "type": "rss",
        "config": {
            "feedUrls": ["https://www.fxstreet.com/rss/news"],
            "sourceName": "FXStreet — News",
        },
    },
    {
        "name": "Kitco — Gold News",
        "type": "rss",
        "config": {
            "feedUrls": ["https://www.kitco.com/rss/KitcoNewsRSS.xml"],
            "sourceName": "Kitco — Gold News",
        },
    },
]


async def seed_default_news_sources():
    """Insert default news sources only when none exist yet."""
    try:
        existing = await news_repository.list_sources()
        if existing:
            return
        for source in DEFAULT_SOURCES:
            await news_repository.add_source(source)
    except Exception as exc:  # noqa: BLE001 - seeding must never block boot
        import logging

        logging.getLogger("news.seed").warning("Failed to seed default news sources: %s", exc)

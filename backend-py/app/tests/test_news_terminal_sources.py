"""Tests for the News Terminal finalization modules (additive).

Covers:
  - Module 1: official Telegram Bot API channel collector + ``telegram_channel``
    source type registration.
  - Module 2: X/Twitter and web-blog realtime collectors remain wired into the
    shared ``poll_all_collectors`` persist + publish pipeline.
  - Module 3: WhatsApp manual-forward ingestion (non-1/2 text) triggers the
    unified ingest pipeline and persists to the same NewsItem store.

No real network: collectors are fed canned responses via mocks.
"""
import asyncio
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test_news_terminal")
os.environ["POSTGRES_ENABLED"] = "false"
os.environ["DATABASE_URL"] = ""
os.environ.pop("TELEGRAM_BOT_TOKEN", None)

from app.modules.news.realtime.registry import (  # noqa: E402
    _COLLECTOR_TYPES,
    _build_collector,
    collect_from_sources,
    poll_all_collectors,
)
from app.modules.news.realtime.telegram_channel import (  # noqa: E402
    TelegramChannelRealtimeCollector,
    _OFFSETS,
    _normalize_channel,
    poll_manual_messages,
)
from app.modules.news.realtime.web import (  # noqa: E402
    WebRealtimeCollector,
    _fingerprint,
)
from app.modules.news.whatsapp_manual import (  # noqa: E402
    AUTO_REPLY,
    SOURCE_TYPE,
    ingest_whatsapp_manual,
)
from app.persistence import news_repository  # noqa: E402


def _telegram_updates_payload():
    return {
        "ok": True,
        "result": [
            {
                "update_id": 101,
                "channel_post": {
                    "message_id": 42,
                    "chat": {"id": -1001234567890, "username": "goldalerts", "title": "Gold Alerts", "type": "channel"},
                    "date": 1700000000,
                    "text": "Gold surges past $2400 on Fed cut bets",
                },
            },
            {
                "update_id": 102,
                "message": {
                    "message_id": 7,
                    "chat": {"id": 999, "username": "privatechat", "type": "private"},
                    "date": 1700000001,
                    "text": "ignored",
                },
            },
        ],
    }


class _FakeTelegramResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


# --------------------------------------------------------------------------- #
# Module 1: Telegram Bot API channel collector
# --------------------------------------------------------------------------- #
def test_telegram_channel_type_registered_in_registry():
    assert "telegram_channel" in _COLLECTOR_TYPES
    assert _COLLECTOR_TYPES["telegram_channel"] is TelegramChannelRealtimeCollector
    collector = _build_collector({"type": "telegram_channel", "name": "Gold", "config": {}})
    assert isinstance(collector, TelegramChannelRealtimeCollector)


def test_telegram_channel_normalizes_links_and_usernames():
    assert _normalize_channel("@goldalerts") == "goldalerts"
    assert _normalize_channel("https://t.me/goldalerts") == "goldalerts"
    assert _normalize_channel("t.me/goldalerts?x=1") == "goldalerts"


def test_telegram_channel_requires_token():
    collector = TelegramChannelRealtimeCollector({"channels": ["@goldalerts"]})
    assert collector.collect({}) == []


def test_telegram_channel_parses_bot_api_updates():
    _OFFSETS.clear()
    payload = _telegram_updates_payload()
    with mock.patch("httpx.Client.get", return_value=_FakeTelegramResponse(payload)):
        items = TelegramChannelRealtimeCollector({"botToken": "123:abc", "channels": ["@goldalerts"]}).collect({})
    assert len(items) == 1
    assert items[0]["title"] == "Gold surges past $2400 on Fed cut bets"
    assert items[0]["source"] == "@goldalerts"
    assert items[0]["url"] == "https://t.me/goldalerts/42"
    assert items[0]["sourceType"] == "telegram_channel"
    assert items[0]["time"] == 1700000000 * 1000
    assert _OFFSETS.get("123:abc") == 103


def test_telegram_channel_advances_offset_no_duplicates():
    _OFFSETS.clear()
    payload = _telegram_updates_payload()
    collector = TelegramChannelRealtimeCollector({"botToken": "123:abc", "channels": ["@goldalerts"]})
    with mock.patch("httpx.Client.get", return_value=_FakeTelegramResponse(payload)):
        first = collector.collect({})
    assert len(first) == 1
    with mock.patch("httpx.Client.get", return_value=_FakeTelegramResponse(payload)):
        second = collector.collect({})
    assert second == []


def test_telegram_channel_skips_non_channel_messages():
    _OFFSETS.clear()
    payload = {"ok": True, "result": [{"update_id": 5, "message": {"chat": {"type": "private"}}}]}
    with mock.patch("httpx.Client.get", return_value=_FakeTelegramResponse(payload)):
        items = TelegramChannelRealtimeCollector({"botToken": "t", "channels": ["@goldalerts"]}).collect({})
    assert items == []


# --------------------------------------------------------------------------- #
# Module 2: X/Twitter + web-blog wired into the shared pipeline
# --------------------------------------------------------------------------- #
def test_twitter_and_web_blog_types_mapped_in_registry():
    assert _COLLECTOR_TYPES.get("x_twitter") is not None
    assert _COLLECTOR_TYPES.get("twitter") is _COLLECTOR_TYPES.get("x_twitter")
    assert _COLLECTOR_TYPES.get("web_blog") is _COLLECTOR_TYPES.get("web")
    twitter_collector = _build_collector({"type": "x_twitter", "name": "X", "config": {}})
    assert twitter_collector is not None
    assert twitter_collector.id == "twitter"
    blog_collector = _build_collector({"type": "web_blog", "name": "Blog", "config": {}})
    assert blog_collector is not None


def test_poll_all_collectors_persists_and_publishes():
    source = {
        "id": "test-x-feed",
        "name": "X Feed",
        "type": "x_twitter",
        "config": {"handles": ["@reuters"], "bearerToken": "test-token"},
        "enabled": True,
    }
    item = {
        "source": "X@reuters",
        "title": "Fed signals rate cut",
        "summary": "Powell hints at easing",
        "url": "https://x.com/reuters/status/1",
        "category": "social",
        "impact": 0.3,
        "collector": "twitter",
        "collectorType": "twitter",
        "time": int(__import__("time").time() * 1000),
        "raw": True,
    }
    with mock.patch("app.modules.news.realtime.registry.news_repository.list_sources", return_value=[source]):
        with mock.patch("app.modules.news.realtime.x_twitter.XTwitterRealtimeCollector.collect", return_value=[item]):
            with mock.patch("app.foundation.redis_pubsub.redis_pubsub.publish") as publish_mock:
                result = asyncio.run(poll_all_collectors(limit_per_source=5))
    assert result["collected"] == 1
    assert result["persisted"] == 1
    assert publish_mock.called
    assert publish_mock.call_args[0][0] == "ws_news"
    saved = asyncio.run(news_repository.list_items(limit=5))
    assert any(i["title"] == "Fed signals rate cut" for i in saved)


# --------------------------------------------------------------------------- #
# Module 3: WhatsApp manual-forward ingestion
# --------------------------------------------------------------------------- #
def test_whatsapp_manual_ingest_persists_and_publishes():
    with mock.patch("app.modules.news.whatsapp_manual.redis_pubsub.publish") as publish_mock:
        item = ingest_whatsapp_manual("+15551234567", "BREAKING: Oil prices crash 5%")
    assert item is not None
    assert (item.get("raw") or {}).get("sourceType") == SOURCE_TYPE
    assert publish_mock.called
    assert publish_mock.call_args[0][0] == "ws_news"
    saved = asyncio.run(news_repository.list_items(limit=10))
    assert any(i["source"] == "WhatsApp +15551234567" for i in saved)
    assert any(i["raw"].get("sourceType") == SOURCE_TYPE for i in saved)


def test_whatsapp_manual_ingest_ignores_empty():
    assert ingest_whatsapp_manual("+15551234567", "   ") is None


def test_whatsapp_manual_auto_reply_text():
    assert AUTO_REPLY == "News received. AI is analyzing..."


# --------------------------------------------------------------------------- #
# Module 3b: social-bot wiring (Telegram / WhatsApp / Email -> news pipeline)
# --------------------------------------------------------------------------- #
def test_telegram_chat_message_ingests_manual_news():
    """A non-command Telegram message is both news-ingested and answered."""
    from app.modules.integrations.telegram_bot import TelegramBotClient

    client = TelegramBotClient(token="tok:wiring", chat_id="555")
    with mock.patch.object(TelegramBotClient, "_ingest_manual") as ingest:
        with mock.patch("app.modules.integrations.telegram_bot.TelegramBotClient.send_message", return_value=None):
            reply = client._handle_chat_message("BREAKING: NFP surprise", "555")
    assert reply is not None
    ingest.assert_called_once_with("BREAKING: NFP surprise", "555")


def test_telegram_chat_message_ingest_failure_never_breaks_chat():
    from app.modules.integrations.telegram_bot import TelegramBotClient

    client = TelegramBotClient(token="tok:wiring2", chat_id="555")
    with mock.patch.object(TelegramBotClient, "_ingest_manual", side_effect=RuntimeError("boom")):
        with mock.patch("app.modules.integrations.telegram_bot.TelegramBotClient.send_message", return_value=None):
            reply = client._handle_chat_message("BREAKING: Oil crash", "555")
    assert reply is not None
    assert "something went wrong" not in reply  # chat reply still produced


def test_telegram_chat_message_skips_ingest_for_approval_shorthand():
    from app.modules.integrations.telegram_bot import TelegramBotClient

    client = TelegramBotClient(token="tok:wiring3", chat_id="555")
    with mock.patch.object(TelegramBotClient, "_ingest_manual") as ingest:
        with mock.patch("app.modules.integrations.telegram_bot.TelegramBotClient.send_message", return_value=None):
            client._handle_chat_message("1", "555")
    ingest.assert_not_called()


def test_whatsapp_webhook_ingests_manual_news():
    """Non-1/2 non-command WhatsApp text is news-ingested + answered."""
    from app.routes.whatsapp_ext import _handle_message

    with mock.patch("app.modules.news.whatsapp_manual.ingest_whatsapp_manual") as ingest:
        with mock.patch("app.modules.ai.conversation.process_message", return_value="analyzed"):
            with mock.patch("app.modules.integrations.whatsapp_client.whatsapp_alert_client.send_text"):
                outcome = _handle_message("+15551234567", "BREAKING: Cable spikes")
    assert outcome["reply"] == "analyzed"
    ingest.assert_called_once_with("+15551234567", "BREAKING: Cable spikes")


def test_whatsapp_webhook_ingest_failure_never_breaks_chat():
    from app.routes.whatsapp_ext import _handle_message

    with mock.patch("app.modules.news.whatsapp_manual.ingest_whatsapp_manual", side_effect=RuntimeError("boom")):
        with mock.patch("app.modules.ai.conversation.process_message", return_value="still-answered"):
            with mock.patch("app.modules.integrations.whatsapp_client.whatsapp_alert_client.send_text"):
                outcome = _handle_message("+15551234567", "BREAKING: Cable spikes")
    assert outcome["reply"] == "still-answered"


def test_whatsapp_webhook_skips_ingest_for_approval_shorthand():
    from app.routes.whatsapp_ext import _handle_message

    with mock.patch("app.modules.news.whatsapp_manual.ingest_whatsapp_manual") as ingest:
        with mock.patch("app.modules.integrations.whatsapp_client.whatsapp_alert_client.send_text"):
            outcome = _handle_message("+15551234567", "1")
    ingest.assert_not_called()
    assert outcome["reply"] is not None


def test_email_route_ingests_manual_news():
    """Non-command email text is news-ingested + answered."""
    from app.modules.integrations.email_bot import EmailConversationBot

    bot = EmailConversationBot()
    with mock.patch("app.modules.news.email_manual.ingest_email_manual") as ingest:
        with mock.patch("app.modules.ai.conversation.process_message", return_value="email-analyzed"):
            reply = bot._route_command("BREAKING: Gold all-time high", "alerts@trader.com")
    assert reply == "email-analyzed"
    ingest.assert_called_once_with("alerts@trader.com", "BREAKING: Gold all-time high")


def test_email_route_ingest_failure_never_breaks_chat():
    from app.modules.integrations.email_bot import EmailConversationBot

    bot = EmailConversationBot()
    with mock.patch("app.modules.news.email_manual.ingest_email_manual", side_effect=RuntimeError("boom")):
        with mock.patch("app.modules.ai.conversation.process_message", return_value="still-ok"):
            reply = bot._route_command("BREAKING: Euro dump", "alerts@trader.com")
    assert reply == "still-ok"


def test_email_route_skips_ingest_for_commands():
    from app.modules.integrations.email_bot import EmailConversationBot

    bot = EmailConversationBot()
    with mock.patch("app.modules.news.email_manual.ingest_email_manual") as ingest:
        reply = bot._route_command("/status", "alerts@trader.com")
    ingest.assert_not_called()
    assert reply is not None


def test_email_manual_ingest_persists_and_publishes():
    from app.modules.news.email_manual import SOURCE_TYPE as EMAIL_SOURCE_TYPE
    from app.modules.news.email_manual import ingest_email_manual

    with mock.patch("app.modules.news.email_manual.redis_pubsub.publish") as publish_mock:
        item = ingest_email_manual("alerts@trader.com", "BREAKING: Fed hikes")
    assert item is not None
    assert (item.get("raw") or {}).get("sourceType") == EMAIL_SOURCE_TYPE
    assert publish_mock.called
    assert publish_mock.call_args[0][0] == "ws_news"
    saved = asyncio.run(news_repository.list_items(limit=10))
    assert any(i["source"] == "Email alerts@trader.com" for i in saved)


def test_email_manual_ingest_ignores_empty():
    from app.modules.news.email_manual import ingest_email_manual

    assert ingest_email_manual("alerts@trader.com", "   ") is None


# --------------------------------------------------------------------------- #
# Module 4: Telegram manual-message polling (only the token is needed)
# --------------------------------------------------------------------------- #
def _telegram_message_payload():
    return {
        "ok": True,
        "result": [
            {
                "update_id": 201,
                "message": {
                    "message_id": 1,
                    "chat": {"id": 555, "type": "private"},
                    "date": 1700000100,
                    "text": "Gold alert incoming",
                },
            },
            {
                "update_id": 202,
                "channel_post": {
                    "message_id": 2,
                    "chat": {"id": -100999, "type": "channel", "username": "goldalerts"},
                    "date": 1700000101,
                    "text": "Channel post",
                },
            },
            {
                "update_id": 203,
                "message": {
                    "message_id": 3,
                    "chat": {"id": 666, "type": "group", "title": "Traders"},
                    "date": 1700000102,
                    "text": "group message",
                },
            },
        ],
    }


def test_poll_manual_messages_routes_private_messages():
    _OFFSETS.clear()
    payload = _telegram_message_payload()
    with mock.patch("httpx.Client.get", return_value=_FakeTelegramResponse(payload)):
        routed = poll_manual_messages("tok:manual")
    assert len(routed) == 1
    assert routed[0]["chat_id"] == "555"
    assert routed[0]["text"] == "Gold alert incoming"
    # Offset only advances past the consumed message, leaving the channel post
    # for the per-source channel collector in the same cycle.
    assert _OFFSETS.get("tok:manual") == 202


def test_poll_manual_messages_advances_offset_no_duplicates():
    _OFFSETS.clear()
    payload = _telegram_message_payload()
    collector = poll_manual_messages
    with mock.patch("httpx.Client.get", return_value=_FakeTelegramResponse(payload)):
        first = collector("tok:manual2")
    assert len(first) == 1
    with mock.patch("httpx.Client.get", return_value=_FakeTelegramResponse(payload)):
        second = collector("tok:manual2")
    assert second == []


def test_poll_manual_messages_ignores_channel_posts_and_groups():
    _OFFSETS.clear()
    payload = {"ok": True, "result": [_telegram_message_payload()["result"][1], _telegram_message_payload()["result"][2]]}
    with mock.patch("httpx.Client.get", return_value=_FakeTelegramResponse(payload)):
        routed = poll_manual_messages("tok:manual3")
    assert routed == []
    assert _OFFSETS.get("tok:manual3", 0) == 0


def test_poll_all_collectors_routes_telegram_manual_messages():
    os.environ["TELEGRAM_BOT_TOKEN"] = "tok:route"
    try:
        with mock.patch(
            "app.modules.news.realtime.registry.poll_manual_messages",
            return_value=[
                {"chat_id": "777", "text": "/status"},
                {"chat_id": "777", "text": "BREAKING: Oil prices crash"},
            ],
        ):
            with mock.patch(
                "app.modules.integrations.telegram_bot.telegram_bot.handle_command",
                return_value={"ok": True},
            ) as handle:
                with mock.patch("app.modules.news.realtime.registry.news_repository.list_sources", return_value=[]):
                    result = asyncio.run(poll_all_collectors(limit_per_source=5))
    finally:
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    assert result["telegramMessagesRouted"] == 2
    assert handle.call_count == 2
    texts = [c.args[0] for c in handle.call_args_list]
    assert "/status" in texts
    assert "BREAKING: Oil prices crash" in texts


def test_poll_all_collectors_tolerates_telegram_failures():
    os.environ["TELEGRAM_BOT_TOKEN"] = "tok:fail"
    try:
        with mock.patch(
            "app.modules.news.realtime.registry.poll_manual_messages",
            side_effect=RuntimeError("bot api down"),
        ):
            with mock.patch("app.modules.news.realtime.registry.news_repository.list_sources", return_value=[]):
                result = asyncio.run(poll_all_collectors(limit_per_source=5))
    finally:
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    assert result["telegramMessagesRouted"] == 0


# --------------------------------------------------------------------------- #
# Module 5: Web collector dedupe (unchanged pages are never re-inserted)
# --------------------------------------------------------------------------- #
def test_web_collector_skips_unchanged_page_via_content_hash():
    collector = WebRealtimeCollector({"urls": ["https://example.com/stmt"]})
    item = {"title": "Fed statement", "url": "https://example.com/stmt"}
    item["contentHash"] = _fingerprint(item)
    collector.config["lastContentHash"] = _fingerprint(item)
    assert collector._is_duplicate(item, []) is True


def test_web_collector_skips_duplicate_vs_recent_item():
    collector = WebRealtimeCollector({"urls": ["https://example.com/stmt"]})
    item = {"title": "Fed statement", "url": "https://example.com/stmt"}
    item["contentHash"] = _fingerprint(item)
    recent = [{"title": "Fed statement", "url": "https://example.com/stmt", "contentHash": _fingerprint(item)}]
    assert collector._is_duplicate(item, recent) is True


def test_web_collector_returns_changed_page():
    collector = WebRealtimeCollector({"urls": ["https://example.com/stmt"]})
    item = {"title": "Fed statement UPDATED", "url": "https://example.com/stmt"}
    item["contentHash"] = _fingerprint(item)
    recent = [{"title": "Fed statement", "url": "https://example.com/stmt"}]
    assert collector._is_duplicate(item, recent) is False


# --------------------------------------------------------------------------- #
# Module 6: X/Twitter source creation maps url/handles into config
# --------------------------------------------------------------------------- #
def test_extract_twitter_handle_from_url():
    from app.modules.news.engine import _extract_twitter_handle, build_twitter_handles

    assert _extract_twitter_handle("https://x.com/ForexPeaceArmy_?s=20") == "ForexPeaceArmy_"
    assert _extract_twitter_handle("https://twitter.com/elonmusk") == "elonmusk"
    assert _extract_twitter_handle("@DeItaone") == "DeItaone"
    assert _extract_twitter_handle("markets") == "markets"
    assert _extract_twitter_handle("") == ""

    assert build_twitter_handles(None, "https://x.com/ForexPeaceArmy_?s=20") == ["ForexPeaceArmy_"]
    assert build_twitter_handles(["@DeItaone", "DeItaone"], None) == ["DeItaone"]
    assert build_twitter_handles(["@a", "@b"], "https://x.com/a") == ["a", "b"]
    assert build_twitter_handles([], None) == []


def test_add_manual_source_maps_twitter_url_to_handles():
    from app.foundation.json_store import db
    from app.modules.news.engine import add_manual_source

    sources_col = db.collection("news_sources")
    for s in sources_col.find({"id": "test-tw-url"}) + sources_col.find({"id": "test-tw-handles"}):
        sources_col.remove(s["id"])

    try:
        added = add_manual_source({
            "id": "test-tw-url",
            "name": "X URL",
            "type": "x_twitter",
            "url": "https://x.com/ForexPeaceArmy_?s=20",
            "enabled": True,
        })
        assert added["config"]["handles"] == ["ForexPeaceArmy_"]
        assert "urls" not in added["config"]

        added2 = add_manual_source({
            "id": "test-tw-handles",
            "name": "X Handles",
            "type": "x_twitter",
            "url": "https://x.com/ignored?s=1",
            "config": {"handles": ["@DeItaone", "elonmusk"]},
            "enabled": True,
        })
        assert added2["config"]["handles"] == ["DeItaone", "elonmusk"]
    finally:
        for sid in ("test-tw-url", "test-tw-handles"):
            for s in sources_col.find({"id": sid}):
                sources_col.remove(s["id"])


def test_repository_round_trips_twitter_handles():
    """Repository stores ``config.handles`` unchanged (JSON + PG share the path)."""
    import asyncio

    async def scenario():
        await news_repository.remove_source("test-tw-repo")
        src = await news_repository.add_source({
            "name": "X Repo",
            "type": "x_twitter",
            "config": {"handles": ["ForexPeaceArmy_"]},
            "priority": 1,
            "enabled": True,
        })
        assert src["config"]["handles"] == ["ForexPeaceArmy_"]
        listed = await news_repository.list_sources()
        stored = next(s for s in listed if s["id"] == src["id"])
        assert stored["config"]["handles"] == ["ForexPeaceArmy_"]
        await news_repository.remove_source(src["id"])

    asyncio.run(scenario())


def _remove_test_sources(*source_ids):
    from app.foundation.json_store import db

    sources_col = db.collection("news_sources")
    for source_id in source_ids:
        for s in sources_col.find({"id": source_id}):
            sources_col.remove(s["id"])


def test_web_poll_cycle_first_inserts_second_skips():
    source = {
        "id": "test-web-dedupe",
        "name": "Web Dedupe",
        "type": "web",
        "config": {"urls": ["https://example.com/stmt"]},
        "enabled": True,
    }
    page = {
        "title": "Fed holds rates steady",
        "summary": "Statement text",
        "url": "https://example.com/stmt",
        "category": "macro",
        "impact": 0.5,
    }
    _remove_test_sources("test-web-dedupe", "test-web-dedupe-change")

    async def _cycle_one():
        await news_repository.add_source(source)
        return await poll_all_collectors(limit_per_source=5)

    async def _cycle_two():
        return await poll_all_collectors(limit_per_source=5)

    with mock.patch("app.modules.news.realtime.web.WebRealtimeCollector._fetch_page", return_value=page):
        with mock.patch("app.foundation.redis_pubsub.redis_pubsub.publish"):
            first = asyncio.run(_cycle_one())
    assert first["collected"] == 1
    assert first["persisted"] == 1

    with mock.patch("app.modules.news.realtime.web.WebRealtimeCollector._fetch_page", return_value=page):
        with mock.patch("app.foundation.redis_pubsub.redis_pubsub.publish"):
            second = asyncio.run(_cycle_two())
    assert second["collected"] == 0
    assert second["persisted"] == 0

    async def _cleanup():
        await news_repository.remove_source("test-web-dedupe")

    asyncio.run(_cleanup())


def test_web_poll_cycle_reinserts_when_page_changes():
    source = {
        "id": "test-web-dedupe-change",
        "name": "Web Dedupe Change",
        "type": "web",
        "config": {"urls": ["https://example.com/live"]},
        "enabled": True,
    }
    page_a = {"title": "Live statement v1", "summary": "s", "url": "https://example.com/live", "category": "macro", "impact": 0.5}
    page_b = {"title": "Live statement v2", "summary": "s", "url": "https://example.com/live", "category": "macro", "impact": 0.5}
    _remove_test_sources("test-web-dedupe", "test-web-dedupe-change")

    async def _seed():
        await news_repository.add_source(source)

    async def _cycle():
        return await poll_all_collectors(limit_per_source=5)

    async def _cleanup():
        await news_repository.remove_source("test-web-dedupe-change")

    asyncio.run(_seed())
    try:
        with mock.patch("app.modules.news.realtime.web.WebRealtimeCollector._fetch_page", return_value=page_a):
            with mock.patch("app.foundation.redis_pubsub.redis_pubsub.publish"):
                first = asyncio.run(_cycle())
        assert first["persisted"] == 1
        with mock.patch("app.modules.news.realtime.web.WebRealtimeCollector._fetch_page", return_value=page_b):
            with mock.patch("app.foundation.redis_pubsub.redis_pubsub.publish"):
                second = asyncio.run(_cycle())
        assert second["collected"] == 1
        assert second["persisted"] == 1
    finally:
        asyncio.run(_cleanup())

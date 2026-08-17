"""Unit tests for the additive Reddit realtime sentiment collector.

No real network and no real PRAW package required: the RSS feed parser is
mocked with canned feeds, and the optional PRAW path is exercised by injecting
a fake ``praw`` module into ``sys.modules``. Unconfigured/failure paths must
return ``[]`` (fail-safe contract).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test_reddit")
os.environ["POSTGRES_ENABLED"] = "false"
os.environ["DATABASE_URL"] = ""

from unittest import mock  # noqa: E402

from app.modules.news.realtime.reddit import RedditRealtimeCollector  # noqa: E402
from app.modules.news.realtime.registry import _COLLECTOR_TYPES  # noqa: E402


def _fake_feed(titles):
    return {
        "bozo": False,
        "feed": {"title": "r/Forex"},
        "entries": [
            {"title": t, "summary": "summary", "link": f"https://reddit.example/{i}",
             "published_parsed": None, "updated_parsed": None}
            for i, t in enumerate(titles)
        ],
    }


def test_reddit_rss_mode_normalizes_entries():
    collector = RedditRealtimeCollector({"subreddits": ["Forex"]})
    with mock.patch("feedparser.parse", return_value=_fake_feed(["Gold rally incoming"])):
        items = collector.collect({"limit": 5})
    assert len(items) == 1
    item = items[0]
    assert item["title"] == "Gold rally incoming"
    assert item["source"] == "r/Forex"
    assert item["category"] == "social"
    assert item["collector"] == "reddit"
    assert item["collectorType"] == "reddit"
    assert item["raw"] is True
    assert item["impact"] == 0.3


def test_reddit_rss_mode_drops_empty_titles_and_strips_r_prefix():
    collector = RedditRealtimeCollector({"subreddits": ["/r/economy"]})
    with mock.patch("feedparser.parse", return_value=_fake_feed(["   ", "Real post"])):
        items = collector.collect({})
    assert len(items) == 1
    assert items[0]["title"] == "Real post"
    assert items[0]["source"] == "r/economy"


def test_reddit_rss_mode_returns_empty_on_failure():
    collector = RedditRealtimeCollector({})
    with mock.patch("feedparser.parse", side_effect=RuntimeError("net down")):
        assert collector.collect({}) == []


def test_reddit_rss_mode_returns_empty_on_bozo_without_entries():
    collector = RedditRealtimeCollector({"subreddits": ["Forex"]})
    with mock.patch("feedparser.parse", return_value={"bozo": True, "entries": []}):
        assert collector.collect({}) == []


def test_reddit_uses_rss_when_no_credentials_configured():
    collector = RedditRealtimeCollector({"subreddits": ["Forex"]})
    with mock.patch.dict(os.environ, {}, clear=False):
        with mock.patch("feedparser.parse", return_value=_fake_feed(["No API key post"])):
            items = collector.collect({})
    assert len(items) == 1
    assert items[0]["title"] == "No API key post"


class _FakePost:
    title = "XAUUSD at record high"
    selftext = "Bullish pressure on gold"
    permalink = "/r/Forex/comments/abc/xauusd_record_high/"
    url = "https://www.reddit.com/r/Forex/comments/abc/xauusd_record_high/"
    created_utc = 1700000000.0


def test_reddit_praw_path_with_credentials():
    fake_praw = mock.MagicMock()
    subreddit = fake_praw.Reddit.return_value.subreddit.return_value
    subreddit.display_name = "Forex"
    subreddit.hot.return_value = [_FakePost()]
    with mock.patch.dict(sys.modules, {"praw": fake_praw}):
        with mock.patch.dict(os.environ, {"REDDIT_CLIENT_ID": "cid", "REDDIT_CLIENT_SECRET": "secret"}, clear=False):
            collector = RedditRealtimeCollector({"subreddits": ["Forex"]})
            items = collector.collect({"limit": 5})
    assert len(items) == 1
    item = items[0]
    assert item["title"] == "XAUUSD at record high"
    assert item["source"] == "r/Forex"
    assert item["url"].startswith("https://www.reddit.com/r/Forex/comments/")
    assert item["collectorType"] == "reddit"


def test_reddit_praw_path_falls_back_to_rss_when_praw_missing():
    """PRAW env configured but package absent => RSS fallback, never crash."""
    with mock.patch.dict(sys.modules, {"praw": None}):
        with mock.patch.dict(os.environ, {"REDDIT_CLIENT_ID": "cid", "REDDIT_CLIENT_SECRET": "secret"}, clear=False):
            with mock.patch("feedparser.parse", return_value=_fake_feed(["RSS fallback post"])):
                collector = RedditRealtimeCollector({"subreddits": ["Forex"]})
                items = collector.collect({})
    assert len(items) == 1
    assert items[0]["title"] == "RSS fallback post"


def test_reddit_registered_in_realtime_registry():
    assert "reddit" in _COLLECTOR_TYPES
    collector = _COLLECTOR_TYPES["reddit"]({})
    assert collector.id == "reddit"
    assert collector.collector_type == "reddit"

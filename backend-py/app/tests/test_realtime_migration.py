"""Unit tests for the additive realtime collectors + macro realtime fetcher.

No real network: collectors are fed canned RSS/HTML payloads via mock; the
macro fetcher is exercised against a tiny local HTTP server so the parsing
paths run end-to-end without hitting the public internet.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test_realtime")
os.environ["POSTGRES_ENABLED"] = "false"
os.environ["DATABASE_URL"] = ""

import http.server  # noqa: E402
import threading  # noqa: E402

from unittest import mock  # noqa: E402

from app.modules.news.realtime.rss import RssRealtimeCollector  # noqa: E402
from app.modules.news.realtime.web import WebRealtimeCollector  # noqa: E402
from app.modules.news.realtime.telegram import TelegramRealtimeCollector  # noqa: E402
from app.modules.macro.realtime import fetch_macro_snapshot, fetch_fx_series, _safe_float  # noqa: E402

def test_rss_collector_normalizes_entries():
    fake_feed = {
        "bozo": False,
        "feed": {"title": "GoldWire"},
        "entries": [
            {
                "title": "Gold rallies on Fed cut hopes",
                "summary": "Bullion climbs 1.2%",
                "link": "https://gold.example/rally",
                "published_parsed": None,
                "updated_parsed": None,
            }
        ],
    }
    collector = RssRealtimeCollector({"feedUrls": ["https://example/feed"]})
    with mock.patch("feedparser.parse", return_value=fake_feed):
        items = collector.collect({"limit": 5})
    assert len(items) == 1
    assert items[0]["title"] == "Gold rallies on Fed cut hopes"
    assert items[0]["source"] == "GoldWire"
    assert items[0]["collector"] == "rss"
    assert items[0]["raw"] is True


def test_rss_collector_drops_empty_titles():
    fake_feed = {
        "bozo": False,
        "feed": {"title": "QuietFeed"},
        "entries": [{"title": "   ", "summary": "x", "link": "https://e/x"}],
    }
    collector = RssRealtimeCollector({"feedUrls": ["https://example/feed"]})
    with mock.patch("feedparser.parse", return_value=fake_feed):
        items = collector.collect({})
    assert items == []


def test_web_collector_extracts_title_and_meta():
    html = b"<html><head><title>Gold at Record High</title>"
    html += b"<meta name='description' content='Gold breaches $2400'>"
    html += b"<meta property='og:description' content='Gold breaches $2400'></head><body></body></html>"
    collector = WebRealtimeCollector({"urls": ["https://example/article"]})
    with mock.patch("urllib.request.urlopen", return_value=mock.Mock(read=lambda: html)):
        items = collector.collect({})
    assert len(items) == 1
    assert items[0]["title"] == "Gold at Record High"
    assert items[0]["summary"] == "Gold breaches $2400"
    assert items[0]["category"] == "macro"


def test_telegram_collector_normalizes_joined_html():
    html = ("<html><body><div class='tgme_widget_message_text'>"
            "Gold up after CPI<br/>$2400 high</div></body></html>")
    collector = TelegramRealtimeCollector({"channels": ["@goldalerts"]})
    with mock.patch("urllib.request.urlopen", return_value=mock.Mock(read=lambda: html.encode())):
        items = collector.collect({})
    assert len(items) == 1
    assert "Gold up after CPI" in items[0]["title"]
    assert items[0]["source"] == "@goldalerts"


def test_safe_float_edge_cases():
    assert _safe_float("12.34") == 12.34
    assert _safe_float("n/a") is None
    assert _safe_float(None) is None
    assert _safe_float("") is None


class _MacroHandler(http.server.BaseHTTPRequestHandler):
    """Serves a canned CBOE VIX CSV on /allstocksdaily.csv."""

    def do_GET(self):
        if "allstocksdaily" in self.path:
            body = b"Date,VIX\n08/07/2026,14.23\n08/06/2026,15.01\n"
        elif "yield" in self.path or "xml" in self.path:
            body = b"<data><entry><content><value>US 2 Year,3.94</value>"
            body += b"<value>US 10 Year,4.21</value></content></entry></data>"
        else:
            body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # noqa: A002
        pass


def _start_server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _MacroHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def test_fetch_macro_snapshot_parses_vix_and_treasury():
    srv, base = _start_server()
    try:
        with mock.patch("app.modules.macro.realtime.settings") as m:
            m.VIX_CSV_URL = f"{base}/allstocksdaily.csv"
            m.TREASURY_XML_URL = f"{base}/yield.xml"
            m.DXY_URL = None
            m.GOLD_URL = None
            m.OIL_URL = None
            m.MACRO_FX_BASE_URL = ""
            snap = fetch_macro_snapshot()
        assert snap["vix"] == 14.23
        assert snap["us2y"] == 3.94
        assert snap["us10y"] == 4.21
        assert snap["us2y10y"] is not None
        assert snap["regime"] in ("risk_on", "risk_off", "neutral", "crisis")
        assert snap["gold"] is None  # no FX provider configured -> None, never fabricated
    finally:
        srv.shutdown()


def test_fetch_fx_series_falls_back_to_keyless_providers():
    """Without a configured feed, free keyless providers fill dxy/gold/oil."""
    with mock.patch("app.modules.macro.realtime.settings") as m:
        m.MACRO_FX_BASE_URL = ""
        m.GOLD_API_URL = ""
        m.OIL_QUOTE_URL = ""
        m.FX_RATES_URL = ""
        with mock.patch("app.modules.macro.realtime._get_json") as gj:
            gj.side_effect = [
                {"price": 2340.5},                                   # gold
                {"chart": {"result": [{"meta": {"regularMarketPrice": 78.9}}]}},  # oil
                {"rates": {"EUR": 0.85, "JPY": 150.0, "GBP": 0.75,
                           "CAD": 1.35, "SEK": 10.0, "CHF": 0.90}},  # dxy basket
            ]
            fx = fetch_fx_series()
    assert fx["gold"] == 2340.5
    assert fx["oil"] == 78.9
    assert fx["dxy"] is not None and fx["dxy"] > 0


def test_fetch_fx_series_uses_configured_feed_first():
    """A configured MACRO_FX_BASE_URL overrides the keyless fallback."""
    with mock.patch("app.modules.macro.realtime.settings") as m:
        m.MACRO_FX_BASE_URL = "https://feed.example/macro.json"
        with mock.patch("httpx.Client") as client_cls:
            client = client_cls.return_value.__enter__.return_value
            client.get.return_value.raise_for_status.return_value = None
            client.get.return_value.json.return_value = {"dxy": 104.2, "gold": 2300.0, "oil": 77.0}
            fx = fetch_fx_series()
    assert fx == {"dxy": 104.2, "gold": 2300.0, "oil": 77.0}


def test_fetch_fx_series_never_fabricates_when_all_sources_fail():
    """Every provider down => all fields None (no fabricated values)."""
    with mock.patch("app.modules.macro.realtime.settings") as m:
        m.MACRO_FX_BASE_URL = ""
        with mock.patch("app.modules.macro.realtime._get_json", side_effect=RuntimeError("net down")):
            fx = fetch_fx_series()
    assert fx == {"dxy": None, "gold": None, "oil": None}

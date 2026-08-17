"""Real Telegram channel collector.

Public Telegram channels expose a web preview at ``https://t.me/s/<channel>``.
This collector fetches that page via HTTPS and parses the message blocks
(``tgme_widget_message_text``), producing real headline payloads. Channels are
configured on the source (``config.channels`` as list of usernames or full
``t.me/...`` links). Requires no API token for public channels.
"""
import re
import time
import urllib.request

from ....foundation.logger import logger

BASE_URL = "https://t.me/s/{channel}"
TIMEOUT_SECONDS = 15
_USER_AGENT = "Mozilla/5.0 (compatible; ZZ_QuantOS_AI_BOAT/1.0; +news collector)"


def _normalize_channel(channel):
    ch = str(channel).strip()
    ch = ch.split("?")[0]
    if "t.me/" in ch:
        ch = ch.rsplit("t.me/", 1)[-1]
    ch = ch.lstrip("@")
    return ch


class TelegramRealtimeCollector:
    id = "telegram"
    name = "Telegram Channels (live)"
    collector_type = "telegram"

    def __init__(self, config=None):
        self.config = config or {}
        self.api_id = self.config.get("apiId") or ""
        self.api_hash = self.config.get("apiHash") or ""
        self.session_file = self.config.get("sessionFile") or ""

    def collect(self, params=None):
        channels = self.config.get("channels") or []
        items = []
        for raw in channels:
            ch = _normalize_channel(raw)
            if not ch:
                continue
            for message in self._fetch_channel(ch, (params or {}).get("limit", 10)):
                items.append({
                    "source": f"@{ch}",
                    "title": message["text"][:300],
                    "summary": message["text"][:2000],
                    "url": f"https://t.me/{ch}/{message['message_id']}",
                    "category": "social",
                    "impact": 0.3,
                    "collector": self.id,
                    "collectorType": self.collector_type,
                    "channel": ch,
                    "time": message["time"],
                    "raw": True,
                })
        return [i for i in items if i["title"]]

    def _fetch_channel(self, channel, limit):
        """Fetch the t.me/s preview page and extract the latest messages."""
        try:
            url = BASE_URL.format(channel=channel)
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            resp = urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS)
            try:
                html = resp.read().decode("utf-8", errors="replace")
            finally:
                resp.close()
        except Exception as exc:  # noqa: BLE001 - network failure is non-fatal
            logger.warn(f"Telegram fetch failed for {channel}: {exc}")
            return []
        messages = []
        # Message text blocks: div.tgme_widget_message_text (inside the outer
        # tgme_widget_message block on the real page; standalone in fixtures).
        text_blocks = re.findall(
            r'<div[^>]*class=["\']tgme_widget_message_text["\'][^>]*>(.*?)</div>',
            html,
            re.DOTALL,
        )
        ids = re.findall(r'data-post="[^"]*/(\d+)"', html)
        times = re.findall(r'<time[^>]*datetime="([^"]+)"', html)
        for i, block in enumerate(text_blocks):
            text = re.sub(r"<[^>]+>", "", block).strip()
            text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"')
            if not text:
                continue
            message_id = int(ids[i]) if i < len(ids) else int(time.time() * 1000)
            published_ms = _parse_datetime(times[i]) if i < len(times) else int(time.time() * 1000)
            messages.append({"text": text, "message_id": message_id, "time": published_ms})
            if len(messages) >= limit:
                break
        return messages


def _parse_datetime(iso_str):
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return int(time.time() * 1000)


def register(config=None):
    return TelegramRealtimeCollector(config or {})

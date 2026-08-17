"""News Decay Engine (Batch 03, additive).

Implements time-based relevance decay so stale news can never trigger a trade.

The master prompt mandates: "No stale news" — news older than the configurable
half-life loses effective impact and confidence, and below ``min_relevance`` a
story is treated as decayed (excluded from live-trade context).

Everything here is additive to ``news/engine.py`` (which is left untouched).
"""
import time

from ...foundation.logger import logger

# Default half-life: a story loses half its relevance after this many seconds.
DEFAULT_HALF_LIFE_SECONDS = 1800  # 30 minutes
# Below this relevance the news item is considered decayed.
DEFAULT_MIN_RELEVANCE = 0.10
# A decayed story may not participate in live trade decisions.
DEFAULT_HARD_STALE_SECONDS = 7200  # 2 hours absolute cap


class NewsDecayEngine:
    """Computes decayed relevance for news items based on age."""

    def __init__(self, half_life_seconds=DEFAULT_HALF_LIFE_SECONDS, min_relevance=DEFAULT_MIN_RELEVANCE, hard_stale_seconds=DEFAULT_HARD_STALE_SECONDS):
        self.half_life_seconds = max(1, int(half_life_seconds))
        self.min_relevance = max(0.0, min(1.0, float(min_relevance)))
        self.hard_stale_seconds = max(1, int(hard_stale_seconds))

    def _age_seconds(self, item, now_ms=None):
        now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        ts = item.get("time") or item.get("publishedAt") or item.get("ingestedAt")
        if not ts:
            return 0
        return max(0, now_ms - int(ts)) / 1000.0

    def decay_factor(self, item, now_ms=None):
        """Exponential decay factor in [0,1]; 1.0 = fresh, 0.0 = fully decayed."""
        age = self._age_seconds(item, now_ms)
        return max(0.0, 2.0 ** (-age / float(self.half_life_seconds)))

    def effective_impact(self, item, now_ms=None):
        """Base market impact scaled by decay."""
        base = float(item.get("marketImpact") or item.get("impact") or abs(item.get("sentiment") or 0.0))
        return max(0.0, min(1.0, base * self.decay_factor(item, now_ms)))

    def is_decayed(self, item, now_ms=None):
        """A news item is decayed if stale past hard cap OR relevance below floor."""
        age = self._age_seconds(item, now_ms)
        if age > self.hard_stale_seconds:
            return True
        return self.decay_factor(item, now_ms) < self.min_relevance

    def classify(self, item, now_ms=None):
        """Return a decay assessment object suitable for storage/display."""
        age = self._age_seconds(item, now_ms)
        factor = self.decay_factor(item, now_ms)
        effective = self.effective_impact(item, now_ms)
        decayed = self.is_decayed(item, now_ms)
        return {
            "ageSeconds": int(age),
            "decayFactor": round(factor, 4),
            "effectiveImpact": round(effective, 4),
            "decayed": decayed,
            "halfLifeSeconds": self.half_life_seconds,
            "minRelevance": self.min_relevance,
            "hardStaleSeconds": self.hard_stale_seconds,
        }

    def filter_live(self, items, now_ms=None):
        """Keep only non-decayed items; used before live trade context is built."""
        live = []
        for item in items:
            if not self.is_decayed(item, now_ms):
                item = {**item, "decay": self.classify(item, now_ms)}
                live.append(item)
        return live


news_decay_engine = NewsDecayEngine()

from .engine import get_news  # noqa: E402  (additive import for helpers below)


def get_live_news(params=None):
    """Additive helper: return only live (non-decayed) news for trade decisions."""
    items = get_news(params or {"limit": 100})
    return news_decay_engine.filter_live(items)


def init_news_decay_engine():
    logger.info("News decay engine initialized")
    return news_decay_engine

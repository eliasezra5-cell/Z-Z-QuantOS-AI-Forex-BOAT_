"""Extended candlestick pattern coverage: registry completeness + handcrafted detections."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest  # noqa: E402

from app.modules.technical.candlesticks import PATTERNS, detect_patterns  # noqa: E402

NEWLY_IMPLEMENTED = [
    "morning_doji_star",
    "evening_doji_star",
    "bullish_abandoned_baby",
    "bearish_abandoned_baby",
    "mat_hold",
    "separating_lines_bull",
    "separating_lines_bear",
    "stick_sandwich",
    "upsidedown_gap_two_crows",
    "two_crows",
    "three_stars_south",
    "ladder_bottom",
    "unique_three_river",
    "concealing_baby_swallow",
    "thrusting",
    "in_neck",
    "on_neck",
    "homing_pigeon",
    "descending_hawk",
    "advance_block",
    "deliberation",
    "breakaway",
    "matching_low",
    "matching_high",
]


def _candles(pattern_candles):
    filler = [
        {"open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i, "close": 100.3 + i, "volume": 1000}
        for i in range(6)
    ]
    return filler + pattern_candles


def _detected_ids(candles):
    return [p["id"] for p in detect_patterns(candles)]


# ---- (a) registry size ----
def test_registry_has_at_least_60_entries():
    assert len(PATTERNS) >= 60


def test_new_patterns_registered():
    for pid in NEWLY_IMPLEMENTED:
        assert pid in PATTERNS


# ---- (b) every registered pattern has a detection branch ----
def test_every_registered_pattern_is_implemented():
    import inspect

    from app.modules.technical.candlesticks import detect_patterns as fn

    source = inspect.getsource(fn)
    for pid in PATTERNS:
        assert '"' + pid + '"' in source, "no detection branch for registered pattern %r" % pid


def test_detected_objects_carry_index_and_direction():
    hammer = {"open": 99.8, "close": 100, "high": 100.1, "low": 98.9, "volume": 1000}
    out = detect_patterns(_candles([hammer]))
    assert out
    for p in out:
        assert p["index"] == 6
        assert p["direction"] == PATTERNS[p["id"]]["type"]
        assert p["strength"] is not None
        assert p["reliability"] is not None


# ---- (c) handcrafted detections for newly implemented patterns ----
HANDCRAFTED = {
    "morning_doji_star": (
        [
            {"open": 105, "high": 105.5, "low": 99.5, "close": 100},
            {"open": 99.98, "high": 100.1, "low": 99.7, "close": 99.99},
            {"open": 99.5, "close": 102, "high": 102.5, "low": 99.5},
        ],
        "bullish",
    ),
    "evening_doji_star": (
        [
            {"open": 100, "high": 105.5, "low": 99.5, "close": 105},
            {"open": 105.02, "close": 105.01, "high": 105.3, "low": 104.8},
            {"open": 105.5, "close": 103, "high": 106, "low": 102.5},
        ],
        "bearish",
    ),
    "bullish_abandoned_baby": (
        [
            {"open": 105, "high": 105.5, "low": 98, "close": 100},
            {"open": 97.55, "close": 97.5, "high": 97.8, "low": 97.2},
            {"open": 98.2, "close": 104, "high": 104.5, "low": 98.1},
        ],
        "bullish",
    ),
    "bearish_abandoned_baby": (
        [
            {"open": 100, "high": 105.5, "low": 99.5, "close": 105},
            {"open": 106.2, "close": 106.23, "high": 106.5, "low": 106.1},
            {"open": 105.8, "close": 101, "high": 105.9, "low": 100.5},
        ],
        "bearish",
    ),
    "mat_hold": (
        [
            {"open": 100, "close": 105, "high": 105.5, "low": 99.5},
            {"open": 105.5, "close": 105.2, "high": 105.8, "low": 105.0},
            {"open": 105.4, "close": 105.1, "high": 105.7, "low": 105.0},
            {"open": 105.2, "close": 105.0, "high": 105.5, "low": 105.0},
            {"open": 105.6, "close": 106.5, "high": 106.8, "low": 105.4},
        ],
        "bullish",
    ),
    "separating_lines_bull": (
        [
            {"open": 102, "close": 100, "high": 102.5, "low": 99.5},
            {"open": 102, "close": 104, "high": 104.5, "low": 101.5},
        ],
        "bullish",
    ),
    "separating_lines_bear": (
        [
            {"open": 102, "close": 104, "high": 104.5, "low": 101.5},
            {"open": 102, "close": 100, "high": 102.5, "low": 99.5},
        ],
        "bearish",
    ),
    "stick_sandwich": (
        [
            {"open": 104, "close": 100, "high": 104.5, "low": 99.5},
            {"open": 100.5, "close": 102, "high": 102.5, "low": 100},
            {"open": 101, "close": 100, "high": 101.5, "low": 99.5},
        ],
        "bullish",
    ),
    "upsidedown_gap_two_crows": (
        [
            {"open": 100, "close": 102, "high": 102.5, "low": 99.5},
            {"open": 104, "close": 103, "high": 104.5, "low": 102.8},
            {"open": 103.2, "close": 102.8, "high": 103.6, "low": 102.5},
        ],
        "bearish",
    ),
    "two_crows": (
        [
            {"open": 100, "close": 105, "high": 105.5, "low": 99.5},
            {"open": 107, "close": 101, "high": 107.5, "low": 100.5},
            {"open": 103, "close": 100.5, "high": 103.5, "low": 100},
        ],
        "bearish",
    ),
    "three_stars_south": (
        [
            {"open": 101.8, "close": 100.4, "high": 102, "low": 99.8},
            {"open": 100.6, "close": 99.8, "high": 100.9, "low": 98.8},
            {"open": 99.6, "close": 98.8, "high": 99.9, "low": 98.2},
        ],
        "bullish",
    ),
    "ladder_bottom": (
        [
            {"open": 104, "close": 102, "high": 104.5, "low": 101.5},
            {"open": 103, "close": 101, "high": 103.5, "low": 100.5},
            {"open": 102, "close": 100, "high": 102.5, "low": 99.5},
            {"open": 101, "close": 100.5, "high": 103, "low": 98.5},
            {"open": 100.8, "close": 104, "high": 104.5, "low": 100.5},
        ],
        "bullish",
    ),
    "unique_three_river": (
        [
            {"open": 104, "close": 99.5, "high": 105, "low": 99},
            {"open": 102, "close": 100, "high": 102.5, "low": 98},
            {"open": 100.4, "close": 100.6, "high": 101, "low": 100},
        ],
        "bullish",
    ),
    "concealing_baby_swallow": (
        [
            {"open": 106, "close": 102, "high": 106.5, "low": 101.5},
            {"open": 105, "close": 101, "high": 105.5, "low": 100.5},
            {"open": 104, "close": 100, "high": 104.5, "low": 99.5},
            {"open": 100.5, "close": 105, "high": 105.5, "low": 100},
        ],
        "bullish",
    ),
    "thrusting": (
        [
            {"open": 105, "close": 100, "high": 105.5, "low": 99.5},
            {"open": 99, "close": 103, "high": 103.5, "low": 98.8},
        ],
        "bullish",
    ),
    "in_neck": (
        [
            {"open": 105, "close": 100, "high": 105.5, "low": 99.5},
            {"open": 99.8, "close": 100, "high": 100.5, "low": 99.5},
        ],
        "bearish",
    ),
    "on_neck": (
        [
            {"open": 105, "close": 100, "high": 105.5, "low": 99.5},
            {"open": 99.3, "close": 99.5, "high": 99.9, "low": 99.2},
        ],
        "bearish",
    ),
    "homing_pigeon": (
        [
            {"open": 105, "close": 100, "high": 105.5, "low": 99.5},
            {"open": 102, "close": 101, "high": 102.5, "low": 100.5},
        ],
        "bullish",
    ),
    "descending_hawk": (
        [
            {"open": 102, "close": 106, "high": 106.5, "low": 101.5},
            {"open": 104, "close": 105, "high": 105.5, "low": 103.5},
            {"open": 104.5, "close": 104.8, "high": 105.2, "low": 104.2},
        ],
        "bearish",
    ),
    "advance_block": (
        [
            {"open": 102, "close": 106, "high": 106.5, "low": 101.5},
            {"open": 104, "close": 105.5, "high": 107, "low": 103.5},
            {"open": 105, "close": 105.2, "high": 108, "low": 104.8},
        ],
        "bearish",
    ),
    "deliberation": (
        [
            {"open": 100, "close": 105, "high": 105.5, "low": 99.5},
            {"open": 104, "close": 108, "high": 108.5, "low": 103.5},
            {"open": 108.3, "close": 108.4, "high": 109, "low": 108.2},
        ],
        "bearish",
    ),
    "breakaway": (
        [
            {"open": 106, "close": 100, "high": 106.5, "low": 99.5},
            {"open": 99, "close": 98.5, "high": 99, "low": 98},
            {"open": 98.5, "close": 98, "high": 98.7, "low": 97.5},
            {"open": 98, "close": 97.5, "high": 98.5, "low": 97},
            {"open": 99.5, "close": 107, "high": 107.5, "low": 99.2},
        ],
        "neutral",
    ),
    "matching_low": (
        [
            {"open": 105, "close": 100, "high": 105.5, "low": 99.5},
            {"open": 102, "close": 99.5, "high": 102.5, "low": 99.5},
        ],
        "bullish",
    ),
    "matching_high": (
        [
            {"open": 100, "close": 105, "high": 105.5, "low": 99.5},
            {"open": 103, "close": 105.5, "high": 105.5, "low": 102.5},
        ],
        "bearish",
    ),
}


@pytest.mark.parametrize("pid", sorted(HANDCRAFTED))
def test_handcrafted_detection(pid):
    pattern_candles, expected_direction = HANDCRAFTED[pid]
    candles = _candles(pattern_candles)
    detected = [p for p in detect_patterns(candles) if p["id"] == pid]
    assert detected, "pattern %r not detected" % pid
    assert detected[0]["direction"] == expected_direction


def test_at_least_10_new_patterns_detect():
    detected = 0
    for pid, (pattern_candles, expected_direction) in HANDCRAFTED.items():
        if pid in _detected_ids(_candles(pattern_candles)):
            detected += 1
    assert detected >= 10

import time
from types import SimpleNamespace

from src.jobs import detect_structure, parse_feed_entries


def test_detect_structure_higher_high():
    highs = [10, 11, 12, 9, 13]
    lows = [5, 6, 5, 4, 7]
    assert detect_structure(highs, lows) == "HH"


def test_detect_structure_lower_low():
    highs = [10, 11, 12, 9, 10]
    lows = [5, 6, 5, 4, 3]
    assert detect_structure(highs, lows) == "LL"


def test_detect_structure_range():
    highs = [10, 11, 12, 9, 11]
    lows = [5, 6, 5, 4, 5]
    assert detect_structure(highs, lows) == "range"


def test_parse_feed_entries_skips_missing_link_and_fills_published_at():
    published = time.strptime("2026-11-12", "%Y-%m-%d")
    fake_feed = SimpleNamespace(
        entries=[
            {"title": "A", "link": "https://example.com/a", "summary": "sum a", "published_parsed": published},
            {"title": "No link", "link": "", "summary": "sum b"},
        ]
    )
    items = parse_feed_entries(fake_feed, "TestSource")
    assert len(items) == 1
    assert items[0]["source"] == "TestSource"
    assert items[0]["link"] == "https://example.com/a"
    assert items[0]["published_at"].startswith("2026-11-12")

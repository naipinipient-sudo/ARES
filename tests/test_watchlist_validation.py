import datetime as dt

from src.binance_client import classify_tier, is_listing_old_enough, parse_ticker_stats
from src.telegram_bot import find_market_symbol


def test_classify_tier_thresholds():
    assert classify_tier(300_000_000) == "inti"
    assert classify_tier(200_000_000) == "inti"
    assert classify_tier(100_000_000) == "alt"
    assert classify_tier(50_000_000) == "alt"
    assert classify_tier(25_000_000) == "meme"
    assert classify_tier(1_000_000) is None


def test_is_listing_old_enough():
    now = dt.datetime(2026, 11, 12, tzinfo=dt.timezone.utc)
    old = int((now - dt.timedelta(days=40)).timestamp() * 1000)
    recent = int((now - dt.timedelta(days=5)).timestamp() * 1000)
    assert is_listing_old_enough(old, now) is True
    assert is_listing_old_enough(recent, now) is False
    assert is_listing_old_enough(None, now) is False


def test_parse_ticker_stats():
    raw = {"symbol": "BTC/USDT:USDT", "quoteVolume": "1234.5"}
    assert parse_ticker_stats(raw) == {"symbol": "BTC/USDT:USDT", "volume_24h_usd": 1234.5}


def test_find_market_symbol():
    markets = {
        "WLD/USDT:USDT": {"base": "WLD", "quote": "USDT", "swap": True, "linear": True},
        "WLD/USDC:USDC": {"base": "WLD", "quote": "USDC", "swap": True, "linear": True},
    }
    assert find_market_symbol(markets, "wld") == "WLD/USDT:USDT"
    assert find_market_symbol(markets, "DOGE") is None

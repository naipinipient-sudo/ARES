"""Read-only Binance USDS-M futures access via ccxt, plus the pure
parsing/classification helpers used by job0 (universe selection) and the
/watch validation path. Imported by src/jobs.py and src/telegram_bot.py."""
from __future__ import annotations

import datetime as dt
import time
from functools import lru_cache, wraps
from typing import Any, Callable

import ccxt

from src.config import Config

# PRD "Seleksi otomatis harian (job 0)" thresholds, in 24h USD volume.
TIER_VOLUME_THRESHOLDS = {"inti": 200_000_000, "alt": 50_000_000, "meme": 20_000_000}
MIN_LISTING_DAYS = 30


def retry(times: int = 3, base_delay: float = 1.0) -> Callable:
    """Exponential backoff for flaky/rate-limited Binance calls."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(times):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:  # ccxt raises its own exception tree
                    last_exc = exc
                    if attempt < times - 1:
                        time.sleep(base_delay * (2**attempt))
            raise last_exc

        return wrapper

    return decorator


@lru_cache(maxsize=1)
def get_exchange(cfg: Config) -> ccxt.binanceusdm:
    exchange = ccxt.binanceusdm(
        {
            "apiKey": cfg.binance_api_key,
            "secret": cfg.binance_api_secret,
            "enableRateLimit": True,
        }
    )
    exchange.load_markets()
    return exchange


def classify_tier(volume_24h_usd: float) -> str | None:
    """Pure function: returns the tier a pair qualifies for, or None if it
    is below even the meme threshold."""
    if volume_24h_usd >= TIER_VOLUME_THRESHOLDS["inti"]:
        return "inti"
    if volume_24h_usd >= TIER_VOLUME_THRESHOLDS["alt"]:
        return "alt"
    if volume_24h_usd >= TIER_VOLUME_THRESHOLDS["meme"]:
        return "meme"
    return None


def is_listing_old_enough(onboard_date_ms: int | None, now: dt.datetime | None = None) -> bool:
    """Pure function: True if a market has been listed for >= MIN_LISTING_DAYS."""
    if not onboard_date_ms:
        return False
    now = now or dt.datetime.now(dt.timezone.utc)
    listed_at = dt.datetime.fromtimestamp(onboard_date_ms / 1000, tz=dt.timezone.utc)
    return (now - listed_at).days >= MIN_LISTING_DAYS


def parse_ticker_stats(raw: dict[str, Any]) -> dict[str, Any]:
    """Pure function: normalizes one ccxt fetch_tickers() entry into the
    fields job0 needs. `raw` is a single value from exchange.fetch_tickers()."""
    return {
        "symbol": raw["symbol"],
        "volume_24h_usd": float(raw.get("quoteVolume") or 0.0),
    }


@retry()
def fetch_usdm_tickers(exchange: ccxt.binanceusdm) -> dict[str, dict[str, Any]]:
    raw = exchange.fetch_tickers()
    return {sym: parse_ticker_stats(t) for sym, t in raw.items()}


def get_onboard_date_ms(exchange: ccxt.binanceusdm, symbol: str) -> int | None:
    market = exchange.markets.get(symbol)
    if not market:
        return None
    onboard = (market.get("info") or {}).get("onboardDate")
    return int(onboard) if onboard else None


def symbol_exists(exchange: ccxt.binanceusdm, symbol: str) -> bool:
    return symbol in exchange.markets


@retry()
def fetch_ohlcv_closed(exchange: ccxt.binanceusdm, symbol: str, timeframe: str, limit: int = 210) -> list[list[float]]:
    """Fetches candles and drops the still-forming last one so indicators
    are only ever computed on closed candles."""
    candles = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit + 1)
    return candles[:-1]


@retry()
def fetch_derivatives_pulse(exchange: ccxt.binanceusdm, symbol: str) -> dict[str, Any]:
    """Funding + OI + long/short ratios for one symbol (PRD job 2)."""
    market_id = exchange.market(symbol)["id"]
    funding = exchange.fetch_funding_rate(symbol)
    oi = exchange.fetch_open_interest(symbol)
    ls_account = exchange.fapiDataGetGlobalLongShortAccountRatio({"symbol": market_id, "period": "15m", "limit": 1})
    ls_taker = exchange.fapiDataGetTakerlongshortRatio({"symbol": market_id, "period": "15m", "limit": 1})
    return {
        "funding_rate": funding.get("fundingRate"),
        "open_interest": oi.get("openInterestAmount") or oi.get("openInterestValue"),
        "long_short_account_ratio": float(ls_account[-1]["longShortRatio"]) if ls_account else None,
        "taker_long_short_ratio": float(ls_taker[-1]["buySellRatio"]) if ls_taker else None,
    }


@retry()
def fetch_account_snapshot(exchange: ccxt.binanceusdm) -> dict[str, Any]:
    balance = exchange.fetch_balance()
    positions = [p for p in exchange.fetch_positions() if float(p.get("contracts") or 0) != 0]
    usdt = balance.get("USDT", {})
    return {
        "total_balance": usdt.get("total"),
        "available_balance": usdt.get("free"),
        "used_margin": usdt.get("used"),
        "unrealized_pnl": sum(float(p.get("unrealizedPnl") or 0) for p in positions),
        "positions": [
            {
                "symbol": p["symbol"],
                "side": p.get("side"),
                "contracts": p.get("contracts"),
                "entryPrice": p.get("entryPrice"),
                "unrealizedPnl": p.get("unrealizedPnl"),
                "liquidationPrice": p.get("liquidationPrice"),
            }
            for p in positions
        ],
    }

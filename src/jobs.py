"""All Phase 1 data jobs (PRD jobs 0,1,2,5,7,10,11), the daily brief composer,
and the health check. One module because every job shares the same
fetch -> upsert -> record_job_run shape; splitting each into its own file
would just scatter that shape across nine near-identical files.
Scheduled from src/main.py."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import feedparser
import pandas as pd
import requests

from src import binance_client as bx
from src import db
from src.config import Config

logger = logging.getLogger(__name__)

NEWS_FEEDS = {
    "BBC World": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "BBC Business": "http://feeds.bbci.co.uk/news/business/rss.xml",
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "The Fed": "https://www.federalreserve.gov/feeds/press_all.xml",
}

FUNDING_EXTREME_ABS = 0.001  # 0.1% per 8h, PRD "funding ekstrem"

# Expected seconds between successful runs, per PRD job table. Health check
# flags a job stale at 2x this (PRD: "Data inti lebih tua dari 2x interval").
JOB_INTERVALS_SECONDS = {
    "job0_universe": 86_400,
    "job1_market_snapshot": 3_600,
    "job2_derivatives_pulse": 900,
    "job5_news": 900,
    "job7_macro": 86_400,
    "job10_events": 86_400,
    "job11_account": 60,
    "job12_signal_outcomes": 3_600,
}


def _run(client, job_name: str, func, *args, **kwargs):
    """Wraps a job body so every job records success/failure the same way."""
    try:
        result = func(*args, **kwargs)
        db.record_job_run(client, job_name)
        return result
    except Exception as exc:
        logger.exception("%s failed", job_name)
        db.record_job_run(client, job_name, error=str(exc))
        raise


# --- Job 0: universe selection ---------------------------------------------------


def job0_select_universe(cfg: Config, client) -> list[dict[str, Any]]:
    return _run(client, "job0_universe", _job0_select_universe, cfg, client)


def _job0_select_universe(cfg: Config, client) -> list[dict[str, Any]]:
    exchange = bx.get_exchange(cfg)
    tickers = bx.fetch_usdm_tickers(exchange)
    watchlist_symbols = {row["symbol"] for row in db.get_watchlist(client)}
    protected = db.get_open_position_symbols(client)

    proposals = []
    for symbol, stats in tickers.items():
        if symbol in watchlist_symbols:
            continue
        tier = bx.classify_tier(stats["volume_24h_usd"])
        if tier is None:
            continue
        onboard = bx.get_onboard_date_ms(exchange, symbol)
        if not bx.is_listing_old_enough(onboard):
            continue
        proposals.append(
            {
                "symbol": symbol,
                "suggested_tier": tier,
                "volume_24h_usd": stats["volume_24h_usd"],
            }
        )
    db.upsert_rows(client, "universe_proposals", proposals, on_conflict="symbol")

    # Drop symbols that have been below threshold for the last 3 checks,
    # unless a position is still open in them.
    stale = [
        row["symbol"]
        for row in db.get_watchlist(client)
        if row["symbol"] not in tickers or bx.classify_tier(tickers[row["symbol"]]["volume_24h_usd"]) is None
    ]
    for symbol in stale:
        if symbol not in protected:
            db.remove_watchlist_entry(client, symbol)
            db.log_audit(client, "job0", "auto_unwatch_low_volume", symbol)

    return proposals


# --- Job 1: market snapshot (1H/4H EMA/RSI/ATR/structure) -------------------------


def detect_structure(highs: list[float], lows: list[float]) -> str:
    """Pure function: labels the last closed candle as HH (higher high),
    LL (lower low), or 'range' against the preceding window."""
    if len(highs) < 2 or len(lows) < 2:
        return "range"
    if highs[-1] > max(highs[:-1]):
        return "HH"
    if lows[-1] < min(lows[:-1]):
        return "LL"
    return "range"


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / length, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / length, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.ewm(alpha=1 / length, adjust=False).mean()


def compute_indicators(candles: list[list[float]]) -> dict[str, Any] | None:
    """Pure function: candles is ccxt OHLCV [[ts, o, h, l, c, v], ...], already
    closed-only. Returns the latest closed candle's values plus indicators."""
    if len(candles) < 210:
        return None
    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
    ema50 = _ema(df["close"], 50)
    ema200 = _ema(df["close"], 200)
    rsi = _rsi(df["close"], 14)
    atr = _atr(df["high"], df["low"], df["close"], 14)
    last = df.iloc[-1]
    return {
        "ts": dt.datetime.fromtimestamp(last["ts"] / 1000, tz=dt.timezone.utc).isoformat(),
        "open": last["open"],
        "high": last["high"],
        "low": last["low"],
        "close": last["close"],
        "volume": last["volume"],
        "ema50": float(ema50.iloc[-1]),
        "ema200": float(ema200.iloc[-1]),
        "rsi": float(rsi.iloc[-1]),
        "atr": float(atr.iloc[-1]),
        "structure": detect_structure(df["high"].tolist()[-20:], df["low"].tolist()[-20:]),
    }


def job1_market_snapshot(cfg: Config, client) -> None:
    _run(client, "job1_market_snapshot", _job1_market_snapshot, cfg, client)


def _job1_market_snapshot(cfg: Config, client) -> None:
    exchange = bx.get_exchange(cfg)
    rows = []
    for entry in db.get_watchlist(client):
        symbol = entry["symbol"]
        for timeframe in ("1h", "4h"):
            candles = bx.fetch_ohlcv_closed(exchange, symbol, timeframe)
            indicators = compute_indicators(candles)
            if indicators:
                rows.append({"symbol": symbol, "timeframe": timeframe, **indicators})
    db.upsert_rows(client, "market_snapshots", rows, on_conflict="symbol,timeframe,ts")


# --- Job 2: derivatives pulse ------------------------------------------------------


def job2_derivatives_pulse(cfg: Config, client) -> None:
    _run(client, "job2_derivatives_pulse", _job2_derivatives_pulse, cfg, client)


def _job2_derivatives_pulse(cfg: Config, client) -> None:
    exchange = bx.get_exchange(cfg)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = []
    for entry in db.get_watchlist(client):
        symbol = entry["symbol"]
        pulse = bx.fetch_derivatives_pulse(exchange, symbol)
        funding_rate = pulse.get("funding_rate") or 0.0
        rows.append(
            {
                "symbol": symbol,
                "ts": now,
                "funding_extreme": abs(funding_rate) >= FUNDING_EXTREME_ABS,
                **pulse,
            }
        )
    db.upsert_rows(client, "derivatives_pulse", rows, on_conflict="symbol,ts")


# --- Job 5: news scanner ------------------------------------------------------------


def parse_feed_entries(parsed_feed, source_name: str) -> list[dict[str, Any]]:
    """Pure function: parsed_feed is a feedparser.parse() result (or anything
    with the same .entries shape), easy to fake in tests without network."""
    items = []
    for entry in parsed_feed.entries:
        published = entry.get("published_parsed")
        items.append(
            {
                "source": source_name,
                "title": entry.get("title", "").strip(),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", "")[:500],
                "published_at": dt.datetime(*published[:6], tzinfo=dt.timezone.utc).isoformat() if published else None,
            }
        )
    return [item for item in items if item["link"]]


def job5_news_scanner(cfg: Config, client) -> None:
    _run(client, "job5_news", _job5_news_scanner, cfg, client)


def _job5_news_scanner(cfg: Config, client) -> None:
    rows = []
    for source_name, url in NEWS_FEEDS.items():
        try:
            parsed = feedparser.parse(url)
            rows.extend(parse_feed_entries(parsed, source_name))
        except Exception:
            logger.exception("news feed failed: %s", source_name)
    # LLM labeling (asset/direction/surprise) is intentionally not wired up
    # yet: PRD leaves "model LLM mana yang dipakai" as an open question, and
    # news still gets stored (label_* stays null) so nothing is lost.
    db.upsert_rows(client, "news_items", rows, on_conflict="link")


# --- Job 7: macro & sentiment --------------------------------------------------------


def _fetch_fred_latest(cfg: Config, series_id: str) -> float | None:
    if not cfg.fred_api_key:
        return None
    resp = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": cfg.fred_api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1,
        },
        timeout=10,
    )
    resp.raise_for_status()
    obs = resp.json().get("observations") or []
    value = obs[0]["value"] if obs else None
    return float(value) if value not in (None, ".") else None


def _fetch_fear_greed() -> int | None:
    resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data") or []
    return int(data[0]["value"]) if data else None


def _fetch_stablecoin_supply_usd() -> float | None:
    resp = requests.get("https://stablecoins.llama.fi/stablecoins?includePrices=true", timeout=10)
    resp.raise_for_status()
    assets = resp.json().get("peggedAssets") or []
    return sum(float(a.get("circulating", {}).get("peggedUSD") or 0) for a in assets)


def job7_macro_sentiment(cfg: Config, client) -> None:
    _run(client, "job7_macro", _job7_macro_sentiment, cfg, client)


def _job7_macro_sentiment(cfg: Config, client) -> None:
    row = {"dgs10": None, "dtwexbgs": None, "fear_greed": None, "stablecoin_supply_usd": None}
    for key, fetcher in (
        ("dgs10", lambda: _fetch_fred_latest(cfg, "DGS10")),
        ("dtwexbgs", lambda: _fetch_fred_latest(cfg, "DTWEXBGS")),
        ("fear_greed", _fetch_fear_greed),
        ("stablecoin_supply_usd", _fetch_stablecoin_supply_usd),
    ):
        try:
            row[key] = fetcher()
        except Exception:
            logger.exception("macro source failed: %s", key)
    client.table("macro_snapshots").insert(row).execute()


# --- Job 10: event calendar (manual table, read-only here) --------------------------


def job10_check_events(client, within_hours: int = 24) -> list[dict[str, Any]]:
    return _run(client, "job10_events", _job10_check_events, client, within_hours)


def _job10_check_events(client, within_hours: int) -> list[dict[str, Any]]:
    now = dt.datetime.now(dt.timezone.utc)
    horizon = (now + dt.timedelta(hours=within_hours)).isoformat()
    res = (
        client.table("events_calendar")
        .select("*")
        .gte("event_time", now.isoformat())
        .lte("event_time", horizon)
        .order("event_time")
        .execute()
    )
    events = res.data
    for event in events:
        event_time = dt.datetime.fromisoformat(event["event_time"])
        event["within_1h"] = (event_time - now) <= dt.timedelta(hours=1)
    return events


# --- Job 11: account snapshot --------------------------------------------------------


def job11_account_snapshot(cfg: Config, client) -> dict[str, Any]:
    return _run(client, "job11_account", _job11_account_snapshot, cfg, client)


def _job11_account_snapshot(cfg: Config, client) -> dict[str, Any]:
    exchange = bx.get_exchange(cfg)
    snapshot = bx.fetch_account_snapshot(exchange)
    client.table("account_snapshots").insert(snapshot).execute()
    return snapshot


# --- Job 12: rapor sinyal (+1h/+4h/+24h price tracking) ------------------------------


def _fetch_last_price(exchange, symbol: str) -> float:
    return exchange.fetch_ticker(symbol)["last"]


def job12_track_signal_outcomes(cfg: Config, client) -> None:
    _run(client, "job12_signal_outcomes", _job12_track_signal_outcomes, cfg, client)


def _job12_track_signal_outcomes(cfg: Config, client) -> None:
    exchange = bx.get_exchange(cfg)
    now = dt.datetime.now(dt.timezone.utc)
    res = client.table("signals").select("*").is_("price_24h", "null").order("created_at").limit(200).execute()
    for sig in res.data:
        created_at = dt.datetime.fromisoformat(sig["created_at"])
        age = now - created_at
        updates: dict[str, Any] = {}
        if sig["price_1h"] is None and age >= dt.timedelta(hours=1):
            updates["price_1h"] = _fetch_last_price(exchange, sig["symbol"])
        if sig["price_4h"] is None and age >= dt.timedelta(hours=4):
            updates["price_4h"] = _fetch_last_price(exchange, sig["symbol"])
        if sig["price_24h"] is None and age >= dt.timedelta(hours=24):
            updates["price_24h"] = _fetch_last_price(exchange, sig["symbol"])
        if updates:
            client.table("signals").update(updates).eq("id", sig["id"]).execute()


# --- Health check --------------------------------------------------------------------


def run_health_check(client) -> list[str]:
    """Returns job names whose last success is older than 2x their expected
    interval (or that have never run), per PRD 'nol saran dari data basi'."""
    runs = db.get_job_runs(client)
    now = dt.datetime.now(dt.timezone.utc)
    stale = []
    for job_name, interval_s in JOB_INTERVALS_SECONDS.items():
        last_success_at = (runs.get(job_name) or {}).get("last_success_at")
        if not last_success_at:
            stale.append(job_name)
            continue
        age = (now - dt.datetime.fromisoformat(last_success_at)).total_seconds()
        if age > 2 * interval_s:
            stale.append(job_name)
    return stale


def ping_heartbeat(cfg: Config) -> None:
    """Dead man's switch: Healthchecks.io only alerts when pings STOP, so
    this just needs to fire on a schedule while the process is alive."""
    if not cfg.healthchecks_ping_url:
        return
    try:
        requests.get(cfg.healthchecks_ping_url, timeout=10)
    except Exception:
        logger.exception("healthcheck ping failed")


# --- Daily brief ----------------------------------------------------------------------


def _regime_label(ema200: float | None, close: float | None) -> str:
    if ema200 is None or close is None:
        return "?"
    return "bullish" if close > ema200 else "bearish"


def compose_daily_brief(cfg: Config, client) -> str:
    watchlist = db.get_watchlist(client)
    lines = [f"Daily Brief — {dt.datetime.now(dt.timezone.utc).date().isoformat()} (UTC)", ""]

    lines.append("Rezim (4H, harga vs EMA200):")
    snap_res = client.table("market_snapshots").select("*").eq("timeframe", "4h").order("ts", desc=True).execute()
    seen = set()
    for row in snap_res.data:
        if row["symbol"] in seen:
            continue
        seen.add(row["symbol"])
        lines.append(f"  {row['symbol']}: {_regime_label(row.get('ema200'), row.get('close'))}")

    deriv_res = client.table("derivatives_pulse").select("*").eq("funding_extreme", True).order("ts", desc=True).limit(5).execute()
    if deriv_res.data:
        lines.append("")
        lines.append("Funding ekstrem:")
        for row in deriv_res.data:
            lines.append(f"  {row['symbol']}: funding {row['funding_rate']}")

    macro_res = client.table("macro_snapshots").select("*").order("ts", desc=True).limit(1).execute()
    if macro_res.data:
        m = macro_res.data[0]
        lines.append("")
        lines.append(f"Makro: Fear&Greed {m.get('fear_greed')}, DGS10 {m.get('dgs10')}, stablecoin supply {m.get('stablecoin_supply_usd')}")

    news_res = client.table("news_items").select("title,source").order("fetched_at", desc=True).limit(5).execute()
    if news_res.data:
        lines.append("")
        lines.append("Berita terbaru:")
        for item in news_res.data:
            lines.append(f"  [{item['source']}] {item['title']}")

    events = job10_check_events(client)
    lines.append("")
    if events:
        lines.append("Event hari ini:")
        for e in events:
            flag = " (H-1 jam!)" if e.get("within_1h") else ""
            lines.append(f"  {e['event_time']} — {e['name']}{flag}")
    else:
        lines.append("Tidak ada event makro dalam 24 jam ke depan.")

    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).isoformat()
    signals_res = client.table("signals").select("*").gte("created_at", since).order("created_at", desc=True).execute()
    lines.append("")
    if signals_res.data:
        lines.append("Sinyal 24 jam terakhir:")
        for sig in signals_res.data:
            hasil = f", harga 24j: {sig['price_24h']:.6g}" if sig.get("price_24h") else ""
            lines.append(f"  {sig['symbol']} {sig['direction']} skor {sig['score']}/3{hasil}")
    else:
        lines.append("Tidak ada sinyal dalam 24 jam terakhir.")

    content = "\n".join(lines)
    client.table("daily_briefs").upsert(
        {"brief_date": dt.date.today().isoformat(), "content": content}, on_conflict="brief_date"
    ).execute()
    return content

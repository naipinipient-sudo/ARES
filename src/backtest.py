"""Fase 3: replays the mesin saran rules (src/signal_engine.py) over
historical Binance klines and reports expectancy per PRD 'Backtest'.

ponytail: skips the `backtesting.py` dependency listed in the PRD tech
stack. That library vectorizes a single-timeframe strategy; our rules need
two aligned timeframes (4H regime + 1H trigger) and path-dependent TP1/TP2/
SL resolution, which doesn't fit its Strategy model without fighting it.
A plain loop over precomputed indicator series is less code and easier to
verify. Swap in backtesting.py if a future single-timeframe strategy wants
its vectorized stats.

Run: `python -m src.backtest SYMBOL TIER START_ISO END_ISO`
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import sys
from typing import Any

from src import binance_client as bx
from src import db, jobs
from src.config import load_config
from src.signal_engine import compute_entry_sl_tp, detect_regime, detect_setup

RULE_VERSION = 1
MAX_HOLD_BARS_1H = 72  # ~3 days; PRD doesn't set a holding cap, this bounds the sim


def fetch_historical_ohlcv(exchange, symbol: str, timeframe: str, since_ms: int, until_ms: int) -> list[list[float]]:
    """Paginates ccxt fetch_ohlcv from since_ms up to (not including) until_ms."""
    all_candles: list[list[float]] = []
    cursor = since_ms
    while cursor < until_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=1000)
        if not batch:
            break
        all_candles.extend(batch)
        cursor = batch[-1][0] + 1
        if len(batch) < 1000:
            break
    return [c for c in all_candles if c[0] < until_ms]


def build_indicator_series(candles: list[list[float]]) -> list[dict[str, Any]]:
    """Reuses jobs.py's pure indicator math, but keeps the whole history
    (jobs.compute_indicators only keeps the latest closed candle)."""
    import pandas as pd

    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ema50"] = jobs._ema(df["close"], 50)
    df["ema200"] = jobs._ema(df["close"], 200)
    df["rsi"] = jobs._rsi(df["close"], 14)
    df["atr"] = jobs._atr(df["high"], df["low"], df["close"], 14)

    rows = df.to_dict("records")
    for i, row in enumerate(rows):
        window_highs = [r["high"] for r in rows[max(0, i - 19) : i + 1]]
        window_lows = [r["low"] for r in rows[max(0, i - 19) : i + 1]]
        row["structure"] = jobs.detect_structure(window_highs, window_lows)
    return rows


def align_4h_index(ts_4h: list[int], ts_1h: int) -> int | None:
    """Pure function: index of the latest 4H candle closed at or before a
    given 1H candle's timestamp (bisect avoids an O(n) scan per 1H bar)."""
    idx = bisect.bisect_right(ts_4h, ts_1h) - 1
    return idx if idx >= 0 else None


def simulate_outcome(direction: str, entry: float, sl: float, tp1: float, tp2: float, future_bars: list[dict[str, Any]]) -> float:
    """Pure function: walks forward bar-by-bar and returns the realized
    R-multiple. Position is 50% closed at TP1 (matches the kartu saran:
    'TP1 tutup 50%'), remainder runs to TP2 or SL."""
    hit_tp1 = False
    for bar in future_bars[:MAX_HOLD_BARS_1H]:
        high, low = bar["high"], bar["low"]
        if direction == "long":
            sl_hit, tp1_hit, tp2_hit = low <= sl, high >= tp1, high >= tp2
        else:
            sl_hit, tp1_hit, tp2_hit = high >= sl, low <= tp1, low <= tp2

        if not hit_tp1:
            if sl_hit:
                return -1.0
            if tp1_hit:
                hit_tp1 = True
        else:
            if sl_hit:
                return 0.5 * 1 + 0.5 * (-1)
            if tp2_hit:
                return 0.5 * 1 + 0.5 * 2

    if hit_tp1:
        return 0.5  # TP1 secured; remainder unresolved within the hold window
    if not future_bars:
        return 0.0
    last_close = future_bars[min(len(future_bars), MAX_HOLD_BARS_1H) - 1]["close"]
    sl_distance = abs(entry - sl)
    sign = 1 if direction == "long" else -1
    return (last_close - entry) / sl_distance * sign


def max_drawdown_r(r_multiples: list[float]) -> float:
    """Pure function: largest peak-to-trough drop in cumulative R."""
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for r in r_multiples:
        cumulative += r
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return worst


def run_backtest(cfg, symbol: str, tier: str, start: dt.datetime, end: dt.datetime) -> dict[str, Any]:
    exchange = bx.get_exchange(cfg)
    since_ms, until_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    candles_1h = fetch_historical_ohlcv(exchange, symbol, "1h", since_ms, until_ms)
    candles_4h = fetch_historical_ohlcv(exchange, symbol, "4h", since_ms, until_ms)
    series_1h = build_indicator_series(candles_1h)
    series_4h = build_indicator_series(candles_4h)
    ts_4h = [row["ts"] for row in series_4h]

    r_multiples: list[float] = []
    warmup = 210
    for i in range(warmup, len(series_1h)):
        latest_1h = series_1h[i]
        idx_4h = align_4h_index(ts_4h, latest_1h["ts"])
        if idx_4h is None or idx_4h < warmup:
            continue
        latest_4h = series_4h[idx_4h]
        prior_atrs = [row["atr"] for row in series_4h[max(0, idx_4h - 20) : idx_4h]]
        direction = detect_regime(latest_4h, prior_atrs)
        if direction == "chop":
            continue
        setup = detect_setup(direction, latest_1h)
        if not setup:
            continue
        entry, sl, tp1, tp2 = compute_entry_sl_tp(direction, setup, latest_1h, tier)
        r = simulate_outcome(direction, entry, sl, tp1, tp2, series_1h[i + 1 :])
        r_multiples.append(r)

    n = len(r_multiples)
    stats = {
        "symbol": symbol,
        "tier": tier,
        "rule_version": RULE_VERSION,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "n_signals": n,
        "win_rate": (sum(1 for r in r_multiples if r > 0) / n) if n else 0.0,
        "expectancy_r": (sum(r_multiples) / n) if n else 0.0,
        "max_drawdown_r": max_drawdown_r(r_multiples),
    }
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest mesin saran rules on historical klines")
    parser.add_argument("symbol")
    parser.add_argument("tier", choices=["inti", "alt", "meme"])
    parser.add_argument("start", help="ISO date, e.g. 2026-01-01")
    parser.add_argument("end", help="ISO date, e.g. 2026-11-01")
    args = parser.parse_args()

    cfg = load_config()
    client = db.get_client(cfg)
    start = dt.datetime.fromisoformat(args.start).replace(tzinfo=dt.timezone.utc)
    end = dt.datetime.fromisoformat(args.end).replace(tzinfo=dt.timezone.utc)

    stats = run_backtest(cfg, args.symbol, args.tier, start, end)
    client.table("backtests").insert(stats).execute()
    print(stats)


if __name__ == "__main__":
    sys.exit(main())

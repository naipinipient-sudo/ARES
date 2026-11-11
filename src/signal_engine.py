"""Mesin saran trade (PRD 'Mesin saran trade & kalkulator risiko'): four
sequential stages — regime filter, setup trigger, confirmation/veto, then
src/risk.py sizes the trade. Any stage failing means no card, ever. This is
rule-based code, not an LLM call: the LLM (when wired) only ever gets to
phrase the reasons, never to decide pass/fail.
Scheduled from src/main.py; persists to the `signals` table for job 12."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Iterator

from src import binance_client as bx
from src import db
from src import risk
from src.config import Config

logger = logging.getLogger(__name__)

# Meme tier per PRD "Aturan tambahan": wider stop to survive its noise.
MEME_MIN_ATR_MULTIPLE = 1.5
DEFAULT_ATR_MULTIPLE = 1.5
PULLBACK_SL_ATR_MULTIPLE = 1.0
EVENT_VETO_HOURS = 4


# --- Stage 1: regime filter (4H) ----------------------------------------------------


def is_chop(latest: dict[str, Any], prior_atrs: list[float]) -> bool:
    """Pure function: price whipsawing around EMA200 with ATR compressing."""
    if not prior_atrs:
        return False
    avg_atr = sum(prior_atrs) / len(prior_atrs)
    near_ema200 = abs(latest["close"] - latest["ema200"]) < 0.5 * latest["atr"]
    narrowing = latest["atr"] < 0.8 * avg_atr
    return near_ema200 and narrowing


def detect_regime(latest_4h: dict[str, Any], prior_atrs: list[float]) -> str:
    """Pure function: 'long', 'short', or 'chop' (PRD stage 1)."""
    if is_chop(latest_4h, prior_atrs):
        return "chop"
    return "long" if latest_4h["close"] > latest_4h["ema200"] else "short"


# --- Stage 2: setup trigger (1H) -----------------------------------------------------


def detect_setup(direction: str, latest_1h: dict[str, Any]) -> str | None:
    """Pure function: 'pullback_ema50', 'break_of_structure', or None."""
    close, ema50, atr, rsi, structure = (
        latest_1h["close"],
        latest_1h["ema50"],
        latest_1h["atr"],
        latest_1h["rsi"],
        latest_1h["structure"],
    )
    near_ema50 = abs(close - ema50) <= 0.3 * atr
    rsi_reset = 35 <= rsi <= 55 if direction == "long" else 45 <= rsi <= 65
    if near_ema50 and rsi_reset:
        return "pullback_ema50"
    if direction == "long" and structure == "HH":
        return "break_of_structure"
    if direction == "short" and structure == "LL":
        return "break_of_structure"
    return None


def compute_entry_sl_tp(direction: str, setup: str, latest_1h: dict[str, Any], tier: str) -> tuple[float, float, float, float]:
    """Pure function: market entry at the last close; SL distance is an ATR
    multiple (wider for meme / breakout setups); TP2 is built at exactly
    2x the SL distance so RRR>=2 holds by construction."""
    entry = latest_1h["close"]
    atr = latest_1h["atr"]
    multiple = MEME_MIN_ATR_MULTIPLE if tier == "meme" else (PULLBACK_SL_ATR_MULTIPLE if setup == "pullback_ema50" else DEFAULT_ATR_MULTIPLE)
    distance = atr * multiple
    sign = 1 if direction == "long" else -1
    sl = entry - sign * distance
    tp1 = entry + sign * distance
    tp2 = entry + sign * 2 * distance
    return entry, sl, tp1, tp2


# --- Stage 3: confirmation & larangan -------------------------------------------------


def check_vetoes(
    direction: str,
    derivatives: dict[str, Any] | None,
    events_within_4h: list[dict[str, Any]],
) -> list[str]:
    """Pure function: PRD 'Larangan mutlak' (minus the news veto, which stays
    off until LLM labeling is wired — see src/jobs.py job5 note)."""
    reasons = []
    if derivatives and derivatives.get("funding_extreme"):
        funding_rate = derivatives.get("funding_rate") or 0.0
        if (direction == "long" and funding_rate > 0) or (direction == "short" and funding_rate < 0):
            reasons.append("funding ekstrem searah posisi")
    if events_within_4h:
        names = ", ".join(e["name"] for e in events_within_4h)
        reasons.append(f"event makro dalam {EVENT_VETO_HOURS} jam: {names}")
    return reasons


def confirmation_score(direction: str, derivatives: dict[str, Any] | None) -> int:
    """Pure function: 'skor = jumlah syarat terpenuhi, bukan peluang menang'."""
    if not derivatives:
        return 0
    score = 0
    ls_ratio = derivatives.get("long_short_account_ratio")
    taker_ratio = derivatives.get("taker_long_short_ratio")
    oi_change = derivatives.get("oi_change_pct") or 0
    if ls_ratio is not None and ((direction == "long" and ls_ratio > 1) or (direction == "short" and ls_ratio < 1)):
        score += 1
    if taker_ratio is not None and ((direction == "long" and taker_ratio > 1) or (direction == "short" and taker_ratio < 1)):
        score += 1
    if (direction == "long" and oi_change > 0) or (direction == "short" and oi_change < 0):
        score += 1
    return score


# --- Orchestration (impure: reads Supabase/Binance, writes `signals`) ----------------


def _latest_snapshots(client, symbol: str, timeframe: str, limit: int) -> list[dict[str, Any]]:
    res = (
        client.table("market_snapshots")
        .select("*")
        .eq("symbol", symbol)
        .eq("timeframe", timeframe)
        .order("ts", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(res.data))  # oldest -> newest


def generate_signal(cfg: Config, client, watchlist_entry: dict[str, Any]) -> dict[str, Any] | None:
    symbol, tier = watchlist_entry["symbol"], watchlist_entry["tier"]

    snaps_4h = _latest_snapshots(client, symbol, "4h", limit=21)
    if not snaps_4h:
        return None
    latest_4h = snaps_4h[-1]
    prior_atrs = [s["atr"] for s in snaps_4h[:-1]]
    direction = detect_regime(latest_4h, prior_atrs)
    if direction == "chop":
        return None

    snaps_1h = _latest_snapshots(client, symbol, "1h", limit=1)
    if not snaps_1h:
        return None
    latest_1h = snaps_1h[-1]
    setup = detect_setup(direction, latest_1h)
    if not setup:
        return None

    deriv_res = client.table("derivatives_pulse").select("*").eq("symbol", symbol).order("ts", desc=True).limit(1).execute()
    derivatives = deriv_res.data[0] if deriv_res.data else None

    from src import jobs as jobs_module  # local import: avoids a jobs<->signal_engine import cycle

    events = jobs_module.job10_check_events(client, within_hours=EVENT_VETO_HOURS)
    vetoes = check_vetoes(direction, derivatives, events)
    if vetoes:
        return None

    entry, sl, tp1, tp2 = compute_entry_sl_tp(direction, setup, latest_1h, tier)

    exchange = bx.get_exchange(cfg)
    account = bx.fetch_account_snapshot(exchange)
    day_start = risk.wib_day_start_utc()
    day_start_res = (
        client.table("account_snapshots").select("total_balance").gte("ts", day_start.isoformat()).order("ts").limit(1).execute()
    )
    balance_at_day_start = (day_start_res.data[0]["total_balance"] if day_start_res.data else account["total_balance"]) or account["total_balance"]

    open_positions_with_tier = []
    watchlist_by_symbol = {row["symbol"]: row for row in db.get_watchlist(client)}
    for p in account["positions"]:
        wl = watchlist_by_symbol.get(p["symbol"])
        open_positions_with_tier.append({"symbol": p["symbol"], "tier": wl["tier"] if wl else None})

    risk_pct = {"inti": cfg.risk_pct_inti, "alt": cfg.risk_pct_alt, "meme": cfg.risk_pct_meme}[tier]
    safety = risk.check_account_safety(
        balance_at_day_start=balance_at_day_start,
        balance_now=account["total_balance"],
        daily_loss_limit_pct=cfg.daily_loss_limit_pct,
        open_positions=open_positions_with_tier,
        max_open_positions=cfg.max_open_positions,
        new_trade_tier=tier,
    )
    if not safety.ok:
        return None

    max_leverage = cfg.max_leverage_meme if tier == "meme" else cfg.max_leverage_default
    plan = risk.build_trade_plan(
        balance=account["total_balance"],
        risk_pct=risk_pct,
        entry=entry,
        sl=sl,
        tp2=tp2,
        side=direction,
        max_leverage=max_leverage,
    )
    if not plan.ok:
        return None

    score = confirmation_score(direction, derivatives)
    reasons = [f"regime {direction} (4H vs EMA200)", f"setup {setup} (1H)"]
    if derivatives:
        reasons.append(f"skor konfirmasi derivatif: {score}/3")

    return {
        "symbol": symbol,
        "tier": tier,
        "direction": direction,
        "setup": setup,
        "score": score,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "rrr": plan.rrr,
        "qty": plan.qty,
        "leverage": plan.leverage,
        "margin": plan.margin,
        "risk_usdt": plan.risk_usdt,
        "risk_pct": plan.risk_pct,
        "liquidation_price": plan.liquidation_price,
        "reasons": reasons,
        "account_open_positions": len(account["positions"]),
        "account_daily_loss_pct": risk.daily_loss_pct(balance_at_day_start, account["total_balance"]),
    }


def format_signal_card(card: dict[str, Any]) -> str:
    arrow = "LONG" if card["direction"] == "long" else "SHORT"
    lines = [
        f"{arrow} {card['symbol']} — skor {card['score']}/3 (jumlah syarat, bukan peluang menang)",
        f"Entry: {card['entry']:.6g} (market)",
        f"SL: {card['sl']:.6g}",
        f"TP1 (tutup 50%): {card['tp1']:.6g}",
        f"TP2: {card['tp2']:.6g}",
        f"RRR ke TP2: {card['rrr']:.2f}",
        f"Qty: {card['qty']:.6g} | Leverage: {card['leverage']}x isolated | Margin: {card['margin']:.2f} USDT",
        f"Risiko: {card['risk_usdt']:.2f} USDT ({card['risk_pct']}%)",
        f"Est. likuidasi: {card['liquidation_price']:.6g}",
        "Alasan: " + "; ".join(card["reasons"]),
        "Kondisi batal: setup invalid jika harga balik lewati EMA50 sebelum entry, atau SL kena sebelum entry diisi.",
        "Masa berlaku: sampai candle 1H berikutnya ditutup.",
        f"Status akun: {card['account_open_positions']} posisi terbuka, rugi hari ini {card['account_daily_loss_pct']:.2f}%",
    ]
    return "\n".join(lines)


def generate_signals_job(cfg: Config, client) -> Iterator[dict[str, Any]]:
    for entry in db.get_watchlist(client, mode="saran"):
        try:
            card = generate_signal(cfg, client, entry)
        except Exception:
            logger.exception("signal generation failed for %s", entry["symbol"])
            continue
        if not card:
            continue
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        row = {**card, "reasons": "; ".join(card["reasons"]), "status": "sent", "rule_version": 1, "created_at": now}
        client.table("signals").insert(row).execute()
        yield card  # caller (src/main.py) sends each card to Telegram as it's produced

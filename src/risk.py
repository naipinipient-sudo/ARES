"""Risk Desk: position sizing, leverage/liquidation safety, and account-level
guardrails (PRD 'Mesin saran trade & kalkulator risiko'). Pure, side-effect-free
functions — everything here is pass/fail math, not an API call or an LLM
opinion ('Risk Desk adalah kode, bukan LLM'). Imported by src/signal_engine.py."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

# Binance USDS-M taker fee at VIP0; charged on both entry and exit.
DEFAULT_TAKER_FEE_RATE = 0.0004

MIN_RRR = 2.0


@dataclass
class TradePlan:
    ok: bool
    reason: str | None
    qty: float = 0.0
    notional: float = 0.0
    margin: float = 0.0
    leverage: int = 0
    risk_usdt: float = 0.0
    risk_pct: float = 0.0
    liquidation_price: float = 0.0
    rrr: float = 0.0


def estimate_liquidation_price(entry: float, leverage: int, side: str) -> float:
    """Pure function: simplified isolated-margin liquidation estimate.
    ponytail: ignores Binance's tiered maintenance-margin-rate table (the
    exact formula needs the per-notional leverage bracket from Binance's
    API) — upgrade to real MMR tiers before sizing real capital with high
    leverage on larger notional."""
    if side == "long":
        return entry * (1 - 1 / leverage)
    return entry * (1 + 1 / leverage)


def pick_safe_leverage(entry: float, sl: float, side: str, max_leverage: int) -> int:
    """Pure function: highest leverage (<= max_leverage) whose liquidation
    price still sits beyond the stop loss. Falls back to 1x."""
    for leverage in range(max_leverage, 0, -1):
        liq = estimate_liquidation_price(entry, leverage, side)
        if side == "long" and liq < sl:
            return leverage
        if side == "short" and liq > sl:
            return leverage
    return 1


def calculate_position_size(
    balance: float, risk_pct: float, entry: float, sl: float, fee_rate: float = DEFAULT_TAKER_FEE_RATE
) -> tuple[float, float]:
    """Pure function: PRD formula 'qty = (modal x risk% - fee) / |entry - SL|',
    solved in closed form since fee depends on qty*entry (entry+exit, both
    at the taker rate). Returns (qty, risk_usdt)."""
    risk_usdt = balance * (risk_pct / 100)
    sl_distance = abs(entry - sl)
    denom = sl_distance + entry * fee_rate * 2
    qty = risk_usdt / denom if denom > 0 else 0.0
    return qty, risk_usdt


def build_trade_plan(
    *,
    balance: float,
    risk_pct: float,
    entry: float,
    sl: float,
    tp2: float,
    side: str,
    max_leverage: int,
    fee_rate: float = DEFAULT_TAKER_FEE_RATE,
) -> TradePlan:
    """The risk engine's single entry point: sizes a trade from real account
    balance and vetoes it outright if RRR or the liquidation buffer fail."""
    rrr = abs(tp2 - entry) / abs(entry - sl) if entry != sl else 0.0
    if rrr < MIN_RRR:
        return TradePlan(ok=False, reason=f"RRR {rrr:.2f} < {MIN_RRR}", rrr=rrr)

    qty, risk_usdt = calculate_position_size(balance, risk_pct, entry, sl, fee_rate)
    if qty <= 0:
        return TradePlan(ok=False, reason="qty<=0 (entry==SL atau saldo 0)")

    leverage = pick_safe_leverage(entry, sl, side, max_leverage)
    notional = qty * entry
    margin = notional / leverage
    liquidation_price = estimate_liquidation_price(entry, leverage, side)

    return TradePlan(
        ok=True,
        reason=None,
        qty=qty,
        notional=notional,
        margin=margin,
        leverage=leverage,
        risk_usdt=risk_usdt,
        risk_pct=risk_pct,
        liquidation_price=liquidation_price,
        rrr=rrr,
    )


def daily_loss_pct(balance_at_day_start: float, balance_now: float) -> float:
    """Pure function: positive number = a loss, as a percent of the day's
    starting balance."""
    if balance_at_day_start <= 0:
        return 0.0
    return max(0.0, (balance_at_day_start - balance_now) / balance_at_day_start * 100)


def wib_day_start_utc(now: dt.datetime | None = None) -> dt.datetime:
    """Pure function: the UTC instant corresponding to 00:00 WIB (UTC+7) of
    the current WIB day."""
    now = now or dt.datetime.now(dt.timezone.utc)
    wib_now = now + dt.timedelta(hours=7)
    wib_midnight = wib_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return wib_midnight - dt.timedelta(hours=7)


@dataclass
class AccountSafety:
    ok: bool
    reasons: list[str]


def check_account_safety(
    *,
    balance_at_day_start: float,
    balance_now: float,
    daily_loss_limit_pct: float,
    open_positions: list[dict],
    max_open_positions: int,
    new_trade_tier: str,
    max_meme_positions: int = 1,
) -> AccountSafety:
    """Account-level gate, independent of any single trade's math (PRD
    'Pengaman akun'). ponytail: total-correlated-risk is approximated by the
    open-position/meme-position counts rather than a real correlation
    matrix — add real correlation weighting if multi-asset drawdowns in the
    rapor sinyal show the approximation under- or over-blocking."""
    reasons = []
    if daily_loss_pct(balance_at_day_start, balance_now) >= daily_loss_limit_pct:
        reasons.append(f"batas rugi harian {daily_loss_limit_pct}% tercapai")
    if len(open_positions) >= max_open_positions:
        reasons.append(f"sudah {len(open_positions)} posisi terbuka (maks {max_open_positions})")
    if new_trade_tier == "meme":
        open_meme = sum(1 for p in open_positions if p.get("tier") == "meme")
        if open_meme >= max_meme_positions:
            reasons.append("sudah ada posisi meme terbuka")
    return AccountSafety(ok=not reasons, reasons=reasons)

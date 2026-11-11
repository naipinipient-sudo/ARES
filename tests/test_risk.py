import datetime as dt

from src.risk import (
    build_trade_plan,
    calculate_position_size,
    check_account_safety,
    daily_loss_pct,
    pick_safe_leverage,
    wib_day_start_utc,
)


def test_realized_loss_at_sl_never_exceeds_risk_budget():
    """The P0 acceptance criterion: 'rugi teoretis di SL tidak pernah
    melebihi risk%', fee included."""
    balance = 1000.0
    risk_pct = 1.0
    for entry, sl, fee_rate in [(100_000, 98_500, 0.0004), (3_000, 2_950, 0.0004), (0.5, 0.49, 0.001)]:
        qty, risk_usdt = calculate_position_size(balance, risk_pct, entry, sl, fee_rate)
        realized_loss = qty * abs(entry - sl) + qty * entry * fee_rate * 2
        assert realized_loss <= risk_usdt + 1e-9


def test_calculate_position_size_same_order_as_prd_example():
    # PRD: modal 1000, risk 1% -> qty ~ 0.0067 BTC (fee-free illustration).
    qty, risk_usdt = calculate_position_size(1000.0, 1.0, 100_000, 98_500, fee_rate=0.0)
    assert risk_usdt == 10.0
    assert abs(qty - 0.006667) < 1e-4


def test_pick_safe_leverage_keeps_liquidation_beyond_sl():
    entry, sl = 100_000, 98_500
    leverage = pick_safe_leverage(entry, sl, "long", max_leverage=3)
    liq = entry * (1 - 1 / leverage)
    assert liq < sl


def test_build_trade_plan_rejects_low_rrr():
    plan = build_trade_plan(
        balance=1000, risk_pct=1.0, entry=100_000, sl=98_500, tp2=101_000, side="long", max_leverage=3
    )
    assert plan.ok is False
    assert "RRR" in plan.reason


def test_build_trade_plan_accepts_valid_setup():
    plan = build_trade_plan(
        balance=1000, risk_pct=1.0, entry=100_000, sl=98_500, tp2=103_000, side="long", max_leverage=3
    )
    assert plan.ok is True
    assert plan.leverage <= 3
    assert plan.margin == plan.notional / plan.leverage


def test_daily_loss_pct():
    assert daily_loss_pct(1000, 970) == 3.0
    assert daily_loss_pct(1000, 1010) == 0.0  # a gain is not a loss


def test_check_account_safety_blocks_after_daily_loss_limit():
    result = check_account_safety(
        balance_at_day_start=1000,
        balance_now=965,
        daily_loss_limit_pct=3.0,
        open_positions=[],
        max_open_positions=2,
        new_trade_tier="inti",
    )
    assert result.ok is False
    assert any("rugi harian" in r for r in result.reasons)


def test_check_account_safety_blocks_third_position():
    result = check_account_safety(
        balance_at_day_start=1000,
        balance_now=1000,
        daily_loss_limit_pct=3.0,
        open_positions=[{"tier": "inti"}, {"tier": "alt"}],
        max_open_positions=2,
        new_trade_tier="inti",
    )
    assert result.ok is False


def test_check_account_safety_blocks_second_meme_position():
    result = check_account_safety(
        balance_at_day_start=1000,
        balance_now=1000,
        daily_loss_limit_pct=3.0,
        open_positions=[{"tier": "meme"}],
        max_open_positions=2,
        new_trade_tier="meme",
    )
    assert result.ok is False
    assert any("meme" in r for r in result.reasons)


def test_wib_day_start_utc_is_17_utc_previous_day():
    now = dt.datetime(2026, 11, 12, 10, 0, tzinfo=dt.timezone.utc)  # 17:00 WIB
    start = wib_day_start_utc(now)
    assert start == dt.datetime(2026, 11, 11, 17, 0, tzinfo=dt.timezone.utc)

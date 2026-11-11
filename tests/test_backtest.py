from src.backtest import align_4h_index, max_drawdown_r, simulate_outcome


def test_align_4h_index_picks_latest_closed_4h_candle():
    ts_4h = [1000, 2000, 3000, 4000]
    assert align_4h_index(ts_4h, 3500) == 2  # ts=3000
    assert align_4h_index(ts_4h, 3000) == 2  # exact match counts as closed
    assert align_4h_index(ts_4h, 500) is None


def test_simulate_outcome_sl_hit_first_is_minus_one_r():
    bars = [{"high": 101, "low": 97, "close": 98}]  # SL=98 hit before TP1=105
    r = simulate_outcome("long", entry=100, sl=98, tp1=105, tp2=110, future_bars=bars)
    assert r == -1.0


def test_simulate_outcome_tp1_then_tp2_is_one_point_five_r():
    bars = [{"high": 106, "low": 99, "close": 106}, {"high": 111, "low": 104, "close": 111}]
    r = simulate_outcome("long", entry=100, sl=98, tp1=105, tp2=110, future_bars=bars)
    assert r == 1.5


def test_simulate_outcome_tp1_then_sl_is_zero_r():
    bars = [{"high": 106, "low": 99, "close": 106}, {"high": 103, "low": 97, "close": 97}]
    r = simulate_outcome("long", entry=100, sl=98, tp1=105, tp2=110, future_bars=bars)
    assert r == 0.0


def test_simulate_outcome_short_direction():
    bars = [{"high": 99, "low": 94, "close": 94}]  # TP1=95 hit, SL=102 not touched
    r = simulate_outcome("short", entry=100, sl=102, tp1=95, tp2=90, future_bars=bars)
    assert r == 0.5  # only TP1 touched within the single bar provided


def test_max_drawdown_r_tracks_peak_to_trough():
    assert max_drawdown_r([1, 1, -3, 1]) == -3
    assert max_drawdown_r([1, 1, 1]) == 0
    assert max_drawdown_r([]) == 0

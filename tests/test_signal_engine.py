from src.signal_engine import (
    check_vetoes,
    compute_entry_sl_tp,
    confirmation_score,
    detect_regime,
    detect_setup,
    is_chop,
)


def test_detect_regime_long_and_short():
    assert detect_regime({"close": 110, "ema200": 100, "atr": 2}, [5, 5, 5]) == "long"
    assert detect_regime({"close": 90, "ema200": 100, "atr": 2}, [5, 5, 5]) == "short"


def test_is_chop_true_when_narrow_and_near_ema200():
    latest = {"close": 100.3, "ema200": 100, "atr": 1.0}
    assert is_chop(latest, [2.0, 2.0, 2.0]) is True


def test_is_chop_false_when_trending_away_from_ema200():
    latest = {"close": 120, "ema200": 100, "atr": 2.0}
    assert is_chop(latest, [2.0, 2.0]) is False


def test_detect_setup_pullback_ema50():
    latest = {"close": 100.1, "ema50": 100.0, "atr": 1.0, "rsi": 45, "structure": "range"}
    assert detect_setup("long", latest) == "pullback_ema50"


def test_detect_setup_break_of_structure():
    latest = {"close": 110, "ema50": 100.0, "atr": 1.0, "rsi": 70, "structure": "HH"}
    assert detect_setup("long", latest) == "break_of_structure"


def test_detect_setup_none_when_no_trigger():
    latest = {"close": 110, "ema50": 100.0, "atr": 1.0, "rsi": 70, "structure": "range"}
    assert detect_setup("long", latest) is None


def test_compute_entry_sl_tp_long_has_rrr_two():
    entry, sl, tp1, tp2 = compute_entry_sl_tp("long", "break_of_structure", {"close": 100, "atr": 2}, "inti")
    assert entry == 100
    assert sl < entry < tp1 < tp2
    assert abs((tp2 - entry) / (entry - sl) - 2.0) < 1e-9


def test_compute_entry_sl_tp_meme_uses_wider_atr_multiple():
    _, sl_inti, _, _ = compute_entry_sl_tp("long", "break_of_structure", {"close": 100, "atr": 2}, "inti")
    _, sl_meme, _, _ = compute_entry_sl_tp("long", "break_of_structure", {"close": 100, "atr": 2}, "meme")
    assert (100 - sl_meme) >= (100 - sl_inti)


def test_check_vetoes_funding_extreme_same_direction():
    derivatives = {"funding_extreme": True, "funding_rate": 0.002}
    assert check_vetoes("long", derivatives, []) != []
    assert check_vetoes("short", derivatives, []) == []  # extreme but opposite direction


def test_check_vetoes_event_within_window():
    events = [{"name": "FOMC", "within_1h": True}]
    reasons = check_vetoes("long", None, events)
    assert any("FOMC" in r for r in reasons)


def test_confirmation_score_counts_matching_signals():
    derivatives = {"long_short_account_ratio": 1.5, "taker_long_short_ratio": 1.2, "oi_change_pct": 3}
    assert confirmation_score("long", derivatives) == 3
    assert confirmation_score("short", derivatives) == 0

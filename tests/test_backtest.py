"""Tests for backtest outcome simulation (forward-walk logic)."""

from app.training.backtest import simulate_setup_outcome


def _candle(low, high, close=None, op=None):
    """Small helper to build candles."""
    c = close if close is not None else (low + high) / 2
    o = op if op is not None else c
    return {"low": low, "high": high, "close": c, "open": o, "volume": 0,
            "datetime": None}


def test_buy_setup_hits_full_tp():
    setup = {
        "direction": "buy",
        "entries": [4520.0], "avg_entry": 4520.0,
        "stop_loss": 4500.0,
        "take_profits": [{"level": 4540.0}],
    }
    future = [
        _candle(4516, 4525),  # touches entry
        _candle(4520, 4535),
        _candle(4538, 4545, close=4541),  # hits TP
    ]
    r = simulate_setup_outcome(setup, future)
    assert r["filled"] is True
    assert r["status"] == "tp_full"
    assert r["realized_rr"] == 1.0


def test_buy_setup_hits_sl():
    setup = {
        "direction": "buy",
        "entries": [4520.0], "avg_entry": 4520.0,
        "stop_loss": 4500.0,
        "take_profits": [{"level": 4540.0}],
    }
    future = [
        _candle(4515, 4525),  # entry filled
        _candle(4495, 4520),  # SL hit
    ]
    r = simulate_setup_outcome(setup, future)
    assert r["filled"] is True
    assert r["status"] == "sl"
    assert r["realized_rr"] == -1.0


def test_buy_unfilled_expires():
    setup = {
        "direction": "buy",
        "entries": [4500.0], "avg_entry": 4500.0,
        "stop_loss": 4480.0,
        "take_profits": [{"level": 4520.0}],
    }
    # Future never drops to entry
    future = [_candle(4510, 4515) for _ in range(10)]
    r = simulate_setup_outcome(setup, future)
    assert r["filled"] is False
    assert r["status"] == "expired_unfilled"


def test_sell_setup_hits_full_tp():
    setup = {
        "direction": "sell",
        "entries": [4540.0], "avg_entry": 4540.0,
        "stop_loss": 4560.0,
        "take_profits": [{"level": 4500.0}],
    }
    future = [
        _candle(4538, 4542),  # entry filled
        _candle(4520, 4540),
        _candle(4498, 4515),  # TP hit
    ]
    r = simulate_setup_outcome(setup, future)
    assert r["filled"] is True
    assert r["status"] == "tp_full"
    assert r["realized_rr"] == 2.0  # (4540-4500)/(4560-4540)


def test_invalid_setup_zero_risk():
    setup = {
        "direction": "buy",
        "entries": [4500.0], "avg_entry": 4500.0,
        "stop_loss": 4500.0,  # equal → zero risk
        "take_profits": [{"level": 4520.0}],
    }
    future = [_candle(4499, 4521)]
    r = simulate_setup_outcome(setup, future)
    assert r["filled"] is False
    assert "invalid" in r["status"]


def test_invalid_setup_no_entries():
    setup = {
        "direction": "buy",
        "entries": [], "stop_loss": 4500.0,
        "take_profits": [{"level": 4520.0}],
    }
    r = simulate_setup_outcome(setup, [_candle(4510, 4520)])
    assert r["filled"] is False
    assert r["status"] == "invalid"

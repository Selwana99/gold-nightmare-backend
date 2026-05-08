"""Tests for outcome tracker logic — buy/sell fills, TP/SL detection."""

import pytest
from datetime import datetime
from app.models.analysis_outcome import AnalysisOutcome
from app.training.outcome_tracker import _check_buy_outcome, _check_sell_outcome


def _mk_outcome(direction="buy", entry=4520.0, sl=4500.0, tps=None, **kw):
    """Helper: build a fresh outcome model for testing."""
    if tps is None:
        tps = [
            {"level": 4540.0, "close_pct": 50, "label_ar": "TP1"},
            {"level": 4560.0, "close_pct": 50, "label_ar": "TP2"},
        ]
        if direction == "sell":
            tps = [
                {"level": 4500.0, "close_pct": 50, "label_ar": "TP1"},
                {"level": 4480.0, "close_pct": 50, "label_ar": "TP2"},
            ]
    o = AnalysisOutcome(
        analysis_id="a-test",
        setup_index=0,
        setup_label="Test",
        direction=direction,
        entry_price=entry,
        stop_loss=sl,
        tp_levels=tps,
        chart_price_at_creation=4525.0,
        is_active=True,
        entry_filled=False,
        status="pending",
        tp1_hit=False, tp2_hit=False, tp3_hit=False, tp4_hit=False,
        sl_hit=False,
        check_count=0,
    )
    for k, v in kw.items():
        setattr(o, k, v)
    return o


# ─── BUY outcomes ───

def test_buy_entry_fill():
    o = _mk_outcome(direction="buy", entry=4520.0)
    # Price hasn't reached entry yet
    upd = _check_buy_outcome(o, current_price=4525.0)
    assert "entry_filled" not in upd

    # Price drops to entry → filled
    upd = _check_buy_outcome(o, current_price=4519.0)
    assert upd.get("entry_filled") is True
    assert upd.get("status") == "active"


def test_buy_sl_hit():
    o = _mk_outcome(direction="buy", entry=4520.0, sl=4500.0,
                    entry_filled=True, status="active")
    upd = _check_buy_outcome(o, current_price=4499.0)
    assert upd.get("sl_hit") is True
    assert upd.get("status") == "sl_hit"
    assert upd.get("realized_rr") == -1.0
    assert upd.get("is_active") is False


def test_buy_full_tp():
    o = _mk_outcome(direction="buy", entry=4520.0, sl=4500.0,
                    entry_filled=True, status="active",
                    tps=[{"level": 4540.0, "close_pct": 100, "label_ar": "TP1"}])
    o.tp_levels = [{"level": 4540.0, "close_pct": 100, "label_ar": "TP1"}]
    upd = _check_buy_outcome(o, current_price=4540.0)
    assert upd.get("tp1_hit") is True
    # Single TP hit means tp_full
    assert upd.get("status") == "tp_full"
    assert upd.get("realized_rr") == pytest.approx(1.0, abs=0.01)


# ─── SELL outcomes ───

def test_sell_entry_fill():
    o = _mk_outcome(direction="sell", entry=4540.0, sl=4560.0)
    # Price below entry — not filled
    upd = _check_sell_outcome(o, current_price=4530.0)
    assert "entry_filled" not in upd

    # Price rises to entry → filled
    upd = _check_sell_outcome(o, current_price=4541.0)
    assert upd.get("entry_filled") is True
    assert upd.get("status") == "active"


def test_sell_sl_hit():
    o = _mk_outcome(direction="sell", entry=4540.0, sl=4560.0,
                    entry_filled=True, status="active")
    upd = _check_sell_outcome(o, current_price=4561.0)
    assert upd.get("sl_hit") is True
    assert upd.get("status") == "sl_hit"
    assert upd.get("realized_rr") == -1.0


def test_sell_full_tp():
    o = _mk_outcome(direction="sell", entry=4540.0, sl=4560.0,
                    entry_filled=True, status="active")
    o.tp_levels = [{"level": 4500.0, "close_pct": 100, "label_ar": "TP1"}]
    upd = _check_sell_outcome(o, current_price=4500.0)
    assert upd.get("tp1_hit") is True
    assert upd.get("status") == "tp_full"
    assert upd.get("realized_rr") == pytest.approx(2.0, abs=0.01)


def test_excursion_tracking_buy():
    """MFE/MAE should track favorable+adverse extremes for a filled buy."""
    o = _mk_outcome(direction="buy", entry=4520.0, sl=4500.0,
                    entry_filled=True, status="active")
    upd = _check_buy_outcome(o, current_price=4530.0)
    assert upd.get("max_favorable_excursion") == pytest.approx(10.0)
    assert upd.get("max_adverse_excursion") == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_create_outcomes_from_analysis(db_session):
    """Integration: creating outcomes from a real Analysis row."""
    from app.models.analysis import Analysis
    from app.training.outcome_tracker import create_outcomes_from_analysis

    analysis = Analysis(
        symbol="XAUUSD",
        timeframe="H1",
        is_mtf=False,
        chart_price=4520.0,
        result_json={
            "setups": [
                {
                    "label": "A - SELL",
                    "direction": "sell",
                    "entries": [4540.0, 4552.0],
                    "avg_entry": 4546.0,
                    "stop_loss": 4566.0,
                    "take_profits": [
                        {"level": 4520.0, "close_pct": 40, "label_ar": "TP1"},
                        {"level": 4500.0, "close_pct": 60, "label_ar": "TP2"},
                    ],
                    "risk_reward": "1:1.5",
                },
            ],
        },
        status="completed",
        model_used="claude-opus-4-7",
    )
    db_session.add(analysis)
    await db_session.flush()

    outcomes = await create_outcomes_from_analysis(db_session, analysis)
    assert len(outcomes) == 1
    o = outcomes[0]
    assert o.direction == "sell"
    assert o.entry_price == 4546.0
    assert o.stop_loss == 4566.0
    assert o.status == "pending"
    assert o.is_active is True

"""Tests for the rule-based validator."""

import pytest
from app.training.validator import (
    validate_setup, validate_analysis_result, _parse_rr_numeric,
)


def test_parse_rr_numeric():
    assert _parse_rr_numeric("1:2") == 2.0
    assert _parse_rr_numeric("1:1.5") == 1.5
    assert _parse_rr_numeric("2:6") == 3.0
    assert _parse_rr_numeric(None) == 0.0
    assert _parse_rr_numeric("garbage") == 0.0


# ─── Geometry rules ───

def test_buy_with_sl_above_entry_is_critical():
    setup = {
        "direction": "buy", "entries": [4520.0], "avg_entry": 4520.0,
        "stop_loss": 4530.0,  # ABOVE entry — wrong
        "take_profits": [{"level": 4540.0, "close_pct": 100}],
        "risk_reward": "1:1",
    }
    report = validate_setup(setup)
    assert report.is_rejected
    assert any(i.code == "INVERTED_SL_BUY" for i in report.issues)


def test_sell_with_sl_below_entry_is_critical():
    setup = {
        "direction": "sell", "entries": [4540.0], "avg_entry": 4540.0,
        "stop_loss": 4530.0,  # BELOW entry — wrong for SELL
        "take_profits": [{"level": 4500.0, "close_pct": 100}],
    }
    report = validate_setup(setup)
    assert report.is_rejected
    assert any(i.code == "INVERTED_SL_SELL" for i in report.issues)


def test_buy_with_tp_below_entry_is_critical():
    setup = {
        "direction": "buy", "entries": [4520.0], "avg_entry": 4520.0,
        "stop_loss": 4500.0,
        "take_profits": [{"level": 4515.0, "close_pct": 100}],  # below entry — wrong
    }
    report = validate_setup(setup)
    assert report.is_rejected


def test_clean_buy_setup_passes():
    setup = {
        "direction": "buy", "entries": [4520.0], "avg_entry": 4520.0,
        "stop_loss": 4500.0,
        "take_profits": [{"level": 4540.0, "close_pct": 50}, {"level": 4560.0, "close_pct": 50}],
        "risk_reward": "1:2",
    }
    report = validate_setup(setup, current_price=4525.0, htf_bias="bullish",
                             current_zone="discount", atr=10.0)
    assert not report.is_rejected
    # may have info-level issues but no critical
    assert all(i.severity != "critical" for i in report.issues)


# ─── R:R rule ───

def test_low_rr_warning():
    setup = {
        "direction": "buy", "entries": [4520.0], "avg_entry": 4520.0,
        "stop_loss": 4500.0,
        "take_profits": [{"level": 4525.0, "close_pct": 100}],  # only 5/20 = 0.25 R:R
        "risk_reward": "1:0.25",
    }
    report = validate_setup(setup, min_rr=1.0)
    # 0.25 < 0.5 → critical
    assert any(i.code == "POOR_RR" and i.severity == "critical" for i in report.issues)


# ─── ATR distance rule ───

def test_sl_too_close_atr():
    setup = {
        "direction": "buy", "entries": [4520.0], "avg_entry": 4520.0,
        "stop_loss": 4519.0,  # 1 point — way less than 0.5 ATR
        "take_profits": [{"level": 4540.0, "close_pct": 100}],
    }
    report = validate_setup(setup, atr=10.0)
    assert any(i.code == "SL_TOO_CLOSE_ATR" for i in report.issues)


def test_sl_too_far_atr():
    setup = {
        "direction": "buy", "entries": [4520.0], "avg_entry": 4520.0,
        "stop_loss": 4400.0,  # 120 points = 12 ATR
        "take_profits": [{"level": 4600.0, "close_pct": 100}],
    }
    report = validate_setup(setup, atr=10.0)
    assert any(i.code == "SL_TOO_FAR_ATR" for i in report.issues)


# ─── HTF bias misalignment ───

def test_buy_against_bearish_bias_warning():
    setup = {
        "direction": "buy", "entries": [4520.0], "avg_entry": 4520.0,
        "stop_loss": 4500.0,
        "take_profits": [{"level": 4540.0, "close_pct": 100}],
    }
    report = validate_setup(setup, htf_bias="bearish")
    assert any(i.code == "AGAINST_HTF_BIAS" for i in report.issues)


def test_buy_in_premium_warning():
    setup = {
        "direction": "buy", "entries": [4520.0], "avg_entry": 4520.0,
        "stop_loss": 4500.0,
        "take_profits": [{"level": 4540.0, "close_pct": 100}],
    }
    report = validate_setup(setup, current_zone="premium")
    assert any(i.code == "BUY_IN_PREMIUM" for i in report.issues)


# ─── TP progression ───

def test_tp_not_progressive_critical():
    setup = {
        "direction": "buy", "entries": [4520.0], "avg_entry": 4520.0,
        "stop_loss": 4500.0,
        "take_profits": [
            {"level": 4540.0, "close_pct": 50},
            {"level": 4530.0, "close_pct": 50},  # less than TP1 — wrong
        ],
    }
    report = validate_setup(setup)
    assert report.is_rejected
    assert any(i.code == "TP_NOT_PROGRESSIVE" for i in report.issues)


# ─── Liquidity proximity ───

def test_sl_near_ssl_zone():
    setup = {
        "direction": "buy", "entries": [4520.0], "avg_entry": 4520.0,
        "stop_loss": 4501.0,  # right next to SSL
        "take_profits": [{"level": 4540.0, "close_pct": 100}],
    }
    report = validate_setup(
        setup, atr=10.0,
        liquidity_zones=[{"price": 4500.0, "kind": "SSL"}],
    )
    assert any(i.code == "SL_NEAR_LIQUIDITY_SSL" for i in report.issues)


# ─── Losing-pattern rejection ───

def test_blocks_setup_matching_losing_pattern():
    setup = {
        "direction": "buy", "entries": [4520.0], "avg_entry": 4520.0,
        "stop_loss": 4500.0,
        "take_profits": [{"level": 4525.0, "close_pct": 100}],
        "risk_reward": "1:0.25",
    }
    losing = [{"features": {"direction": "buy", "zone": "premium", "rr_band": "low"},
               "win_rate": 0.2, "sample_size": 12}]
    report = validate_setup(
        setup, current_zone="premium",
        losing_patterns=losing,
    )
    assert report.is_rejected
    assert any(i.code == "MATCHES_LOSING_PATTERN" for i in report.issues)


# ─── Result-level integration ───

def test_validate_analysis_drops_rejected():
    result = {
        "chart_meta": {"current_price": 4520.0},
        "session_bias": {"primary_bias": "bullish"},
        "premium_discount": {"current_zone": "discount"},
        "setups": [
            {  # Clean
                "direction": "buy", "entries": [4520.0], "avg_entry": 4520.0,
                "stop_loss": 4500.0,
                "take_profits": [{"level": 4540.0, "close_pct": 100}],
                "risk_reward": "1:1",
            },
            {  # Bad — inverted SL
                "direction": "buy", "entries": [4520.0], "avg_entry": 4520.0,
                "stop_loss": 4530.0,
                "take_profits": [{"level": 4540.0, "close_pct": 100}],
            },
        ],
    }
    out = validate_analysis_result(result)
    assert out["validation_summary"]["kept"] == 1
    assert out["validation_summary"]["rejected"] == 1
    assert len(out["setups"]) == 1
    assert len(out["rejected_setups"]) == 1

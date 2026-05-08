"""Tests for the learning loop pattern miner."""

import pytest
from datetime import datetime, timedelta

from app.training.learning_loop import (
    _rr_band, _extract_features, _signature_key, mine_patterns,
    get_active_winning_patterns, get_active_losing_patterns,
    format_winning_insights_for_prompt,
)
from app.models.analysis import Analysis
from app.models.analysis_outcome import AnalysisOutcome


def test_rr_band():
    assert _rr_band("1:1") == "low"
    assert _rr_band("1:2") == "mid"
    assert _rr_band("1:3") == "high"
    assert _rr_band(None) == "unknown"


def test_signature_key_consistency():
    f1 = {"direction": "buy", "zone": "discount", "rr_band": "high"}
    f2 = {"direction": "buy", "zone": "discount", "rr_band": "high", "extra": "ignored"}
    k1 = _signature_key(f1, ["direction", "zone"])
    k2 = _signature_key(f2, ["direction", "zone"])
    assert k1 == k2


def test_extract_features():
    a = Analysis(
        timeframe="H1", is_mtf=False,
        result_json={
            "session_bias": {"primary_bias": "bullish"},
            "premium_discount": {"current_zone": "discount"},
            "setups": [{
                "direction": "buy", "risk_reward": "1:2",
            }],
        },
        model_used="claude-opus-4-7",
    )
    feats = _extract_features(a, 0)
    assert feats["direction"] == "buy"
    assert feats["zone"] == "discount"
    assert feats["htf_bias"] == "bullish"
    assert feats["rr_band"] == "mid"
    assert feats["timeframe"] == "H1"


@pytest.mark.asyncio
async def test_mine_patterns_with_no_data(db_session):
    """Empty DB should return mined: False."""
    result = await mine_patterns(db_session)
    assert result["mined"] is False


@pytest.mark.asyncio
async def test_mine_patterns_finds_winning_cluster(db_session):
    """Seed 8 buy/discount/bullish wins → should be classified as winning pattern."""
    base_dt = datetime(2026, 4, 1)

    # Seed 8 winning trades all with same features
    for i in range(8):
        a = Analysis(
            id=f"a-w-{i}", timeframe="H1", is_mtf=False, source="test",
            chart_price=4520.0, model_used="claude-opus-4-7", status="completed",
            result_json={
                "session_bias": {"primary_bias": "bullish"},
                "premium_discount": {"current_zone": "discount"},
                "setups": [{
                    "direction": "buy", "risk_reward": "1:2",
                    "entries": [4520.0], "avg_entry": 4520.0,
                    "stop_loss": 4500.0,
                    "take_profits": [{"level": 4540.0, "close_pct": 100}],
                }],
            },
        )
        db_session.add(a)
        await db_session.flush()

        outcome = AnalysisOutcome(
            id=f"o-w-{i}", analysis_id=a.id, setup_index=0,
            direction="buy", entry_price=4520.0, stop_loss=4500.0,
            chart_price_at_creation=4520.0, expected_rr="1:2",
            is_active=False, entry_filled=True, status="tp_full",
            realized_rr=2.0, sl_hit=False, tp1_hit=True,
            created_at=base_dt + timedelta(days=i),
        )
        db_session.add(outcome)

    # Add 2 losing trades with different features (won't form a losing pattern alone)
    for i in range(2):
        a = Analysis(
            id=f"a-l-{i}", timeframe="H4", is_mtf=False, source="test",
            chart_price=4520.0, model_used="claude-opus-4-7", status="completed",
            result_json={
                "session_bias": {"primary_bias": "bearish"},
                "premium_discount": {"current_zone": "premium"},
                "setups": [{
                    "direction": "buy", "risk_reward": "1:1",
                    "entries": [4520.0], "avg_entry": 4520.0, "stop_loss": 4500.0,
                    "take_profits": [{"level": 4540.0, "close_pct": 100}],
                }],
            },
        )
        db_session.add(a)
        await db_session.flush()
        db_session.add(AnalysisOutcome(
            id=f"o-l-{i}", analysis_id=a.id, setup_index=0,
            direction="buy", entry_price=4520.0, stop_loss=4500.0,
            chart_price_at_creation=4520.0,
            is_active=False, entry_filled=True, status="sl_hit",
            realized_rr=-1.0, sl_hit=True,
            created_at=base_dt + timedelta(days=20 + i),
        ))
    await db_session.flush()

    result = await mine_patterns(db_session, min_samples=5,
                                  win_threshold=0.65, loss_threshold=0.35)

    assert result["mined"] is True
    assert result["samples"] == 10
    assert result["winning_count"] >= 1

    # Verify the winning pattern matches the buy/discount/bullish/mid features
    winners = await get_active_winning_patterns(db_session, limit=10)
    assert len(winners) >= 1
    found_match = any(
        w.features.get("direction") == "buy" and
        w.features.get("zone") == "discount"
        for w in winners
    )
    assert found_match, f"Expected to find buy+discount winning pattern, got: {[w.features for w in winners]}"


@pytest.mark.asyncio
async def test_mine_patterns_finds_losing_cluster(db_session):
    """Seed 7 sell/premium/bullish losses → losing pattern."""
    base_dt = datetime(2026, 3, 1)
    for i in range(7):
        a = Analysis(
            id=f"a-loss-{i}", timeframe="H1", is_mtf=False, source="test",
            chart_price=4520.0, model_used="claude-opus-4-7", status="completed",
            result_json={
                "session_bias": {"primary_bias": "bullish"},
                "premium_discount": {"current_zone": "premium"},
                "setups": [{
                    "direction": "sell", "risk_reward": "1:1",
                    "entries": [4540.0], "avg_entry": 4540.0,
                    "stop_loss": 4560.0,
                    "take_profits": [{"level": 4520.0, "close_pct": 100}],
                }],
            },
        )
        db_session.add(a)
        await db_session.flush()
        db_session.add(AnalysisOutcome(
            id=f"o-loss-{i}", analysis_id=a.id, setup_index=0,
            direction="sell", entry_price=4540.0, stop_loss=4560.0,
            chart_price_at_creation=4540.0,
            is_active=False, entry_filled=True, status="sl_hit",
            realized_rr=-1.0, sl_hit=True,
            created_at=base_dt + timedelta(days=i),
        ))
    await db_session.flush()

    result = await mine_patterns(db_session, min_samples=5,
                                  win_threshold=0.65, loss_threshold=0.35)
    assert result["mined"] is True
    assert result["losing_count"] >= 1

    losing = await get_active_losing_patterns(db_session, limit=10)
    assert len(losing) >= 1
    found = any(
        l["features"].get("direction") == "sell" and
        l["features"].get("zone") == "premium"
        for l in losing
    )
    assert found


@pytest.mark.asyncio
async def test_format_winning_insights_returns_text(db_session):
    """When winning patterns exist, format_winning_insights_for_prompt should return prompt text."""
    from app.models.learned_insight import LearnedInsight

    db_session.add(LearnedInsight(
        kind="winning_pattern",
        features={"direction": "buy", "zone": "discount"},
        sample_size=8, wins=7, losses=1, win_rate=0.875,
        avg_realized_rr=1.8, expectancy=1.5, confidence=0.7,
        summary_ar="✅ نمط رابح: BUY · في discount → 88% win rate على 8 حالات",
        is_active=True,
    ))
    await db_session.flush()

    text, ids = await format_winning_insights_for_prompt(db_session, limit=5)
    assert text is not None
    assert "LEARNED PATTERNS" in text
    assert "rabh" in text.lower() or "رابح" in text
    assert len(ids) >= 1

"""Tests for OHLC engine — pure-python indicators + structure detection.
No network required (we synthesize candles)."""

from datetime import datetime, timedelta
from app.training.ohlc_engine import (
    Candle, _ema, _rsi, _atr, _adx,
    _find_swings, _classify_structure,
    _detect_order_blocks, _detect_fvgs,
    OHLCAnalysis, format_for_prompt,
)


def _candles_from_closes(closes: list, base_dt=None) -> list:
    base = base_dt or datetime(2026, 1, 1, 12, 0)
    return [
        Candle(
            dt=base + timedelta(hours=i),
            open=c - 0.5, close=c, high=c + 1.0, low=c - 1.0, volume=1000,
        )
        for i, c in enumerate(closes)
    ]


# ─── Indicators ───

def test_ema_simple():
    closes = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    ema = _ema(closes, 5)
    assert ema is not None
    assert 14 < ema < 19


def test_ema_short_input_returns_none():
    assert _ema([1, 2, 3], 5) is None


def test_rsi_uptrend_high():
    closes = list(range(40, 80))  # straight up
    rsi = _rsi(closes, 14)
    assert rsi is not None
    assert rsi > 70  # overbought


def test_rsi_downtrend_low():
    closes = list(range(80, 40, -1))
    rsi = _rsi(closes, 14)
    assert rsi is not None
    assert rsi < 30  # oversold


def test_atr_basic():
    candles = _candles_from_closes([100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
                                     110, 111, 112, 113, 114, 115])
    atr = _atr(candles, 14)
    assert atr is not None
    assert atr > 0


# ─── Swings + structure ───

def test_find_swings_basic_zigzag():
    # Create a zig-zag pattern: up-down-up-down
    closes = [100, 102, 104, 106, 108, 105, 102, 100, 102, 105, 108, 110, 107, 104, 102, 105]
    candles = _candles_from_closes(closes)
    swings = _find_swings(candles, lookback=2)
    assert len(swings) >= 2  # should detect at least a couple of pivots


def test_classify_structure_uptrend():
    swings_data = [
        ("HL", 100), ("HH", 105), ("HL", 102), ("HH", 110), ("HL", 107), ("HH", 115),
    ]
    from app.training.ohlc_engine import Swing
    base = datetime(2026, 1, 1)
    swings = [Swing(idx=i, price=p, kind=k, dt=base + timedelta(hours=i)) for i, (k, p) in enumerate(swings_data)]
    trend, structure, strength = _classify_structure(swings)
    assert trend == "bullish"
    assert structure == "uptrend"
    assert strength > 0


def test_classify_structure_downtrend():
    from app.training.ohlc_engine import Swing
    base = datetime(2026, 1, 1)
    data = [("LH", 110), ("LL", 105), ("LH", 107), ("LL", 100), ("LH", 102), ("LL", 95)]
    swings = [Swing(idx=i, price=p, kind=k, dt=base + timedelta(hours=i)) for i, (k, p) in enumerate(data)]
    trend, structure, _ = _classify_structure(swings)
    assert trend == "bearish"
    assert structure == "downtrend"


def test_classify_structure_ranging_with_few_swings():
    trend, structure, _ = _classify_structure([])
    assert trend == "ranging"
    assert structure == "consolidation"


# ─── Order blocks + FVGs ───

def test_detect_order_blocks_with_strong_impulse():
    """OB = last opposite-color candle before strong impulse.
    We craft candles directly to ensure clear bearish-then-bullish pattern."""
    from app.training.ohlc_engine import Candle
    base = datetime(2026, 1, 1, 12, 0)
    candles = []
    # Sideways with bearish closes
    for i in range(10):
        candles.append(Candle(
            dt=base + timedelta(hours=i),
            open=100.5, close=99.5, high=101.0, low=99.0, volume=1000,
        ))
    # Now strong bullish impulse: each candle closes 5 points higher
    for i in range(4):
        candles.append(Candle(
            dt=base + timedelta(hours=10 + i),
            open=100 + i * 5, close=105 + i * 5,
            high=106 + i * 5, low=99 + i * 5, volume=1000,
        ))
    obs = _detect_order_blocks(candles, lookback=14, min_move_atr=0.5, atr=3.0)
    # The bearish candle right before impulse should become a bullish OB
    assert any(ob.direction == "bullish" for ob in obs)


def test_detect_fvgs_basic():
    # Create a clear bullish FVG: candle N-1 high < candle N+1 low
    candles = _candles_from_closes([100, 101, 102])
    # Customize manually
    candles[0].high = 100.0
    candles[0].low = 99.0
    candles[1].high = 105.0
    candles[1].low = 102.0
    candles[2].high = 108.0
    candles[2].low = 103.0  # > candles[0].high (100) → bullish FVG
    fvgs = _detect_fvgs(candles, lookback=10)
    assert any(f.direction == "bullish" for f in fvgs)


# ─── Format for prompt ───

def test_format_for_prompt_contains_key_sections():
    a = OHLCAnalysis(
        symbol="XAUUSD", timeframe="H1",
        n_candles=300, last_close=4520.5, last_dt=datetime(2026, 5, 1),
        ema_20=4515.0, ema_50=4500.0, ema_200=4480.0,
        rsi_14=62.5, atr_14=12.3, adx_14=28.5,
        trend="bullish", trend_strength=0.7, structure="uptrend",
        range_high=4550.0, range_low=4480.0, range_mid=4515.0,
        current_zone="equilibrium", pct_in_range=58.2,
        nearest_resistance=4540.0, nearest_support=4495.0,
        vol_regime="normal",
    )
    text = format_for_prompt(a)
    assert "OBJECTIVE PRE-ANALYSIS" in text
    assert "bullish" in text.lower()
    assert "EMA20=4515" in text
    assert "RSI(14)" in text
    assert "ATR(14)" in text
    assert "EQUILIBRIUM" in text
    assert "4540" in text  # resistance

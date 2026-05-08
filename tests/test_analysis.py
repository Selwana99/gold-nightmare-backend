"""Tests for analyzer image prep + cost estimation + schemas."""

import io

import pytest
from PIL import Image

from app.core.analyzer import prepare_image, estimate_cost
from app.schemas.analysis import AnalysisResult, ChartMeta, Setup, TakeProfit


def _make_png(w=600, h=400, color=(50, 50, 50)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_prepare_image_normal():
    img_bytes = _make_png(800, 600)
    data, media_type, sha = prepare_image(img_bytes)
    assert data
    assert media_type in ("image/png", "image/jpeg")
    assert sha


def test_prepare_image_resizes_oversized():
    img_bytes = _make_png(3000, 2000)
    data, media_type, sha = prepare_image(img_bytes)
    assert data


def test_prepare_image_invalid_raises():
    with pytest.raises(Exception):
        prepare_image(b"not an image")


def test_cost_estimation():
    cost = estimate_cost("claude-opus-4-7", 1000, 500)
    assert cost > 0
    assert isinstance(cost, float)


def test_analysis_result_schema_minimal():
    data = {
        "chart_meta": {"timeframe": "H1", "trend_direction": "bullish"},
        "structure_read": {"summary_ar": "Test"},
        "liquidity": {"bsl": [], "ssl": [], "swept_recently_ar": []},
        "premium_discount": {
            "range_high": 4500.0, "range_low": 4400.0,
            "midpoint": 4450.0, "current_zone": "equilibrium",
        },
        "session_bias": {"primary_bias": "bullish"},
    }
    result = AnalysisResult(**data)
    assert result.chart_meta.timeframe == "H1"


def test_analysis_result_with_setup():
    setup = Setup(
        label="A - BUY", direction="buy",
        trigger_ar="Test trigger",
        entries=[4520.0], stop_loss=4500.0,
        take_profits=[TakeProfit(level=4540.0, close_pct=100)],
        rationale_ar="Test", invalidation_ar="Below SL",
    )
    assert setup.label == "A - BUY"
    assert len(setup.take_profits) == 1

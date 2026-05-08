"""Tests for ML classifier feature extraction (no heavy deps required)."""

from app.training.pattern_classifier import _parse_rr, _extract_features


class _MockAnalysis:
    """Tiny stand-in matching the attributes _extract_features reads."""
    def __init__(self, **kw):
        self.id = "test"
        self.timeframe = "H1"
        self.chart_price = 4520.0
        self.is_mtf = False
        self.result_json = {
            "premium_discount": {"current_zone": "discount"},
            "session_bias": {"primary_bias": "bearish"},
        }
        for k, v in kw.items():
            setattr(self, k, v)


def test_parse_rr_standard():
    assert _parse_rr("1:1.5") == 1.5
    assert _parse_rr("1:3") == 3.0
    assert _parse_rr("2:6") == 3.0
    assert _parse_rr(None) == 0.0
    assert _parse_rr("") == 0.0


def test_extract_features_buy_setup():
    analysis = _MockAnalysis()
    setup = {
        "direction": "buy",
        "entries": [4515.0],
        "avg_entry": 4515.0,
        "stop_loss": 4500.0,
        "take_profits": [{"level": 4540.0}, {"level": 4560.0}],
        "risk_reward": "1:2",
    }
    feats = _extract_features(analysis, setup)
    assert feats is not None
    assert feats["direction_buy"] == 1
    assert feats["rr"] == 2.0
    assert feats["is_discount"] == 1
    assert feats["is_premium"] == 0
    assert feats["tf_H1"] == 1
    assert feats["n_tps"] == 2
    assert feats["is_split_entry"] == 0
    # Bearish bias + buy setup → not aligned
    assert feats["bias_aligned"] == 0


def test_extract_features_aligned_sell():
    analysis = _MockAnalysis()  # bearish bias
    setup = {
        "direction": "sell",
        "entries": [4540.0, 4552.0],
        "avg_entry": 4546.0,
        "stop_loss": 4566.0,
        "take_profits": [
            {"level": 4520.0}, {"level": 4500.0}, {"level": 4480.0},
        ],
        "risk_reward": "1:2.5",
    }
    feats = _extract_features(analysis, setup)
    assert feats["direction_buy"] == 0
    assert feats["rr"] == 2.5
    assert feats["is_split_entry"] == 1
    assert feats["bias_aligned"] == 1  # bearish + sell
    assert feats["n_tps"] == 3


def test_extract_features_invalid_returns_none():
    analysis = _MockAnalysis(chart_price=0)
    setup = {"direction": "buy", "entries": [], "stop_loss": None}
    feats = _extract_features(analysis, setup)
    assert feats is None


def test_extract_features_complete_feature_set():
    """Sanity: all 16 features Claude expects are present."""
    analysis = _MockAnalysis()
    setup = {
        "direction": "buy", "entries": [4515.0], "avg_entry": 4515.0,
        "stop_loss": 4500.0, "take_profits": [{"level": 4540.0}],
        "risk_reward": "1:1.5",
    }
    feats = _extract_features(analysis, setup)
    expected = {
        "direction_buy", "rr", "entry_distance_pct", "risk_pct",
        "is_premium", "is_discount", "is_equilibrium",
        "tf_M15", "tf_H1", "tf_H4", "tf_D1",
        "is_mtf", "bias_aligned", "n_tps", "is_split_entry",
    }
    assert expected.issubset(set(feats.keys()))

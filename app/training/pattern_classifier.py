"""
Pattern classifier — trains an XGBoost model on historical analyses with
confirmed outcomes, to provide a second-opinion probability that any
new setup will succeed.

Features extracted from each setup:
  - Direction (1=buy, 0=sell)
  - R:R (parsed)
  - Distance to entry (chart_price → entry %)
  - Distance to SL (% from entry)
  - Premium/discount zone (one-hot)
  - Timeframe (one-hot)
  - HTF/LTF alignment indicator
  - Number of TPs

Target: outcome.status == "tp_full" → 1, else 0
"""

import json
import logging
import pickle
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import Analysis
from app.models.analysis_outcome import AnalysisOutcome

logger = logging.getLogger(__name__)

MODEL_PATH = Path("./data/ml_classifier.pkl")
MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)


def _parse_rr(rr_str: Optional[str]) -> float:
    """Extract numeric R:R from strings like '1:1.5' or '1:2.7'."""
    if not rr_str:
        return 0.0
    try:
        parts = rr_str.replace("→", ":").replace("..", ":").split(":")
        nums = [float(p.strip()) for p in parts if p.strip().replace(".", "").isdigit()]
        if len(nums) >= 2:
            return nums[1] / nums[0]
        return 0.0
    except Exception:
        return 0.0


def _extract_features(analysis: Analysis, setup: dict) -> Optional[dict]:
    """Build feature dict for a single setup."""
    if not setup:
        return None
    result = analysis.result_json or {}
    pd = result.get("premium_discount", {})
    bias = result.get("session_bias", {})

    direction = 1 if setup.get("direction") == "buy" else 0
    rr = _parse_rr(setup.get("risk_reward"))
    avg_entry = setup.get("avg_entry") or 0
    sl = setup.get("stop_loss") or 0
    chart_price = analysis.chart_price or 0
    if not all([avg_entry, sl, chart_price]):
        return None

    entry_distance_pct = abs(chart_price - avg_entry) / chart_price * 100 if chart_price else 0
    risk_pct = abs(avg_entry - sl) / avg_entry * 100 if avg_entry else 0

    zone = pd.get("current_zone", "equilibrium")
    primary_bias = bias.get("primary_bias", "neutral")

    tf_norm = (analysis.timeframe or "").upper()
    setup_dir = setup.get("direction", "")
    bias_aligned = 1 if (
        (primary_bias == "bullish" and setup_dir == "buy") or
        (primary_bias == "bearish" and setup_dir == "sell")
    ) else 0

    return {
        "direction_buy": direction,
        "rr": rr,
        "entry_distance_pct": entry_distance_pct,
        "risk_pct": risk_pct,
        "is_premium": int(zone == "premium"),
        "is_discount": int(zone == "discount"),
        "is_equilibrium": int(zone == "equilibrium"),
        "tf_M15": int(tf_norm == "M15"),
        "tf_H1": int(tf_norm == "H1"),
        "tf_H4": int(tf_norm == "H4"),
        "tf_D1": int(tf_norm == "D1"),
        "is_mtf": int(analysis.is_mtf),
        "bias_aligned": bias_aligned,
        "n_tps": len(setup.get("take_profits", [])),
        "is_split_entry": int(len(setup.get("entries", [])) > 1),
    }


async def build_training_dataset(db: AsyncSession) -> Tuple[list, list, list]:
    """
    Returns (X_features, y_labels, feature_names).
    Only uses outcomes that closed (tp_full or sl_hit).
    """
    result = await db.execute(
        select(AnalysisOutcome, Analysis)
        .join(Analysis, AnalysisOutcome.analysis_id == Analysis.id)
        .where(and_(
            AnalysisOutcome.is_active.is_(False),
            AnalysisOutcome.status.in_(["tp_full", "sl_hit"]),
        ))
    )
    rows = result.all()

    X = []
    y = []
    feature_names = []

    for outcome, analysis in rows:
        setups = (analysis.result_json or {}).get("setups", [])
        if outcome.setup_index >= len(setups):
            continue
        setup = setups[outcome.setup_index]
        feats = _extract_features(analysis, setup)
        if not feats:
            continue
        if not feature_names:
            feature_names = list(feats.keys())
        X.append([feats[k] for k in feature_names])
        y.append(1 if outcome.status == "tp_full" else 0)

    return X, y, feature_names


async def train_classifier(db: AsyncSession, min_samples: int = 30) -> dict:
    """
    Train XGBoost classifier on closed outcomes.
    Returns metadata about the trained model.
    """
    X, y, feature_names = await build_training_dataset(db)

    if len(X) < min_samples:
        return {
            "trained": False,
            "reason": f"Not enough samples (have {len(X)}, need {min_samples})",
            "samples": len(X),
        }

    try:
        import numpy as np
        from sklearn.model_selection import cross_val_score, train_test_split
        from sklearn.metrics import accuracy_score, roc_auc_score
        import xgboost as xgb
    except ImportError as e:
        return {"trained": False, "reason": f"ML libs not installed: {e}"}

    X_arr = np.array(X, dtype=float)
    y_arr = np.array(y, dtype=int)

    X_train, X_test, y_train, y_test = train_test_split(
        X_arr, y_arr, test_size=0.2, random_state=42, stratify=y_arr if len(set(y)) > 1 else None,
    )

    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        objective="binary:logistic",
        eval_metric="logloss",
        random_state=42,
        use_label_encoder=False,
    )
    model.fit(X_train, y_train)

    train_acc = accuracy_score(y_train, model.predict(X_train))
    test_acc = accuracy_score(y_test, model.predict(X_test))
    try:
        test_auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
    except ValueError:
        test_auc = None

    # Feature importance
    importances = dict(zip(feature_names, model.feature_importances_.tolist()))

    # Save
    save_data = {
        "model": model,
        "feature_names": feature_names,
        "trained_at": datetime.utcnow().isoformat(),
        "samples": len(X),
        "train_acc": float(train_acc),
        "test_acc": float(test_acc),
        "test_auc": float(test_auc) if test_auc is not None else None,
        "importances": importances,
        "class_balance": {"win": int(y_arr.sum()), "loss": int((1 - y_arr).sum())},
    }
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(save_data, f)

    logger.info("Classifier trained: %d samples, train_acc=%.3f, test_acc=%.3f", len(X), train_acc, test_acc)
    return {
        "trained": True,
        "samples": len(X),
        "train_accuracy": float(train_acc),
        "test_accuracy": float(test_acc),
        "test_auc": float(test_auc) if test_auc is not None else None,
        "importances": importances,
        "class_balance": save_data["class_balance"],
    }


def load_classifier() -> Optional[dict]:
    if not MODEL_PATH.exists():
        return None
    try:
        with open(MODEL_PATH, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning("Failed to load classifier: %s", e)
        return None


def predict_setup_quality(analysis: Analysis, setup: dict) -> Optional[float]:
    """
    Returns probability (0-1) that this setup will hit full TP.
    None if no model trained yet.
    """
    saved = load_classifier()
    if not saved:
        return None
    feats = _extract_features(analysis, setup)
    if not feats:
        return None
    feature_names = saved["feature_names"]
    x = [[feats.get(k, 0.0) for k in feature_names]]
    try:
        proba = saved["model"].predict_proba(x)[0][1]
        return float(proba)
    except Exception as e:
        logger.warning("Prediction failed: %s", e)
        return None


def get_classifier_info() -> dict:
    saved = load_classifier()
    if not saved:
        return {"trained": False}
    return {
        "trained": True,
        "trained_at": saved.get("trained_at"),
        "samples": saved.get("samples"),
        "train_accuracy": saved.get("train_acc"),
        "test_accuracy": saved.get("test_acc"),
        "test_auc": saved.get("test_auc"),
        "importances": saved.get("importances", {}),
        "class_balance": saved.get("class_balance", {}),
    }

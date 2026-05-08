#!/usr/bin/env python3
"""
Train the ML pattern classifier on closed outcomes.

Usage:
    python -m scripts.train_classifier
    python -m scripts.train_classifier --min-samples 50
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import AsyncSessionLocal, init_db
from app.training.pattern_classifier import train_classifier, get_classifier_info


async def main():
    parser = argparse.ArgumentParser(description="Train ML pattern classifier")
    parser.add_argument("--min-samples", type=int, default=30,
                        help="Minimum samples required to train (default: 30)")
    parser.add_argument("--info", action="store_true",
                        help="Just show current classifier info")
    args = parser.parse_args()

    if args.info:
        info = get_classifier_info()
        if not info.get("trained"):
            print("⏳ Classifier not yet trained")
            return
        print(f"✓ Trained at: {info.get('trained_at')}")
        print(f"  Samples: {info.get('samples')}")
        print(f"  Train accuracy: {info.get('train_accuracy', 0)*100:.1f}%")
        print(f"  Test accuracy: {info.get('test_accuracy', 0)*100:.1f}%")
        if info.get("test_auc") is not None:
            print(f"  Test AUC: {info['test_auc']:.3f}")
        print(f"  Class balance: {info.get('class_balance', {})}")
        print("  Top features:")
        imp = info.get("importances", {})
        for f, v in sorted(imp.items(), key=lambda x: x[1], reverse=True)[:8]:
            print(f"    {f:<25} {v*100:>6.2f}%")
        return

    await init_db()
    async with AsyncSessionLocal() as db:
        result = await train_classifier(db, min_samples=args.min_samples)

    if result.get("trained"):
        print(f"✓ Classifier trained on {result['samples']} samples")
        print(f"  Train accuracy: {result['train_accuracy']*100:.1f}%")
        print(f"  Test accuracy:  {result['test_accuracy']*100:.1f}%")
        if result.get("test_auc"):
            print(f"  Test AUC:       {result['test_auc']:.3f}")
        print(f"  Class balance: {result.get('class_balance', {})}")
    else:
        print(f"✗ Training skipped: {result.get('reason')}")


if __name__ == "__main__":
    asyncio.run(main())

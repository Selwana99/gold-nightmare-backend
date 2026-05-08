#!/usr/bin/env python3
"""
Export training datasets (JSONL/CSV) from the database.

Usage:
    python -m scripts.export_dataset --type quality --out ./data/exports/quality.jsonl
    python -m scripts.export_dataset --type training --limit 5000
    python -m scripts.export_dataset --type csv --out ./data/exports/outcomes.csv
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import AsyncSessionLocal, init_db
from app.training.dataset_builder import (
    export_quality_examples, export_training_jsonl, export_outcomes_csv,
)


async def main():
    parser = argparse.ArgumentParser(description="Export training dataset")
    parser.add_argument("--type", choices=["quality", "training", "csv"], required=True)
    parser.add_argument("--out", default=None, help="Output path (default: auto-named in ./data/exports/)")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--min-rr", type=float, default=1.5, help="(quality only)")
    parser.add_argument("--min-rating", type=int, default=4, help="(quality only)")
    args = parser.parse_args()

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    if not args.out:
        ext = "csv" if args.type == "csv" else "jsonl"
        args.out = f"./data/exports/{args.type}_{timestamp}.{ext}"

    await init_db()
    async with AsyncSessionLocal() as db:
        if args.type == "quality":
            r = await export_quality_examples(db, args.out, args.min_rr, args.min_rating)
        elif args.type == "training":
            r = await export_training_jsonl(db, args.out, args.limit)
        else:
            r = await export_outcomes_csv(db, args.out)

    print(f"✓ Exported {r['exported_count']} records to {r['output_path']}")
    if "via_outcome" in r:
        print(f"  via outcomes: {r['via_outcome']}, via feedback: {r['via_feedback']}")


if __name__ == "__main__":
    asyncio.run(main())

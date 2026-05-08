#!/usr/bin/env python3
"""
Bulk-promote past successful analyses to the few-shot example bank.

Usage:
    python -m scripts.seed_few_shot --min-rr 1.5
    python -m scripts.seed_few_shot --max 50 --rebuild-index
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, and_

from app.db.base import AsyncSessionLocal, init_db
from app.models.analysis import Analysis
from app.models.analysis_outcome import AnalysisOutcome
from app.models.few_shot_example import FewShotExample
from app.training.few_shot import (
    promote_analysis_to_example, add_to_index, get_index_stats,
)


async def main():
    parser = argparse.ArgumentParser(description="Seed few-shot example bank")
    parser.add_argument("--min-rr", type=float, default=1.5)
    parser.add_argument("--max", type=int, default=100, help="Max examples to add")
    parser.add_argument("--rebuild-index", action="store_true",
                        help="Re-embed all existing examples")
    args = parser.parse_args()

    await init_db()
    async with AsyncSessionLocal() as db:
        if args.rebuild_index:
            print("Re-building vector index for existing examples...")
            existing = (await db.execute(
                select(FewShotExample).where(FewShotExample.is_active.is_(True))
            )).scalars().all()
            for ex in existing:
                ok = await add_to_index(db, ex, force_re_embed=True)
                print(f"  {ex.id[:8]}... {'✓' if ok else '✗'}")
            await db.commit()

        # Find successful outcomes not yet promoted
        result = await db.execute(
            select(AnalysisOutcome, Analysis)
            .join(Analysis, AnalysisOutcome.analysis_id == Analysis.id)
            .where(and_(
                AnalysisOutcome.status == "tp_full",
                AnalysisOutcome.realized_rr >= args.min_rr,
            ))
            .limit(args.max)
        )
        rows = result.all()

        promoted = 0
        skipped = 0
        for outcome, analysis in rows:
            existing = await db.execute(
                select(FewShotExample).where(FewShotExample.source_analysis_id == analysis.id)
            )
            if existing.scalar_one_or_none():
                skipped += 1
                continue
            try:
                await promote_analysis_to_example(
                    db, analysis,
                    realized_rr=outcome.realized_rr,
                    quality_score=min(10.0, 5.0 + outcome.realized_rr),
                )
                promoted += 1
                print(f"  ✓ {analysis.id[:8]}... R:R={outcome.realized_rr:.2f}")
            except Exception as e:
                print(f"  ✗ {analysis.id[:8]}... {e}")

        await db.commit()

        stats = get_index_stats()
        print(f"\n✓ Promoted: {promoted}, Skipped (already): {skipped}")
        print(f"  Vector store: {stats}")


if __name__ == "__main__":
    asyncio.run(main())

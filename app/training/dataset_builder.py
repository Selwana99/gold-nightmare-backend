"""
Training dataset builder — exports historical analyses (with confirmed outcomes)
as JSONL ready for fine-tuning or analysis.

Two output modes:
  1. "examples"  → high-quality analyses suitable as few-shot prompts
  2. "training"  → JSONL pairs (input, target) for fine-tuning workflows
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import Analysis
from app.models.analysis_outcome import AnalysisOutcome
from app.models.feedback import Feedback

logger = logging.getLogger(__name__)


async def export_quality_examples(
    db: AsyncSession,
    output_path: str,
    min_realized_rr: float = 1.5,
    min_quality_rating: int = 4,
) -> dict:
    """
    Export analyses that:
      - Have at least one outcome that hit full TP with R:R >= min_realized_rr
      - OR have user feedback rating >= min_quality_rating
    """
    # Successful outcomes
    result = await db.execute(
        select(AnalysisOutcome, Analysis)
        .join(Analysis, AnalysisOutcome.analysis_id == Analysis.id)
        .where(and_(
            AnalysisOutcome.status == "tp_full",
            AnalysisOutcome.realized_rr >= min_realized_rr,
        ))
    )
    quality_via_outcome = result.all()

    # Quality via feedback
    result2 = await db.execute(
        select(Feedback, Analysis)
        .join(Analysis, Feedback.analysis_id == Analysis.id)
        .where(Feedback.accuracy_rating >= min_quality_rating)
    )
    quality_via_feedback = result2.all()

    seen_ids = set()
    output_lines = []

    for outcome, analysis in quality_via_outcome:
        if analysis.id in seen_ids:
            continue
        seen_ids.add(analysis.id)
        line = {
            "analysis_id": analysis.id,
            "symbol": analysis.symbol,
            "timeframe": analysis.timeframe,
            "is_mtf": analysis.is_mtf,
            "result": analysis.result_json,
            "quality_signal": "outcome",
            "realized_rr": float(outcome.realized_rr) if outcome.realized_rr else None,
            "created_at": analysis.created_at.isoformat(),
        }
        output_lines.append(line)

    for feedback, analysis in quality_via_feedback:
        if analysis.id in seen_ids:
            continue
        seen_ids.add(analysis.id)
        line = {
            "analysis_id": analysis.id,
            "symbol": analysis.symbol,
            "timeframe": analysis.timeframe,
            "is_mtf": analysis.is_mtf,
            "result": analysis.result_json,
            "quality_signal": "feedback",
            "feedback_rating": feedback.accuracy_rating,
            "created_at": analysis.created_at.isoformat(),
        }
        output_lines.append(line)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for line in output_lines:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")

    logger.info("Exported %d quality examples to %s", len(output_lines), out)
    return {
        "exported_count": len(output_lines),
        "output_path": str(out),
        "via_outcome": len(quality_via_outcome),
        "via_feedback": len(quality_via_feedback),
    }


async def export_training_jsonl(db: AsyncSession, output_path: str, limit: int = 1000) -> dict:
    """
    Export ALL closed analyses (with outcomes) as a training JSONL file.
    Format compatible with most fine-tuning pipelines.
    """
    result = await db.execute(
        select(Analysis, AnalysisOutcome)
        .join(AnalysisOutcome, AnalysisOutcome.analysis_id == Analysis.id)
        .where(AnalysisOutcome.is_active.is_(False))
        .limit(limit)
    )
    rows = result.all()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(out, "w", encoding="utf-8") as f:
        for analysis, outcome in rows:
            entry = {
                "messages": [
                    {
                        "role": "user",
                        "content": f"Analyze this {analysis.symbol} {analysis.timeframe} chart. "
                                   f"Context: {analysis.user_context or 'N/A'}",
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(analysis.result_json, ensure_ascii=False),
                    },
                ],
                "metadata": {
                    "analysis_id": analysis.id,
                    "outcome_status": outcome.status,
                    "realized_rr": float(outcome.realized_rr) if outcome.realized_rr is not None else None,
                    "is_mtf": analysis.is_mtf,
                    "model_used": analysis.model_used,
                    "image_hashes": analysis.image_hashes,
                },
            }
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            count += 1

    logger.info("Exported %d training examples to %s", count, out)
    return {"exported_count": count, "output_path": str(out)}


async def export_outcomes_csv(db: AsyncSession, output_path: str) -> dict:
    """Export all outcomes as CSV for analysis in pandas/Excel."""
    import csv
    result = await db.execute(select(AnalysisOutcome))
    outcomes = result.scalars().all()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "analysis_id", "setup_index", "setup_label", "direction",
            "entry", "sl", "expected_rr", "chart_price",
            "status", "filled", "realized_rr", "realized_pnl_pct",
            "tp1", "tp2", "tp3", "tp4", "sl_hit",
            "max_fav", "max_adv", "created_at", "closed_at",
        ])
        for o in outcomes:
            writer.writerow([
                o.id, o.analysis_id, o.setup_index, o.setup_label, o.direction,
                o.entry_price, o.stop_loss, o.expected_rr, o.chart_price_at_creation,
                o.status, o.entry_filled, o.realized_rr, o.realized_pnl_pct,
                o.tp1_hit, o.tp2_hit, o.tp3_hit, o.tp4_hit, o.sl_hit,
                o.max_favorable_excursion, o.max_adverse_excursion,
                o.created_at, o.closed_at,
            ])

    return {"exported_count": len(outcomes), "output_path": str(out)}

#!/usr/bin/env python3
"""
Run a backtest from the CLI.

Usage:
    python -m scripts.run_backtest --tf H1 --start 2026-01-01 --end 2026-04-30 --samples 30
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.db.base import AsyncSessionLocal, init_db
from app.models.backtest_run import BacktestRun
from app.training.backtest import run_backtest


async def main():
    parser = argparse.ArgumentParser(description="Run a backtest")
    parser.add_argument("--name", default="CLI Backtest")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--tf", default="H1", help="Timeframe (M15/H1/H4/D1)")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--model", default=None, help="Override Claude model")
    args = parser.parse_args()

    if not settings.TWELVEDATA_KEY:
        print("✗ TWELVEDATA_KEY not set in .env — cannot fetch historical data")
        return 1

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    await init_db()
    async with AsyncSessionLocal() as db:
        run = BacktestRun(
            name=args.name,
            symbol=args.symbol,
            timeframe=args.tf,
            start_date=start,
            end_date=end,
            model_used=args.model or settings.CLAUDE_MODEL,
            status="pending",
        )
        db.add(run)
        await db.flush()

        def progress(i, total):
            print(f"  Point {i+1}/{total}")

        try:
            await run_backtest(db, run, sample_size=args.samples, progress_callback=progress)
        except Exception as e:
            print(f"✗ Backtest failed: {e}")
            return 1

        print(f"\n✓ Backtest complete (id={run.id})")
        print(f"  Setups generated: {run.total_setups_generated}")
        print(f"  Setups filled:    {run.total_setups_filled}")
        print(f"  Wins/Losses:      {run.wins}W / {run.losses}L")
        if run.win_rate is not None:
            print(f"  Win rate:         {run.win_rate*100:.1f}%")
        if run.avg_realized_rr is not None:
            print(f"  Avg realized R:R: {run.avg_realized_rr:.2f}")
        if run.total_pnl_R is not None:
            print(f"  Total PnL:        {run.total_pnl_R:+.2f}R")
        print(f"  Cost:             ${run.total_cost_usd or 0:.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)

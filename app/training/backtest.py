"""
Backtest engine — measures how the analyzer would have performed historically.

Strategy:
  1. Pull historical OHLC for symbol/timeframe between dates (TwelveData).
  2. Sample N points evenly across the range.
  3. For each point: render a chart image of the preceding window, run the analyzer.
  4. Forward-walk price after that point and compute outcomes.
  5. Aggregate: win rate, avg R:R, total R, Sharpe-like ratio.
"""

import asyncio
import logging
import io
from datetime import datetime, timedelta
from typing import Optional, List

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.analyzer import analyze_single_chart, AnalyzerError
from app.models.backtest_run import BacktestRun

logger = logging.getLogger(__name__)


# ─── Historical data fetcher ───

async def fetch_historical_ohlc(
    symbol: str = "XAUUSD",
    timeframe: str = "H1",
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = 5000,
) -> List[dict]:
    """
    Fetch historical OHLC data via TwelveData.
    Returns list of {datetime, open, high, low, close, volume}.
    """
    if not settings.TWELVEDATA_KEY:
        raise RuntimeError("TWELVEDATA_KEY not set — cannot fetch historical data")

    interval_map = {
        "M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
        "H1": "1h", "H4": "4h", "D1": "1day", "W1": "1week",
    }
    interval = interval_map.get(timeframe.upper(), "1h")

    # TwelveData uses XAU/USD format
    td_symbol = symbol.replace("USD", "/USD") if "/" not in symbol else symbol

    params = {
        "symbol": td_symbol,
        "interval": interval,
        "apikey": settings.TWELVEDATA_KEY,
        "outputsize": min(limit, 5000),
        "format": "JSON",
        "order": "ASC",
    }
    if start:
        params["start_date"] = start.strftime("%Y-%m-%d %H:%M:%S")
    if end:
        params["end_date"] = end.strftime("%Y-%m-%d %H:%M:%S")

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get("https://api.twelvedata.com/time_series", params=params)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "error":
            raise RuntimeError(f"TwelveData error: {data.get('message')}")
        values = data.get("values", [])
        return [
            {
                "datetime": datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S")
                            if " " in v["datetime"]
                            else datetime.strptime(v["datetime"], "%Y-%m-%d"),
                "open": float(v["open"]),
                "high": float(v["high"]),
                "low": float(v["low"]),
                "close": float(v["close"]),
                "volume": float(v.get("volume", 0)),
            }
            for v in values
        ]


# ─── Chart rendering for backtest ───

def render_candlestick_image(candles: List[dict], symbol: str, timeframe: str) -> bytes:
    """
    Render a candlestick chart from OHLC data as a PNG image.
    Uses matplotlib + mplfinance for accurate chart rendering.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        raise RuntimeError("matplotlib not installed — required for backtests")

    if not candles:
        raise ValueError("No candles provided")

    fig, ax = plt.subplots(figsize=(14, 8), facecolor="#1a1a1a")
    ax.set_facecolor("#1a1a1a")

    width = 0.6
    for i, c in enumerate(candles):
        is_up = c["close"] >= c["open"]
        color = "#26a69a" if is_up else "#ef5350"
        # Wick
        ax.plot([i, i], [c["low"], c["high"]], color=color, linewidth=1, zorder=2)
        # Body
        body_h = abs(c["close"] - c["open"])
        body_y = min(c["close"], c["open"])
        rect = Rectangle((i - width/2, body_y), width, body_h or 0.01,
                         facecolor=color, edgecolor=color, zorder=3)
        ax.add_patch(rect)

    # Axes formatting
    last_close = candles[-1]["close"]
    ax.set_xlim(-1, len(candles))
    y_min = min(c["low"] for c in candles)
    y_max = max(c["high"] for c in candles)
    pad = (y_max - y_min) * 0.05
    ax.set_ylim(y_min - pad, y_max + pad)

    # Title with symbol/TF and current price (mimics MT5)
    ax.text(0.02, 0.97, f"{symbol},{timeframe}", transform=ax.transAxes,
            color="#d4af37", fontsize=14, fontweight="bold", verticalalignment="top")
    ax.text(0.98, 0.95, f"{last_close:.2f}", transform=ax.transAxes,
            color="#ffffff", fontsize=12, ha="right",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#2a2a2a", edgecolor="#d4af37"))

    ax.tick_params(colors="#888888")
    for spine in ax.spines.values():
        spine.set_color("#444444")
    ax.grid(True, alpha=0.15, color="#444444")
    ax.yaxis.tick_right()
    ax.set_xticks([])

    buf = io.BytesIO()
    fig.savefig(buf, format="PNG", bbox_inches="tight", facecolor="#1a1a1a", dpi=100)
    plt.close(fig)
    return buf.getvalue()


# ─── Outcome simulation ───

def simulate_setup_outcome(setup: dict, future_candles: List[dict]) -> dict:
    """
    Walk forward through future candles to determine outcome of a setup.
    Returns: {filled, status, realized_rr, bars_to_outcome}
    """
    direction = setup.get("direction", "buy")
    entries = setup.get("entries", [])
    sl = setup.get("stop_loss")
    tps = setup.get("take_profits", [])
    if not entries or sl is None or not tps:
        return {"filled": False, "status": "invalid", "realized_rr": 0.0, "bars": 0}

    avg_entry = setup.get("avg_entry") or sum(entries) / len(entries)
    final_tp = max(tp.get("level", 0) for tp in tps) if direction == "buy" else min(tp.get("level", 0) for tp in tps)

    risk = abs(avg_entry - sl)
    if risk == 0:
        return {"filled": False, "status": "invalid_zero_risk", "realized_rr": 0.0, "bars": 0}

    filled = False
    fill_bar = -1
    for i, c in enumerate(future_candles):
        if not filled:
            # Check entry fill
            if direction == "buy" and c["low"] <= avg_entry:
                filled = True
                fill_bar = i
            elif direction == "sell" and c["high"] >= avg_entry:
                filled = True
                fill_bar = i

        if filled:
            # Check SL/TP hits
            if direction == "buy":
                if c["low"] <= sl:
                    return {"filled": True, "status": "sl", "realized_rr": -1.0, "bars": i - fill_bar}
                if c["high"] >= final_tp:
                    rr = (final_tp - avg_entry) / risk
                    return {"filled": True, "status": "tp_full", "realized_rr": rr, "bars": i - fill_bar}
            else:  # sell
                if c["high"] >= sl:
                    return {"filled": True, "status": "sl", "realized_rr": -1.0, "bars": i - fill_bar}
                if c["low"] <= final_tp:
                    rr = (avg_entry - final_tp) / risk
                    return {"filled": True, "status": "tp_full", "realized_rr": rr, "bars": i - fill_bar}

    if not filled:
        return {"filled": False, "status": "expired_unfilled", "realized_rr": 0.0, "bars": len(future_candles)}

    # Filled but neither SL nor TP — partial
    last = future_candles[-1]["close"]
    if direction == "buy":
        rr = (last - avg_entry) / risk
    else:
        rr = (avg_entry - last) / risk
    return {"filled": True, "status": "open_at_end", "realized_rr": rr, "bars": len(future_candles) - fill_bar}


# ─── Main backtest runner ───

async def run_backtest(
    db: AsyncSession,
    backtest_run: BacktestRun,
    sample_size: int = 20,
    history_window_bars: int = 100,
    forward_window_bars: int = 100,
    progress_callback=None,
) -> BacktestRun:
    """
    Execute a backtest. Updates backtest_run in-place with results.
    """
    backtest_run.status = "running"
    await db.commit()

    try:
        all_candles = await fetch_historical_ohlc(
            symbol=backtest_run.symbol,
            timeframe=backtest_run.timeframe,
            start=backtest_run.start_date,
            end=backtest_run.end_date,
            limit=5000,
        )
    except Exception as e:
        backtest_run.status = "failed"
        backtest_run.notes = (backtest_run.notes or "") + f"\nFailed to fetch data: {e}"
        await db.commit()
        raise

    if len(all_candles) < history_window_bars + forward_window_bars + 10:
        backtest_run.status = "failed"
        backtest_run.notes = "Not enough historical data"
        await db.commit()
        raise RuntimeError("Not enough candles for backtest")

    # Sample N points
    available = len(all_candles) - history_window_bars - forward_window_bars
    step = max(1, available // sample_size)
    sample_indices = list(range(history_window_bars, history_window_bars + step * sample_size, step))[:sample_size]

    detailed = []
    total_setups = 0
    filled = 0
    wins = 0
    losses = 0
    total_rr = 0.0
    total_input = 0
    total_output = 0
    total_cost = 0.0

    for idx_pos, idx in enumerate(sample_indices):
        if progress_callback:
            progress_callback(idx_pos, sample_size)

        history = all_candles[idx - history_window_bars:idx]
        future = all_candles[idx:idx + forward_window_bars]

        try:
            chart_img = render_candlestick_image(history, backtest_run.symbol, backtest_run.timeframe)
            result = analyze_single_chart(
                chart_img,
                extra_context=f"Backtest point {idx_pos+1}/{sample_size}",
                model=backtest_run.model_used,
            )
        except AnalyzerError as e:
            logger.warning("Backtest point %d failed: %s", idx_pos, e)
            detailed.append({"idx": idx_pos, "error": str(e)})
            continue

        meta = result.pop("_meta", {})
        total_input += meta.get("input_tokens", 0)
        total_output += meta.get("output_tokens", 0)
        total_cost += meta.get("cost_usd", 0.0)

        setups = result.get("setups", [])
        point_result = {
            "idx": idx_pos,
            "datetime": history[-1]["datetime"].isoformat(),
            "current_price": history[-1]["close"],
            "setups": [],
        }

        for setup in setups:
            total_setups += 1
            outcome = simulate_setup_outcome(setup, future)
            point_result["setups"].append({
                "label": setup.get("label"),
                "direction": setup.get("direction"),
                "outcome": outcome,
            })

            if outcome["filled"]:
                filled += 1
                rr = outcome["realized_rr"]
                total_rr += rr
                if outcome["status"] == "tp_full":
                    wins += 1
                elif outcome["status"] == "sl":
                    losses += 1

        detailed.append(point_result)

        # Periodic save
        if idx_pos % 5 == 0:
            backtest_run.detailed_results = detailed
            await db.commit()

    # Finalize
    backtest_run.total_setups_generated = total_setups
    backtest_run.total_setups_filled = filled
    backtest_run.wins = wins
    backtest_run.losses = losses
    backtest_run.win_rate = (wins / (wins + losses)) if (wins + losses) > 0 else None
    backtest_run.avg_realized_rr = (total_rr / filled) if filled > 0 else None
    backtest_run.total_pnl_R = total_rr
    backtest_run.total_input_tokens = total_input
    backtest_run.total_output_tokens = total_output
    backtest_run.total_cost_usd = total_cost
    backtest_run.detailed_results = detailed
    backtest_run.status = "completed"
    backtest_run.completed_at = datetime.utcnow()
    await db.commit()

    logger.info("Backtest %s done: %d setups, %d wins, %d losses, %.2fR total",
                backtest_run.id, total_setups, wins, losses, total_rr)
    return backtest_run

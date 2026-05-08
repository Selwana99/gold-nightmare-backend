"""
Outcome Tracker V2 — candle-based with proper TP/SL sequence detection.

KEY DIFFERENCE FROM V1:
  V1 polled live price. If price hit TP then bounced to SL between polls,
  V1 would only see the SL state and miss the TP entirely. WRONG.

  V2 fetches the actual M5 candles since the recommendation was created.
  For each candle, it checks high/low ranges to determine which level was
  hit FIRST. This gives accurate sequence reconstruction.

Logic per candle (BUY example):
  - If candle.low <= SL AND candle.high >= TP:
      Use candle direction (bullish vs bearish) to guess sequence:
        - Bullish candle (close > open): TP likely hit first
        - Bearish candle (close < open): SL likely hit first
      In ambiguity, prefer SL (worst case for trader)
  - If only candle.high >= TP: TP hit, no SL violation in this bar
  - If only candle.low <= SL: SL hit
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import AsyncSessionLocal
from app.models.analysis import Analysis
from app.models.analysis_outcome import AnalysisOutcome
from app.services.price_service import get_current_gold_price

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  Initial outcome creation
# ═══════════════════════════════════════════════════════════════════

async def create_outcomes_from_analysis(
    db: AsyncSession, analysis: Analysis
) -> List[AnalysisOutcome]:
    """Persist setups as trackable outcomes."""
    setups = (analysis.result_json or {}).get("setups", [])
    chart_price = analysis.chart_price or 0.0
    if not setups or not chart_price:
        return []

    created = []
    for idx, setup in enumerate(setups):
        try:
            entries = setup.get("entries", [])
            if not entries:
                continue
            avg_entry = setup.get("avg_entry") or sum(entries) / len(entries)
            sl = setup.get("stop_loss")
            if sl is None:
                continue

            outcome = AnalysisOutcome(
                analysis_id=analysis.id,
                setup_index=idx,
                setup_label=setup.get("label", f"Setup {idx+1}"),
                direction=setup.get("direction", "buy"),
                entry_price=float(avg_entry),
                stop_loss=float(sl),
                tp_levels=setup.get("take_profits", []),
                expected_rr=setup.get("risk_reward"),
                chart_price_at_creation=chart_price,
            )
            db.add(outcome)
            created.append(outcome)
        except Exception as e:
            logger.warning("Failed to create outcome for setup %d: %s", idx, e)

    await db.flush()
    return created


# ═══════════════════════════════════════════════════════════════════
#  Candle fetcher (TwelveData M5)
# ═══════════════════════════════════════════════════════════════════

async def _fetch_candles_since(start_dt: datetime, symbol: str = "XAU/USD") -> List[dict]:
    """
    Fetch M5 candles from start_dt to now via TwelveData.
    Returns [{datetime, open, high, low, close}, ...] in chronological order.
    """
    if not settings.TWELVEDATA_KEY:
        return []

    # How many M5 bars are we asking for?
    minutes_elapsed = (datetime.utcnow() - start_dt).total_seconds() / 60
    bars_needed = min(int(minutes_elapsed / 5) + 5, 5000)

    if bars_needed < 1:
        return []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get("https://api.twelvedata.com/time_series", params={
                "symbol": symbol, "interval": "5min",
                "apikey": settings.TWELVEDATA_KEY,
                "outputsize": bars_needed,
                "format": "JSON", "order": "ASC",
            })
            r.raise_for_status()
            data = r.json()
            if data.get("status") == "error":
                logger.warning("TwelveData error: %s", data.get("message"))
                return []

            candles = []
            for v in data.get("values", []):
                try:
                    dt_str = v["datetime"]
                    if " " in dt_str:
                        c_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                    else:
                        c_dt = datetime.strptime(dt_str, "%Y-%m-%d")
                    if c_dt >= start_dt:
                        candles.append({
                            "dt": c_dt,
                            "open": float(v["open"]),
                            "high": float(v["high"]),
                            "low": float(v["low"]),
                            "close": float(v["close"]),
                        })
                except (KeyError, ValueError):
                    continue
            return candles
    except Exception as e:
        logger.warning("Candle fetch failed: %s", e)
        return []


# ═══════════════════════════════════════════════════════════════════
#  Sequence reconstruction from candles
# ═══════════════════════════════════════════════════════════════════

def _resolve_buy_outcome_from_candles(
    outcome: AnalysisOutcome, candles: List[dict],
) -> dict:
    """
    Walk through candles chronologically. Determine entry fill, then which
    level (TP/SL) is hit FIRST per candle.
    """
    updates = {}
    entry = outcome.entry_price
    sl = outcome.stop_loss
    tps = outcome.tp_levels or []

    entry_filled = outcome.entry_filled
    entry_fill_dt = outcome.entry_filled_at
    tp_hit_states = [getattr(outcome, f"tp{i+1}_hit", False) for i in range(4)]
    sl_hit = outcome.sl_hit
    max_fav = outcome.max_favorable_excursion or 0
    max_adv = outcome.max_adverse_excursion or 0

    for c in candles:
        # 1. Check entry fill (BUY: price drops to entry)
        if not entry_filled:
            if c["low"] <= entry:
                entry_filled = True
                entry_fill_dt = c["dt"]
                updates["entry_filled"] = True
                updates["entry_filled_at"] = entry_fill_dt
                updates["status"] = "active"
            else:
                continue

        # 2. Track excursions
        max_fav = max(max_fav, c["high"] - entry)
        max_adv = min(max_adv, c["low"] - entry)

        # 3. Check SL/TP hits within this candle
        sl_hit_in_bar = c["low"] <= sl
        tp_hits_in_bar = []
        for i, tp in enumerate(tps[:4]):
            tp_level = tp.get("level")
            if tp_level is not None and not tp_hit_states[i] and c["high"] >= tp_level:
                tp_hits_in_bar.append((i, tp_level))

        if sl_hit_in_bar and tp_hits_in_bar:
            # Both hit in same candle — use direction to disambiguate
            is_bearish_candle = c["close"] < c["open"]
            if is_bearish_candle:
                # Down then up → SL hit first
                sl_hit = True
                updates.update({
                    "sl_hit": True,
                    "status": "sl_hit",
                    "closed_at": c["dt"],
                    "final_close_price": sl,
                    "is_active": False,
                })
                risk = entry - sl
                if risk > 0:
                    updates["realized_rr"] = -1.0
                    updates["realized_pnl_pct"] = -100.0 * risk / entry
                break
            else:
                # Up then down → TP1 hit first; check if SL hit after TP1
                # We assume TP1 was hit and trade managed (BE move common)
                first_tp_idx, first_tp = tp_hits_in_bar[0]
                tp_hit_states[first_tp_idx] = True
                updates[f"tp{first_tp_idx+1}_hit"] = True
                # Conservative: also mark SL since direction was uncertain
                sl_hit = True
                updates.update({
                    "sl_hit": True,
                    "status": "tp_then_sl",  # ambiguous resolution
                    "closed_at": c["dt"],
                    "final_close_price": sl,
                    "is_active": False,
                })
                risk = entry - sl
                # Partial credit: assume 50% closed at TP1
                if risk > 0:
                    pnl_per_R = 0.5 * (first_tp - entry) / risk + 0.5 * -1.0
                    updates["realized_rr"] = pnl_per_R
                break
        elif sl_hit_in_bar:
            sl_hit = True
            updates.update({
                "sl_hit": True,
                "status": "sl_hit",
                "closed_at": c["dt"],
                "final_close_price": sl,
                "is_active": False,
            })
            risk = entry - sl
            if risk > 0:
                updates["realized_rr"] = -1.0
                updates["realized_pnl_pct"] = -100.0 * risk / entry
            break
        elif tp_hits_in_bar:
            for i, tp_level in tp_hits_in_bar:
                tp_hit_states[i] = True
                updates[f"tp{i+1}_hit"] = True

            # All TPs hit?
            valid_tps = [t for t in tps[:4] if t.get("level") is not None]
            if all(tp_hit_states[i] for i in range(len(valid_tps))) and valid_tps:
                last_tp_level = valid_tps[-1]["level"]
                updates.update({
                    "status": "tp_full",
                    "closed_at": c["dt"],
                    "final_close_price": last_tp_level,
                    "is_active": False,
                })
                risk = entry - sl
                reward = last_tp_level - entry
                if risk > 0:
                    updates["realized_rr"] = reward / risk
                    updates["realized_pnl_pct"] = 100.0 * reward / entry
                break

    updates["max_favorable_excursion"] = max_fav
    updates["max_adverse_excursion"] = max_adv
    return updates


def _resolve_sell_outcome_from_candles(
    outcome: AnalysisOutcome, candles: List[dict],
) -> dict:
    updates = {}
    entry = outcome.entry_price
    sl = outcome.stop_loss
    tps = outcome.tp_levels or []

    entry_filled = outcome.entry_filled
    entry_fill_dt = outcome.entry_filled_at
    tp_hit_states = [getattr(outcome, f"tp{i+1}_hit", False) for i in range(4)]
    sl_hit = outcome.sl_hit
    max_fav = outcome.max_favorable_excursion or 0
    max_adv = outcome.max_adverse_excursion or 0

    for c in candles:
        # 1. Entry fill (SELL: price rises to entry)
        if not entry_filled:
            if c["high"] >= entry:
                entry_filled = True
                entry_fill_dt = c["dt"]
                updates["entry_filled"] = True
                updates["entry_filled_at"] = entry_fill_dt
                updates["status"] = "active"
            else:
                continue

        max_fav = max(max_fav, entry - c["low"])
        max_adv = max(max_adv, c["high"] - entry)

        sl_hit_in_bar = c["high"] >= sl
        tp_hits_in_bar = []
        for i, tp in enumerate(tps[:4]):
            tp_level = tp.get("level")
            if tp_level is not None and not tp_hit_states[i] and c["low"] <= tp_level:
                tp_hits_in_bar.append((i, tp_level))

        if sl_hit_in_bar and tp_hits_in_bar:
            is_bullish_candle = c["close"] > c["open"]
            if is_bullish_candle:
                # Up then down → SL hit first for SELL
                sl_hit = True
                updates.update({
                    "sl_hit": True,
                    "status": "sl_hit",
                    "closed_at": c["dt"],
                    "final_close_price": sl,
                    "is_active": False,
                })
                risk = sl - entry
                if risk > 0:
                    updates["realized_rr"] = -1.0
                    updates["realized_pnl_pct"] = -100.0 * risk / entry
                break
            else:
                # Down then up → TP1 hit first
                first_tp_idx, first_tp = tp_hits_in_bar[0]
                tp_hit_states[first_tp_idx] = True
                updates[f"tp{first_tp_idx+1}_hit"] = True
                sl_hit = True
                updates.update({
                    "sl_hit": True,
                    "status": "tp_then_sl",
                    "closed_at": c["dt"],
                    "final_close_price": sl,
                    "is_active": False,
                })
                risk = sl - entry
                if risk > 0:
                    pnl_per_R = 0.5 * (entry - first_tp) / risk + 0.5 * -1.0
                    updates["realized_rr"] = pnl_per_R
                break
        elif sl_hit_in_bar:
            sl_hit = True
            updates.update({
                "sl_hit": True,
                "status": "sl_hit",
                "closed_at": c["dt"],
                "final_close_price": sl,
                "is_active": False,
            })
            risk = sl - entry
            if risk > 0:
                updates["realized_rr"] = -1.0
                updates["realized_pnl_pct"] = -100.0 * risk / entry
            break
        elif tp_hits_in_bar:
            for i, tp_level in tp_hits_in_bar:
                tp_hit_states[i] = True
                updates[f"tp{i+1}_hit"] = True

            valid_tps = [t for t in tps[:4] if t.get("level") is not None]
            if all(tp_hit_states[i] for i in range(len(valid_tps))) and valid_tps:
                last_tp_level = valid_tps[-1]["level"]
                updates.update({
                    "status": "tp_full",
                    "closed_at": c["dt"],
                    "final_close_price": last_tp_level,
                    "is_active": False,
                })
                risk = sl - entry
                reward = entry - last_tp_level
                if risk > 0:
                    updates["realized_rr"] = reward / risk
                    updates["realized_pnl_pct"] = 100.0 * reward / entry
                break

    updates["max_favorable_excursion"] = max_fav
    updates["max_adverse_excursion"] = max_adv
    return updates


# ═══════════════════════════════════════════════════════════════════
#  Main check loop
# ═══════════════════════════════════════════════════════════════════

async def check_all_active_outcomes(db: Optional[AsyncSession] = None) -> dict:
    """
    For each active outcome, fetch M5 candles since last check (or creation)
    and reconstruct the TP/SL sequence accurately.

    Falls back to live price check if candle fetch unavailable.
    """
    own_session = db is None
    if own_session:
        db = AsyncSessionLocal()

    try:
        result = await db.execute(
            select(AnalysisOutcome).where(AnalysisOutcome.is_active.is_(True))
        )
        outcomes = result.scalars().all()

        if not outcomes:
            return {"checked": 0, "closed": 0, "reason": "no_active_outcomes"}

        # Fallback price for excursion-only updates
        live_price = await get_current_gold_price()

        expire_threshold = datetime.utcnow() - timedelta(days=14)
        checked, closed, no_data = 0, 0, 0

        for outcome in outcomes:
            checked += 1

            # Auto-expire stale unfilled
            if not outcome.entry_filled and outcome.created_at:
                created_naive = outcome.created_at.replace(tzinfo=None) \
                    if outcome.created_at.tzinfo else outcome.created_at
                if created_naive < expire_threshold:
                    outcome.status = "expired"
                    outcome.is_active = False
                    outcome.closed_at = datetime.utcnow()
                    closed += 1
                    continue

            # Fetch candles since outcome creation (or last check)
            since_dt = outcome.last_checked_at or outcome.created_at
            if since_dt and since_dt.tzinfo:
                since_dt = since_dt.replace(tzinfo=None)

            candles = await _fetch_candles_since(since_dt or datetime.utcnow() - timedelta(hours=24))

            if candles:
                # Use candle-based resolution
                if outcome.direction == "buy":
                    updates = _resolve_buy_outcome_from_candles(outcome, candles)
                else:
                    updates = _resolve_sell_outcome_from_candles(outcome, candles)
            else:
                # Fallback to live price (V1 behavior)
                no_data += 1
                if live_price is None:
                    continue
                updates = _legacy_check_with_price(outcome, live_price)

            # Apply updates
            outcome.last_checked_at = datetime.utcnow()
            outcome.check_count = (outcome.check_count or 0) + 1
            if live_price:
                outcome.last_checked_price = live_price

            for k, v in updates.items():
                setattr(outcome, k, v)

            if updates.get("status") in ("tp_full", "sl_hit", "tp_then_sl"):
                closed += 1

        await db.commit()
        logger.info(
            "Outcome tracker V2: checked=%d, closed=%d, no_candle_data=%d",
            checked, closed, no_data,
        )
        return {
            "checked": checked, "closed": closed,
            "no_candle_data": no_data, "candle_based": no_data < checked,
        }

    except Exception as e:
        logger.exception("Outcome tracker failed")
        if own_session:
            await db.rollback()
        return {"checked": 0, "closed": 0, "error": str(e)}
    finally:
        if own_session:
            await db.close()


def _legacy_check_with_price(outcome: AnalysisOutcome, price: float) -> dict:
    """Fallback for when TwelveData unavailable. Less accurate."""
    updates = {}

    if outcome.direction == "buy":
        if not outcome.entry_filled and price <= outcome.entry_price:
            updates.update({
                "entry_filled": True,
                "entry_filled_at": datetime.utcnow(),
                "status": "active",
            })
            return updates
        if outcome.entry_filled:
            if price <= outcome.stop_loss and not outcome.sl_hit:
                risk = outcome.entry_price - outcome.stop_loss
                updates.update({
                    "sl_hit": True, "status": "sl_hit",
                    "closed_at": datetime.utcnow(),
                    "final_close_price": outcome.stop_loss, "is_active": False,
                    "realized_rr": -1.0,
                    "realized_pnl_pct": -100.0 * risk / outcome.entry_price if risk > 0 else 0,
                })
    else:  # sell
        if not outcome.entry_filled and price >= outcome.entry_price:
            updates.update({
                "entry_filled": True,
                "entry_filled_at": datetime.utcnow(),
                "status": "active",
            })
            return updates
        if outcome.entry_filled:
            if price >= outcome.stop_loss and not outcome.sl_hit:
                risk = outcome.stop_loss - outcome.entry_price
                updates.update({
                    "sl_hit": True, "status": "sl_hit",
                    "closed_at": datetime.utcnow(),
                    "final_close_price": outcome.stop_loss, "is_active": False,
                    "realized_rr": -1.0,
                    "realized_pnl_pct": -100.0 * risk / outcome.entry_price if risk > 0 else 0,
                })
    return updates

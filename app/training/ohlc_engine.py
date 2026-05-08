"""
OHLC Engine — programmatic price-action analysis that runs BEFORE Claude sees the chart.

Purpose: Give Claude an objective numerical baseline so it builds on top of facts
instead of guessing from a screenshot. This is the "pre-analysis" layer.

Pipeline:
  fetch_ohlc()  →  compute_indicators()  →  detect_structure()  →
  detect_zones()  →  detect_liquidity()  →  format_for_prompt()

Falls back to None gracefully if TwelveData key isn't set or data unavailable.
"""

import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Literal

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  Data structures
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Candle:
    dt: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Swing:
    """A pivot high or low."""
    idx: int
    price: float
    kind: Literal["HH", "HL", "LH", "LL"]
    dt: datetime


@dataclass
class OrderBlock:
    direction: Literal["bullish", "bearish"]
    high: float
    low: float
    formed_at_idx: int
    strength: float  # 0-1 based on subsequent move size


@dataclass
class FairValueGap:
    direction: Literal["bullish", "bearish"]
    high: float
    low: float
    formed_at_idx: int
    is_filled: bool = False


@dataclass
class LiquidityZone:
    kind: Literal["BSL", "SSL"]  # buy-side / sell-side liquidity
    price: float
    touch_count: int
    last_touch_idx: int


@dataclass
class OHLCAnalysis:
    """Complete programmatic snapshot — used to seed Claude's prompt."""
    symbol: str
    timeframe: str
    n_candles: int
    last_close: float
    last_dt: datetime

    # Indicators
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None
    rsi_14: Optional[float] = None
    atr_14: Optional[float] = None
    adx_14: Optional[float] = None

    # Structure
    trend: Literal["bullish", "bearish", "ranging"] = "ranging"
    trend_strength: float = 0.0  # 0-1
    structure: Literal["uptrend", "downtrend", "consolidation"] = "consolidation"
    last_swing_high: Optional[Swing] = None
    last_swing_low: Optional[Swing] = None
    recent_bos: Optional[dict] = None  # {direction, broken_level, at_idx}
    recent_choch: Optional[dict] = None

    # Premium/discount
    range_high: float = 0.0
    range_low: float = 0.0
    range_mid: float = 0.0
    current_zone: Literal["premium", "discount", "equilibrium"] = "equilibrium"
    pct_in_range: float = 50.0

    # Zones
    order_blocks: List[OrderBlock] = field(default_factory=list)
    fvgs: List[FairValueGap] = field(default_factory=list)
    liquidity: List[LiquidityZone] = field(default_factory=list)
    recent_sweep: Optional[dict] = None

    # Key levels
    daily_high: Optional[float] = None
    daily_low: Optional[float] = None
    weekly_open: Optional[float] = None
    nearest_resistance: Optional[float] = None
    nearest_support: Optional[float] = None

    # Volatility classification
    vol_regime: Literal["low", "normal", "high", "extreme"] = "normal"


# ═══════════════════════════════════════════════════════════════════
#  TwelveData fetcher
# ═══════════════════════════════════════════════════════════════════

INTERVAL_MAP = {
    "M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
    "H1": "1h", "H4": "4h", "D1": "1day", "W1": "1week",
}


async def fetch_ohlc(symbol: str = "XAUUSD", timeframe: str = "H1", limit: int = 300) -> List[Candle]:
    """Fetch last N candles. Returns [] if no key configured or fetch fails."""
    if not settings.TWELVEDATA_KEY:
        logger.debug("TWELVEDATA_KEY not set — OHLC engine disabled")
        return []

    interval = INTERVAL_MAP.get(timeframe.upper(), "1h")
    td_symbol = symbol.replace("USD", "/USD") if "/" not in symbol and symbol.endswith("USD") else symbol

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get("https://api.twelvedata.com/time_series", params={
                "symbol": td_symbol, "interval": interval,
                "apikey": settings.TWELVEDATA_KEY,
                "outputsize": min(limit, 5000),
                "format": "JSON", "order": "ASC",
            })
            r.raise_for_status()
            data = r.json()
            if data.get("status") == "error":
                logger.warning("TwelveData error: %s", data.get("message"))
                return []
            return [
                Candle(
                    dt=datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S")
                       if " " in v["datetime"]
                       else datetime.strptime(v["datetime"], "%Y-%m-%d"),
                    open=float(v["open"]), high=float(v["high"]),
                    low=float(v["low"]), close=float(v["close"]),
                    volume=float(v.get("volume", 0)),
                )
                for v in data.get("values", [])
            ]
    except Exception as e:
        logger.warning("OHLC fetch failed: %s", e)
        return []


# ═══════════════════════════════════════════════════════════════════
#  Indicators (pure-numpy / pure-python; no extra deps required)
# ═══════════════════════════════════════════════════════════════════

def _ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(candles: List[Candle], period: int = 14) -> Optional[float]:
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        c = candles[i]
        prev = candles[i - 1]
        tr = max(
            c.high - c.low,
            abs(c.high - prev.close),
            abs(c.low - prev.close),
        )
        trs.append(tr)
    # Wilder smoothing
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _adx(candles: List[Candle], period: int = 14) -> Optional[float]:
    """Simplified ADX — directional strength 0-100."""
    if len(candles) < period * 2:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(candles)):
        c = candles[i]; prev = candles[i - 1]
        up = c.high - prev.high
        dn = prev.low - c.low
        plus_dm.append(up if (up > dn and up > 0) else 0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0)
        tr = max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close))
        trs.append(tr)
    if not trs or sum(trs[-period:]) == 0:
        return None
    smooth_tr = sum(trs[-period:])
    smooth_p = sum(plus_dm[-period:])
    smooth_m = sum(minus_dm[-period:])
    plus_di = 100 * smooth_p / smooth_tr if smooth_tr else 0
    minus_di = 100 * smooth_m / smooth_tr if smooth_tr else 0
    if (plus_di + minus_di) == 0:
        return 0.0
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    return dx  # single-period DX as proxy for ADX


# ═══════════════════════════════════════════════════════════════════
#  Structure detection
# ═══════════════════════════════════════════════════════════════════

def _find_swings(candles: List[Candle], lookback: int = 3) -> List[Swing]:
    """Find pivot highs/lows using a simple lookback fractal."""
    swings: List[Swing] = []
    n = len(candles)
    if n < lookback * 2 + 1:
        return swings

    last_swing_high_price = None
    last_swing_low_price = None

    for i in range(lookback, n - lookback):
        window = candles[i - lookback:i + lookback + 1]
        c = candles[i]
        if c.high == max(w.high for w in window):
            kind: Literal["HH", "LH"] = "HH" if (last_swing_high_price is None or c.high > last_swing_high_price) else "LH"
            swings.append(Swing(idx=i, price=c.high, kind=kind, dt=c.dt))
            last_swing_high_price = c.high
        elif c.low == min(w.low for w in window):
            kind: Literal["HL", "LL"] = "HL" if (last_swing_low_price is None or c.low > last_swing_low_price) else "LL"
            swings.append(Swing(idx=i, price=c.low, kind=kind, dt=c.dt))
            last_swing_low_price = c.low

    return swings


def _classify_structure(swings: List[Swing]) -> Tuple[str, str, float]:
    """
    Returns (trend, structure_label, strength 0-1).
    """
    if len(swings) < 4:
        return "ranging", "consolidation", 0.0

    recent = swings[-6:]
    hh = sum(1 for s in recent if s.kind == "HH")
    hl = sum(1 for s in recent if s.kind == "HL")
    lh = sum(1 for s in recent if s.kind == "LH")
    ll = sum(1 for s in recent if s.kind == "LL")

    if hh >= 2 and hl >= 2 and ll == 0:
        return "bullish", "uptrend", min(1.0, (hh + hl) / 6)
    if ll >= 2 and lh >= 2 and hh == 0:
        return "bearish", "downtrend", min(1.0, (ll + lh) / 6)
    return "ranging", "consolidation", 0.3


def _detect_bos_choch(candles: List[Candle], swings: List[Swing]) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Detect Break of Structure (BOS) and Change of Character (CHoCH) in last 30 bars.
    """
    if len(swings) < 3 or len(candles) < 30:
        return None, None

    last_close = candles[-1].close
    bos = None
    choch = None
    cutoff = len(candles) - 30

    # Last broken swing high → bullish BOS; broken swing low → bearish BOS
    for s in reversed(swings[:-1]):
        if s.idx < cutoff:
            break
        # Find first candle after this swing that closed above/below it
        for i in range(s.idx + 1, len(candles)):
            c = candles[i]
            if s.kind in ("HH", "LH") and c.close > s.price:
                bos = {"direction": "bullish", "broken_level": s.price, "at_idx": i, "swing_kind": s.kind}
                if s.kind == "LH":
                    choch = {"direction": "bullish", **bos}
                break
            if s.kind in ("LL", "HL") and c.close < s.price:
                bos = {"direction": "bearish", "broken_level": s.price, "at_idx": i, "swing_kind": s.kind}
                if s.kind == "HL":
                    choch = {"direction": "bearish", **bos}
                break
        if bos:
            break

    return bos, choch


# ═══════════════════════════════════════════════════════════════════
#  Order blocks + FVG detection
# ═══════════════════════════════════════════════════════════════════

def _detect_order_blocks(candles: List[Candle], lookback: int = 50, min_move_atr: float = 1.5,
                          atr: Optional[float] = None) -> List[OrderBlock]:
    """
    OB definition: last opposite-color candle before a strong impulse move.
    Returns up to 4 most recent.
    """
    if len(candles) < lookback or atr is None or atr == 0:
        return []

    obs: List[OrderBlock] = []
    start = max(1, len(candles) - lookback)
    for i in range(start, len(candles) - 3):
        c = candles[i]
        # Bullish impulse: 3 strong up candles after this one
        if i + 3 < len(candles):
            move = candles[i + 3].close - c.close
            if move > min_move_atr * atr and c.close < c.open:  # bearish before impulse
                obs.append(OrderBlock(
                    direction="bullish", high=c.high, low=c.low,
                    formed_at_idx=i, strength=min(1.0, move / (atr * 3)),
                ))
            elif move < -min_move_atr * atr and c.close > c.open:  # bullish before impulse
                obs.append(OrderBlock(
                    direction="bearish", high=c.high, low=c.low,
                    formed_at_idx=i, strength=min(1.0, abs(move) / (atr * 3)),
                ))

    # Keep most recent 4
    return obs[-4:]


def _detect_fvgs(candles: List[Candle], lookback: int = 30) -> List[FairValueGap]:
    """
    Three-candle FVG: candle N-1 high < candle N+1 low (bullish gap) or vice versa.
    """
    fvgs: List[FairValueGap] = []
    start = max(1, len(candles) - lookback)
    for i in range(start, len(candles) - 1):
        prev = candles[i - 1]
        nxt = candles[i + 1]
        if prev.high < nxt.low:
            # Bullish FVG between prev.high and nxt.low
            fvg = FairValueGap("bullish", high=nxt.low, low=prev.high, formed_at_idx=i)
            fvg.is_filled = any(c.low <= fvg.low for c in candles[i + 1:])
            fvgs.append(fvg)
        elif prev.low > nxt.high:
            fvg = FairValueGap("bearish", high=prev.low, low=nxt.high, formed_at_idx=i)
            fvg.is_filled = any(c.high >= fvg.high for c in candles[i + 1:])
            fvgs.append(fvg)
    return fvgs[-4:]


# ═══════════════════════════════════════════════════════════════════
#  Liquidity / sweeps
# ═══════════════════════════════════════════════════════════════════

def _detect_liquidity_zones(candles: List[Candle], swings: List[Swing], tolerance_atr: float = 0.3,
                              atr: Optional[float] = None) -> List[LiquidityZone]:
    """Find clusters of equal highs (BSL) and equal lows (SSL)."""
    if not swings or atr is None:
        return []

    zones: List[LiquidityZone] = []
    tol = atr * tolerance_atr

    highs = [s for s in swings if s.kind in ("HH", "LH")]
    lows = [s for s in swings if s.kind in ("HL", "LL")]

    # Cluster highs
    used_h = set()
    for i, s in enumerate(highs):
        if i in used_h:
            continue
        cluster = [s]
        for j in range(i + 1, len(highs)):
            if j in used_h: continue
            if abs(highs[j].price - s.price) <= tol:
                cluster.append(highs[j])
                used_h.add(j)
        if len(cluster) >= 2:
            zones.append(LiquidityZone(
                kind="BSL", price=sum(c.price for c in cluster) / len(cluster),
                touch_count=len(cluster), last_touch_idx=max(c.idx for c in cluster),
            ))

    used_l = set()
    for i, s in enumerate(lows):
        if i in used_l: continue
        cluster = [s]
        for j in range(i + 1, len(lows)):
            if j in used_l: continue
            if abs(lows[j].price - s.price) <= tol:
                cluster.append(lows[j])
                used_l.add(j)
        if len(cluster) >= 2:
            zones.append(LiquidityZone(
                kind="SSL", price=sum(c.price for c in cluster) / len(cluster),
                touch_count=len(cluster), last_touch_idx=max(c.idx for c in cluster),
            ))

    return sorted(zones, key=lambda z: z.last_touch_idx, reverse=True)[:6]


def _detect_recent_sweep(candles: List[Candle], zones: List[LiquidityZone],
                          lookback_bars: int = 20, atr: Optional[float] = None) -> Optional[dict]:
    """
    Liquidity sweep: price wicks beyond a known zone but closes back inside, all in last N bars.
    """
    if not zones or atr is None or len(candles) < lookback_bars:
        return None
    start = len(candles) - lookback_bars
    for z in zones:
        for i in range(start, len(candles)):
            c = candles[i]
            if z.kind == "BSL" and c.high > z.price + atr * 0.1 and c.close < z.price:
                return {"zone_kind": "BSL", "zone_price": z.price, "swept_at_idx": i,
                        "wick_extreme": c.high, "close": c.close}
            if z.kind == "SSL" and c.low < z.price - atr * 0.1 and c.close > z.price:
                return {"zone_kind": "SSL", "zone_price": z.price, "swept_at_idx": i,
                        "wick_extreme": c.low, "close": c.close}
    return None


# ═══════════════════════════════════════════════════════════════════
#  Main analyze() — orchestrates everything
# ═══════════════════════════════════════════════════════════════════

async def analyze_ohlc(symbol: str = "XAUUSD", timeframe: str = "H1", limit: int = 300) -> Optional[OHLCAnalysis]:
    """
    Full programmatic analysis. Returns None if data unavailable.
    """
    candles = await fetch_ohlc(symbol, timeframe, limit)
    if len(candles) < 30:
        return None

    closes = [c.close for c in candles]
    last = candles[-1]

    # Indicators
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200) if len(closes) >= 200 else None
    rsi = _rsi(closes, 14)
    atr = _atr(candles, 14)
    adx = _adx(candles, 14)

    # Structure
    swings = _find_swings(candles, lookback=3)
    trend, structure, strength = _classify_structure(swings)
    bos, choch = _detect_bos_choch(candles, swings)
    last_high = next((s for s in reversed(swings) if s.kind in ("HH", "LH")), None)
    last_low = next((s for s in reversed(swings) if s.kind in ("HL", "LL")), None)

    # Range / premium-discount (last 50 bars)
    recent = candles[-50:] if len(candles) >= 50 else candles
    rh = max(c.high for c in recent)
    rl = min(c.low for c in recent)
    rmid = (rh + rl) / 2
    rsize = rh - rl
    pct = ((last.close - rl) / rsize * 100) if rsize > 0 else 50.0
    if pct >= 70:
        zone = "premium"
    elif pct <= 30:
        zone = "discount"
    else:
        zone = "equilibrium"

    # Zones
    obs = _detect_order_blocks(candles, lookback=50, min_move_atr=1.5, atr=atr)
    fvgs = _detect_fvgs(candles, lookback=30)
    liq = _detect_liquidity_zones(candles, swings, tolerance_atr=0.3, atr=atr)
    sweep = _detect_recent_sweep(candles, liq, lookback_bars=15, atr=atr)

    # Vol regime — relative ATR vs price
    vol_regime: str = "normal"
    if atr:
        rel = atr / last.close * 100
        if rel < 0.15:    vol_regime = "low"
        elif rel < 0.4:   vol_regime = "normal"
        elif rel < 0.8:   vol_regime = "high"
        else:             vol_regime = "extreme"

    # Daily / weekly anchors (only relevant for intraday TFs)
    daily_high = max(c.high for c in candles[-24:]) if len(candles) >= 24 else None
    daily_low = min(c.low for c in candles[-24:]) if len(candles) >= 24 else None
    weekly_open = candles[-min(168, len(candles))].open if len(candles) >= 24 else None

    # Nearest support/resistance from swings + zones
    levels_above = [s.price for s in swings if s.price > last.close]
    levels_below = [s.price for s in swings if s.price < last.close]
    nearest_res = min(levels_above) if levels_above else None
    nearest_sup = max(levels_below) if levels_below else None

    return OHLCAnalysis(
        symbol=symbol, timeframe=timeframe,
        n_candles=len(candles), last_close=last.close, last_dt=last.dt,
        ema_20=ema20, ema_50=ema50, ema_200=ema200,
        rsi_14=rsi, atr_14=atr, adx_14=adx,
        trend=trend, trend_strength=strength, structure=structure,
        last_swing_high=last_high, last_swing_low=last_low,
        recent_bos=bos, recent_choch=choch,
        range_high=rh, range_low=rl, range_mid=rmid,
        current_zone=zone, pct_in_range=pct,
        order_blocks=obs, fvgs=fvgs, liquidity=liq, recent_sweep=sweep,
        daily_high=daily_high, daily_low=daily_low, weekly_open=weekly_open,
        nearest_resistance=nearest_res, nearest_support=nearest_sup,
        vol_regime=vol_regime,
    )


# ═══════════════════════════════════════════════════════════════════
#  Format for prompt injection
# ═══════════════════════════════════════════════════════════════════

def format_for_prompt(analysis: OHLCAnalysis) -> str:
    """
    Convert OHLCAnalysis into a compact text block to inject as
    "OBJECTIVE PRE-ANALYSIS" before Claude reads the chart image.
    """
    a = analysis
    lines = [
        "# 🔢 OBJECTIVE PRE-ANALYSIS (from numerical OHLC engine)",
        "# Use this as your factual baseline. The chart image confirms/refines it.",
        "",
        f"## Market state — {a.symbol} {a.timeframe} (last {a.n_candles} candles, last close: {a.last_close:.2f})",
    ]

    # Trend
    lines.append(f"- **Trend**: {a.trend} ({a.structure}), strength={a.trend_strength:.2f}")
    if a.ema_20 and a.ema_50:
        ema_str = f"EMA20={a.ema_20:.2f}, EMA50={a.ema_50:.2f}"
        if a.ema_200:
            ema_str += f", EMA200={a.ema_200:.2f}"
        lines.append(f"- **EMAs**: {ema_str}")
        if a.ema_20 and a.ema_50 and a.ema_20 > a.ema_50:
            lines.append("  → Short-term EMAs in BULLISH stack")
        elif a.ema_20 and a.ema_50 and a.ema_20 < a.ema_50:
            lines.append("  → Short-term EMAs in BEARISH stack")

    if a.adx_14 is not None:
        adx_label = "weak" if a.adx_14 < 20 else "strong" if a.adx_14 < 40 else "very strong"
        lines.append(f"- **ADX**: {a.adx_14:.1f} ({adx_label} directional move)")
    if a.rsi_14 is not None:
        rsi_label = "oversold" if a.rsi_14 < 30 else "overbought" if a.rsi_14 > 70 else "neutral"
        lines.append(f"- **RSI(14)**: {a.rsi_14:.1f} ({rsi_label})")
    if a.atr_14 is not None:
        lines.append(f"- **ATR(14)**: {a.atr_14:.2f} ({a.vol_regime} volatility)")

    # Range
    lines.append("")
    lines.append("## Range / Premium-Discount (last 50 bars)")
    lines.append(f"- Range: {a.range_low:.2f} ↔ {a.range_high:.2f} (mid: {a.range_mid:.2f})")
    lines.append(f"- Current price is at **{a.pct_in_range:.1f}%** of range → **{a.current_zone.upper()}** zone")

    # Structure events
    if a.recent_bos:
        b = a.recent_bos
        lines.append("")
        lines.append(f"## Structure event")
        lines.append(f"- Recent **BOS** ({b['direction']}): broke {b['broken_level']:.2f}")
    if a.recent_choch:
        c = a.recent_choch
        lines.append(f"- Recent **CHoCH** ({c['direction']}): broke {c['broken_level']:.2f} → trend may be reversing")

    # Liquidity
    if a.liquidity:
        lines.append("")
        lines.append("## Liquidity zones (clusters of equal highs/lows)")
        for z in a.liquidity[:4]:
            lines.append(f"- **{z.kind}** @ {z.price:.2f} (touched {z.touch_count}x)")

    if a.recent_sweep:
        s = a.recent_sweep
        lines.append(f"- ⚠️  Recent **sweep**: {s['zone_kind']} @ {s['zone_price']:.2f} (wick to {s['wick_extreme']:.2f}, closed at {s['close']:.2f})")

    # Order blocks
    if a.order_blocks:
        lines.append("")
        lines.append("## Order blocks (recent)")
        for ob in a.order_blocks[-3:]:
            lines.append(f"- **{ob.direction.upper()}** OB: {ob.low:.2f} - {ob.high:.2f} (strength: {ob.strength:.2f})")

    # FVGs
    if a.fvgs:
        unfilled = [f for f in a.fvgs if not f.is_filled]
        if unfilled:
            lines.append("")
            lines.append("## Unfilled FVGs")
            for f in unfilled[-3:]:
                lines.append(f"- **{f.direction.upper()}** FVG: {f.low:.2f} - {f.high:.2f}")

    # Anchors
    lines.append("")
    lines.append("## Key levels")
    if a.nearest_resistance:
        lines.append(f"- Nearest resistance: **{a.nearest_resistance:.2f}** (+{a.nearest_resistance - a.last_close:.2f})")
    if a.nearest_support:
        lines.append(f"- Nearest support: **{a.nearest_support:.2f}** ({a.nearest_support - a.last_close:.2f})")
    if a.daily_high and a.daily_low:
        lines.append(f"- Recent range: low {a.daily_low:.2f} / high {a.daily_high:.2f}")

    lines.append("")
    lines.append("# IMPORTANT — Use these objective levels as anchors. Do not invent levels that contradict this data.")
    return "\n".join(lines)


def to_dict(analysis: OHLCAnalysis) -> dict:
    """Serialize to JSON-safe dict for storage."""
    d = asdict(analysis)
    d["last_dt"] = analysis.last_dt.isoformat()
    if analysis.last_swing_high:
        d["last_swing_high"]["dt"] = analysis.last_swing_high.dt.isoformat()
    if analysis.last_swing_low:
        d["last_swing_low"]["dt"] = analysis.last_swing_low.dt.isoformat()
    return d

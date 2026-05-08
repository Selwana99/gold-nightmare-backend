"""
Validator V2 — rule-based setup quality gate with anti-bias rules.

NEW IN V2:
  - NO TRADE Mode (HTF conflict, mid-range, extreme vol, no structure)
  - Momentum exhaustion filter (don't sell bottoms / buy tops)
  - Entry-at-edge requirement (no mid-zone entries)
  - min_rr raised from 1.0 → 1.5
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Literal

logger = logging.getLogger(__name__)


Severity = Literal["critical", "warning", "info"]


@dataclass
class ValidationIssue:
    severity: Severity
    code: str
    message_ar: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code,
                "message_ar": self.message_ar, "detail": self.detail}


@dataclass
class ValidationReport:
    setup_index: int
    issues: List[ValidationIssue] = field(default_factory=list)
    score: float = 100.0
    is_rejected: bool = False

    def add(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)
        if issue.severity == "critical":
            self.score -= 50
            self.is_rejected = True
        elif issue.severity == "warning":
            self.score -= 15
        elif issue.severity == "info":
            self.score -= 5
        self.score = max(0.0, self.score)

    def to_dict(self) -> dict:
        return {
            "setup_index": self.setup_index,
            "score": round(self.score, 1),
            "is_rejected": self.is_rejected,
            "issue_counts": {
                "critical": sum(1 for i in self.issues if i.severity == "critical"),
                "warning": sum(1 for i in self.issues if i.severity == "warning"),
                "info": sum(1 for i in self.issues if i.severity == "info"),
            },
            "issues": [i.to_dict() for i in self.issues],
        }


def _parse_rr_numeric(rr_str: Optional[str]) -> float:
    if not rr_str:
        return 0.0
    try:
        parts = rr_str.replace("→", ":").split(":")
        nums = [float(p.strip()) for p in parts if p.strip().replace(".", "").isdigit()]
        if len(nums) >= 2:
            return nums[1] / nums[0] if nums[0] else 0.0
    except Exception:
        pass
    return 0.0


def _avg_entry(setup: dict) -> Optional[float]:
    if setup.get("avg_entry"):
        return float(setup["avg_entry"])
    entries = setup.get("entries") or []
    return sum(entries) / len(entries) if entries else None


# ═══ Geometry ═══

def _check_basic_geometry(setup: dict, report: ValidationReport) -> None:
    direction = setup.get("direction")
    entry = _avg_entry(setup)
    sl = setup.get("stop_loss")
    tps = [t.get("level") for t in setup.get("take_profits") or [] if t.get("level") is not None]

    if entry is None or sl is None:
        report.add(ValidationIssue("critical", "MISSING_FIELDS",
            "Entry أو Stop Loss مفقود", {"entry": entry, "sl": sl}))
        return

    if direction == "buy":
        if sl >= entry:
            report.add(ValidationIssue("critical", "INVERTED_SL_BUY",
                f"BUY لكن SL ({sl:.2f}) >= Entry ({entry:.2f})", {"entry": entry, "sl": sl}))
        for i, tp in enumerate(tps, 1):
            if tp <= entry:
                report.add(ValidationIssue("critical", f"INVERTED_TP{i}_BUY",
                    f"BUY لكن TP{i} ({tp:.2f}) <= Entry ({entry:.2f})",
                    {"tp_idx": i, "tp": tp, "entry": entry}))
    elif direction == "sell":
        if sl <= entry:
            report.add(ValidationIssue("critical", "INVERTED_SL_SELL",
                f"SELL لكن SL ({sl:.2f}) <= Entry ({entry:.2f})", {"entry": entry, "sl": sl}))
        for i, tp in enumerate(tps, 1):
            if tp >= entry:
                report.add(ValidationIssue("critical", f"INVERTED_TP{i}_SELL",
                    f"SELL لكن TP{i} ({tp:.2f}) >= Entry ({entry:.2f})",
                    {"tp_idx": i, "tp": tp, "entry": entry}))


def _check_tp_progression(setup: dict, report: ValidationReport) -> None:
    direction = setup.get("direction")
    tps = [t.get("level") for t in setup.get("take_profits") or [] if t.get("level") is not None]
    if len(tps) < 2:
        return
    if direction == "buy":
        for i in range(1, len(tps)):
            if tps[i] <= tps[i - 1]:
                report.add(ValidationIssue("critical", "TP_NOT_PROGRESSIVE",
                    f"TP{i+1} ليس أبعد من TP{i}", {"tps": tps}))
                return
    elif direction == "sell":
        for i in range(1, len(tps)):
            if tps[i] >= tps[i - 1]:
                report.add(ValidationIssue("critical", "TP_NOT_PROGRESSIVE",
                    f"TP{i+1} ليس أبعد من TP{i}", {"tps": tps}))
                return


# ═══ R:R — RAISED to 1.5 ═══

def _check_rr(setup: dict, report: ValidationReport, min_rr: float = 1.5) -> None:
    rr = _parse_rr_numeric(setup.get("risk_reward"))
    if rr <= 0:
        entry = _avg_entry(setup)
        sl = setup.get("stop_loss")
        tps = [t.get("level") for t in setup.get("take_profits") or [] if t.get("level") is not None]
        if entry and sl and tps:
            risk = abs(entry - sl)
            reward = abs(max(tps) - entry) if setup.get("direction") == "buy" else abs(entry - min(tps))
            rr = reward / risk if risk > 0 else 0.0

    if rr < min_rr:
        sev: Severity = "critical" if rr < 1.0 else "warning"
        report.add(ValidationIssue(sev, "POOR_RR",
            f"R:R = {rr:.2f} (الحد الأدنى {min_rr})",
            {"computed_rr": round(rr, 2), "min_rr": min_rr}))


def _check_close_pct_sums(setup: dict, report: ValidationReport) -> None:
    tps = setup.get("take_profits") or []
    total = sum(t.get("close_pct", 0) or 0 for t in tps)
    if total > 100:
        report.add(ValidationIssue("warning", "CLOSE_PCT_OVER_100",
            f"مجموع close_pct = {total} > 100", {"total_pct": total}))


# ═══ Distance / volatility / liquidity ═══

def _check_sl_distance_atr(setup: dict, report: ValidationReport, atr: Optional[float] = None,
                            min_atr: float = 0.5, max_atr: float = 6.0) -> None:
    if atr is None or atr <= 0:
        return
    entry = _avg_entry(setup)
    sl = setup.get("stop_loss")
    if entry is None or sl is None:
        return
    dist_atr = abs(entry - sl) / atr
    if dist_atr < min_atr:
        report.add(ValidationIssue("warning", "SL_TOO_CLOSE_ATR",
            f"SL على بُعد {dist_atr:.2f} ATR — noise risk", {"distance_atr": round(dist_atr, 2)}))
    elif dist_atr > max_atr:
        report.add(ValidationIssue("warning", "SL_TOO_FAR_ATR",
            f"SL على بُعد {dist_atr:.2f} ATR — مخاطرة كبيرة", {"distance_atr": round(dist_atr, 2)}))


def _check_entry_distance(setup: dict, report: ValidationReport,
                            current_price: Optional[float], max_pct: float = 2.0) -> None:
    if not current_price:
        return
    entry = _avg_entry(setup)
    if entry is None:
        return
    pct_away = abs(entry - current_price) / current_price * 100
    if pct_away > max_pct:
        report.add(ValidationIssue("warning", "ENTRY_TOO_FAR",
            f"Entry {pct_away:.2f}% بعيد عن السعر",
            {"entry": entry, "current_price": current_price}))


def _check_htf_bias_alignment(setup: dict, report: ValidationReport,
                                htf_bias: Optional[str]) -> None:
    if not htf_bias or htf_bias == "neutral":
        return
    direction = setup.get("direction")
    if (htf_bias == "bullish" and direction == "sell") or \
       (htf_bias == "bearish" and direction == "buy"):
        report.add(ValidationIssue("warning", "AGAINST_HTF_BIAS",
            f"Setup ({direction.upper()}) يخالف HTF bias ({htf_bias})",
            {"htf_bias": htf_bias, "setup_direction": direction}))


def _check_premium_discount(setup: dict, report: ValidationReport,
                              current_zone: Optional[str]) -> None:
    if not current_zone or current_zone == "equilibrium":
        return
    direction = setup.get("direction")
    if direction == "buy" and current_zone == "premium":
        report.add(ValidationIssue("warning", "BUY_IN_PREMIUM",
            "BUY في PREMIUM zone", {"zone": current_zone}))
    elif direction == "sell" and current_zone == "discount":
        report.add(ValidationIssue("warning", "SELL_IN_DISCOUNT",
            "SELL في DISCOUNT zone", {"zone": current_zone}))


def _check_sl_inside_liquidity(setup: dict, report: ValidationReport,
                                 liquidity_zones: List[dict],
                                 atr: Optional[float] = None) -> None:
    if not liquidity_zones or atr is None:
        return
    sl = setup.get("stop_loss")
    direction = setup.get("direction")
    if sl is None:
        return
    tol = atr * 0.4
    for z in liquidity_zones:
        z_price = z.get("price")
        z_kind = z.get("kind")
        if z_price is None:
            continue
        if direction == "buy" and z_kind == "SSL" and abs(sl - z_price) <= tol:
            report.add(ValidationIssue("warning", "SL_NEAR_LIQUIDITY_SSL",
                f"SL قريب من SSL @ {z_price:.2f} — sweep risk",
                {"sl": sl, "zone_price": z_price}))
            return
        if direction == "sell" and z_kind == "BSL" and abs(sl - z_price) <= tol:
            report.add(ValidationIssue("warning", "SL_NEAR_LIQUIDITY_BSL",
                f"SL قريب من BSL @ {z_price:.2f} — sweep risk",
                {"sl": sl, "zone_price": z_price}))
            return


# ═══ NEW V2: Momentum exhaustion ═══

def _check_momentum_exhaustion(setup: dict, report: ValidationReport,
                                ohlc_analysis: Optional[dict]) -> None:
    """Block trades that bet against extended momentum without pullback."""
    if not ohlc_analysis:
        return

    direction = setup.get("direction")
    trend = ohlc_analysis.get("trend")
    trend_strength = ohlc_analysis.get("trend_strength", 0) or 0
    adx = ohlc_analysis.get("adx_14") or 0
    pct_in_range = ohlc_analysis.get("pct_in_range", 50)
    rsi = ohlc_analysis.get("rsi_14") or 50

    strong_trend = adx >= 25 and trend_strength >= 0.5
    if not strong_trend:
        return

    # SELL after extended drop in discount → exhaustion
    if direction == "sell" and trend == "bearish" and pct_in_range <= 25 and rsi <= 35:
        report.add(ValidationIssue("warning", "MOMENTUM_EXHAUSTION_SELL",
            f"بيع في قاع بعد هبوط ممتد (ADX={adx:.0f}, RSI={rsi:.0f}) — احتمال استنزاف",
            {"trend": trend, "adx": adx, "rsi": rsi, "pct_in_range": pct_in_range}))

    # BUY after extended rally in premium → exhaustion
    if direction == "buy" and trend == "bullish" and pct_in_range >= 75 and rsi >= 65:
        report.add(ValidationIssue("warning", "MOMENTUM_EXHAUSTION_BUY",
            f"شراء في قمة بعد صعود ممتد (ADX={adx:.0f}, RSI={rsi:.0f}) — احتمال استنزاف",
            {"trend": trend, "adx": adx, "rsi": rsi, "pct_in_range": pct_in_range}))


# ═══ NEW V2: Entry must be at edge of OB, not middle ═══

def _check_entry_at_edge(setup: dict, report: ValidationReport,
                           order_blocks: Optional[List[dict]] = None) -> None:
    if not order_blocks:
        return
    direction = setup.get("direction")
    entry = _avg_entry(setup)
    if entry is None:
        return

    needed_kind = "bullish" if direction == "buy" else "bearish"
    relevant_ob = None
    for ob in order_blocks:
        kind = ob.get("type") or ob.get("direction")
        if kind == needed_kind:
            ob_high = ob.get("high") or ob.get("range_high")
            ob_low = ob.get("low") or ob.get("range_low")
            if ob_high and ob_low and ob_low <= entry <= ob_high:
                relevant_ob = (ob_low, ob_high)
                break

    if not relevant_ob:
        return

    ob_low, ob_high = relevant_ob
    ob_range = ob_high - ob_low
    if ob_range <= 0:
        return

    position = (entry - ob_low) / ob_range  # 0 = bottom edge, 1 = top edge

    if direction == "buy" and position > 0.55:
        report.add(ValidationIssue("warning", "ENTRY_MID_ZONE",
            f"BUY في منتصف/أعلى الـ OB ({position*100:.0f}%) — يفضّل الحافة السفلى",
            {"position_in_ob": round(position, 2)}))
    elif direction == "sell" and position < 0.45:
        report.add(ValidationIssue("warning", "ENTRY_MID_ZONE",
            f"SELL في منتصف/أسفل الـ OB ({position*100:.0f}%) — يفضّل الحافة العليا",
            {"position_in_ob": round(position, 2)}))


# ═══ Losing pattern match ═══

def _check_against_learned_losing_pattern(
    setup: dict, report: ValidationReport, htf_bias: Optional[str],
    current_zone: Optional[str], losing_patterns: List[dict],
) -> None:
    if not losing_patterns:
        return
    direction = setup.get("direction")
    rr = _parse_rr_numeric(setup.get("risk_reward"))
    feature_set = {
        "direction": direction, "zone": current_zone, "htf_bias": htf_bias,
        "rr_band": "low" if rr < 1.5 else "mid" if rr < 2.5 else "high",
    }
    for pattern in losing_patterns:
        match = all(
            feature_set.get(k) == v
            for k, v in pattern.get("features", {}).items()
            if v is not None
        )
        if match:
            wr = pattern.get("win_rate", 0)
            n = pattern.get("sample_size", 0)
            report.add(ValidationIssue("critical", "MATCHES_LOSING_PATTERN",
                f"يطابق نمط فاشل: win rate {wr*100:.0f}% على {n} حالة",
                {"pattern": pattern}))
            return


# ═══ NEW V2: NO TRADE Mode (preflight) ═══

def _evaluate_no_trade_conditions(
    result_json: dict, ohlc_analysis: Optional[dict]
) -> List[dict]:
    """Market-wide NO TRADE conditions. If non-empty, every setup is suspect."""
    reasons: List[dict] = []
    if not ohlc_analysis:
        return reasons

    # 1. Extreme volatility
    if ohlc_analysis.get("vol_regime") == "extreme":
        reasons.append({
            "code": "NO_TRADE_EXTREME_VOL",
            "message_ar": "تقلّب متطرّف — ATR > 0.8% من السعر. لا تدخل.",
        })

    # 2. Stuck in middle of range with no momentum
    pct = ohlc_analysis.get("pct_in_range", 50)
    adx = ohlc_analysis.get("adx_14") or 0
    if 40 <= pct <= 60 and adx < 18:
        reasons.append({
            "code": "NO_TRADE_MIDDLE_RANGE",
            "message_ar": f"السعر في منتصف الرينج ({pct:.0f}%) + ADX ضعيف ({adx:.0f}) — لا حافة.",
        })

    # 3. HTF conflict (Claude bias vs OHLC trend)
    bias = (result_json.get("session_bias") or {}).get("primary_bias")
    ohlc_trend = ohlc_analysis.get("trend")
    if bias and ohlc_trend and bias != "neutral" and ohlc_trend != "ranging":
        if bias != ohlc_trend:
            reasons.append({
                "code": "NO_TRADE_HTF_CONFLICT",
                "message_ar": f"تعارض: Claude يقول {bias}، OHLC يقول {ohlc_trend}.",
            })

    # 4. No structure event + low ADX
    if not ohlc_analysis.get("recent_bos") and not ohlc_analysis.get("recent_choch"):
        if adx < 15:
            reasons.append({
                "code": "NO_TRADE_NO_STRUCTURE",
                "message_ar": f"لا BOS/CHoCH حديث + ADX منخفض ({adx:.0f}) — سوق بدون اتجاه.",
            })

    return reasons


# ═══ Public API ═══

def validate_setup(
    setup: dict,
    setup_index: int = 0,
    *,
    current_price: Optional[float] = None,
    htf_bias: Optional[str] = None,
    current_zone: Optional[str] = None,
    atr: Optional[float] = None,
    liquidity_zones: Optional[List[dict]] = None,
    vol_regime: Optional[str] = None,
    losing_patterns: Optional[List[dict]] = None,
    ohlc_analysis: Optional[dict] = None,
    order_blocks: Optional[List[dict]] = None,
    min_rr: float = 1.5,
) -> ValidationReport:
    report = ValidationReport(setup_index=setup_index)

    _check_basic_geometry(setup, report)
    if report.is_rejected:
        return report

    _check_tp_progression(setup, report)
    _check_close_pct_sums(setup, report)
    _check_rr(setup, report, min_rr=min_rr)
    _check_sl_distance_atr(setup, report, atr=atr)
    _check_entry_distance(setup, report, current_price=current_price)
    _check_htf_bias_alignment(setup, report, htf_bias=htf_bias)
    _check_premium_discount(setup, report, current_zone=current_zone)
    _check_sl_inside_liquidity(setup, report, liquidity_zones or [], atr=atr)
    _check_momentum_exhaustion(setup, report, ohlc_analysis=ohlc_analysis)
    _check_entry_at_edge(setup, report, order_blocks=order_blocks)
    _check_against_learned_losing_pattern(
        setup, report, htf_bias=htf_bias, current_zone=current_zone,
        losing_patterns=losing_patterns or [],
    )
    return report


def validate_analysis_result(
    result_json: dict,
    *,
    ohlc_analysis: Optional[dict] = None,
    losing_patterns: Optional[List[dict]] = None,
    min_rr: float = 1.5,
) -> dict:
    setups = result_json.get("setups") or []

    no_trade_reasons = _evaluate_no_trade_conditions(result_json, ohlc_analysis)
    if no_trade_reasons:
        result_json["no_trade_warnings"] = no_trade_reasons
        logger.warning("NO TRADE conditions: %s", [r["code"] for r in no_trade_reasons])

    if not setups:
        result_json["validation_summary"] = {
            "setups_total": 0, "kept": 0, "rejected": 0,
            "no_trade_active": bool(no_trade_reasons),
        }
        return result_json

    chart_meta = result_json.get("chart_meta") or {}
    bias = result_json.get("session_bias") or {}
    pd = result_json.get("premium_discount") or {}
    order_blocks = result_json.get("order_blocks") or []

    current_price = chart_meta.get("current_price")
    htf_bias = bias.get("primary_bias")
    current_zone = pd.get("current_zone")

    atr = None
    liquidity_zones: List[dict] = []
    vol_regime = None
    if ohlc_analysis:
        atr = ohlc_analysis.get("atr_14")
        vol_regime = ohlc_analysis.get("vol_regime")
        for z in ohlc_analysis.get("liquidity") or []:
            liquidity_zones.append({"price": z.get("price"), "kind": z.get("kind")})

    kept = []
    rejected = []
    for i, setup in enumerate(setups):
        report = validate_setup(
            setup, setup_index=i,
            current_price=current_price, htf_bias=htf_bias,
            current_zone=current_zone, atr=atr,
            liquidity_zones=liquidity_zones, vol_regime=vol_regime,
            losing_patterns=losing_patterns,
            ohlc_analysis=ohlc_analysis,
            order_blocks=order_blocks,
            min_rr=min_rr,
        )
        setup["validation"] = report.to_dict()
        if report.is_rejected:
            rejected.append(setup)
        else:
            kept.append(setup)

    result_json["setups"] = kept
    result_json["rejected_setups"] = rejected
    result_json["validation_summary"] = {
        "setups_total": len(setups),
        "kept": len(kept),
        "rejected": len(rejected),
        "rejection_reasons": [
            i["code"] for s in rejected for i in s.get("validation", {}).get("issues", [])
            if i.get("severity") == "critical"
        ],
        "no_trade_active": bool(no_trade_reasons),
        "no_trade_reasons": [r["code"] for r in no_trade_reasons],
    }

    if rejected:
        logger.info("Validator rejected %d/%d setups", len(rejected), len(setups))

    return result_json

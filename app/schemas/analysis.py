"""Analysis result schemas."""

from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict


# ─── Result components ───

class ChartMeta(BaseModel):
    symbol: str = "XAUUSD"
    timeframe: str
    current_price: Optional[float] = None
    trend_direction: Literal["bullish", "bearish", "ranging", "neutral"] = "neutral"


class StructureRead(BaseModel):
    summary_ar: str
    key_swing_high: Optional[float] = None
    key_swing_low: Optional[float] = None
    bos_chochs: List[dict] = Field(default_factory=list)


class Liquidity(BaseModel):
    bsl: List[float] = Field(default_factory=list)
    ssl: List[float] = Field(default_factory=list)
    swept_recently_ar: List[str] = Field(default_factory=list)


class OrderBlock(BaseModel):
    type: Literal["bullish", "bearish"]
    range_high: float
    range_low: float
    timeframe: Optional[str] = None
    note_ar: Optional[str] = None


class FairValueGap(BaseModel):
    type: Literal["bullish", "bearish"]
    high: float
    low: float
    timeframe: Optional[str] = None


class PremiumDiscount(BaseModel):
    range_high: float
    range_low: float
    midpoint: float
    current_zone: Literal["premium", "discount", "equilibrium"]


class SessionBias(BaseModel):
    primary_bias: Literal["bullish", "bearish", "neutral"]
    notes_ar: Optional[str] = None


class TakeProfit(BaseModel):
    level: float
    close_pct: int = Field(..., ge=1, le=100)
    label_ar: Optional[str] = None


class Setup(BaseModel):
    label: str
    direction: Literal["buy", "sell"]
    order_type: Literal["market", "limit", "stop", "limit_split", "stop_split"] = "limit"
    priority: Literal["primary", "secondary", "alternate"] = "primary"
    trigger_ar: str
    entries: List[float] = Field(..., min_length=1, max_length=4)
    avg_entry: Optional[float] = None
    stop_loss: float
    take_profits: List[TakeProfit] = Field(..., min_length=1, max_length=4)
    risk_reward: Optional[str] = None
    rationale_ar: str
    invalidation_ar: str
    ml_quality_score: Optional[float] = None  # populated by classifier


class AnalysisResult(BaseModel):
    chart_meta: ChartMeta
    structure_read: StructureRead
    liquidity: Liquidity
    order_blocks: List[OrderBlock] = Field(default_factory=list)
    fvg: List[FairValueGap] = Field(default_factory=list)
    premium_discount: PremiumDiscount
    session_bias: SessionBias
    setups: List[Setup] = Field(default_factory=list)
    confidence_score: Optional[float] = Field(None, ge=0, le=1)
    notes_ar: Optional[str] = None


# ─── Persisted ───

class AnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    symbol: str
    timeframe: str
    is_mtf: bool
    chart_price: Optional[float] = None
    market_price: Optional[float] = None
    primary_bias: Optional[str] = None
    trend_direction: Optional[str] = None
    source: str
    user_context: Optional[str] = None
    result_json: Optional[dict] = None
    image_count: int
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: Optional[float] = None
    duration_ms: int
    status: str
    created_at: datetime


class AnalysisListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    symbol: str
    timeframe: str
    is_mtf: bool
    chart_price: Optional[float] = None
    primary_bias: Optional[str] = None
    trend_direction: Optional[str] = None
    setup_count: int = 0
    cost_usd: Optional[float] = None
    created_at: datetime


class AnalysisListResponse(BaseModel):
    items: List[AnalysisListItem]
    total: int
    page: int
    page_size: int


class ShareLinkPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    token: str
    public_url: str
    is_active: bool
    view_count: int
    expires_at: Optional[datetime] = None
    created_at: datetime

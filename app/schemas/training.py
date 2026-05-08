"""Training/feedback schemas."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class OutcomePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    analysis_id: str
    setup_index: int
    setup_label: Optional[str] = None
    direction: str
    entry_price: float
    stop_loss: float
    expected_rr: Optional[str] = None
    chart_price_at_creation: float
    is_active: bool
    entry_filled: bool
    entry_filled_at: Optional[datetime] = None
    status: str
    closed_at: Optional[datetime] = None
    final_close_price: Optional[float] = None
    realized_rr: Optional[float] = None
    realized_pnl_pct: Optional[float] = None
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False
    tp4_hit: bool = False
    sl_hit: bool = False
    max_favorable_excursion: Optional[float] = None
    max_adverse_excursion: Optional[float] = None
    last_checked_price: Optional[float] = None
    last_checked_at: Optional[datetime] = None
    check_count: int = 0
    created_at: datetime


class FeedbackCreate(BaseModel):
    accuracy_rating: Optional[int] = Field(None, ge=1, le=5)
    usefulness_rating: Optional[int] = Field(None, ge=1, le=5)
    bias_correct: Optional[bool] = None
    levels_correct: Optional[bool] = None
    setup_followed: Optional[bool] = None
    setup_profitable: Optional[bool] = None
    comments: Optional[str] = Field(None, max_length=2000)


class FeedbackPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    analysis_id: str
    accuracy_rating: Optional[int] = None
    usefulness_rating: Optional[int] = None
    bias_correct: Optional[bool] = None
    levels_correct: Optional[bool] = None
    setup_followed: Optional[bool] = None
    setup_profitable: Optional[bool] = None
    comments: Optional[str] = None
    is_quality_example: bool = False
    created_at: datetime


class BacktestCreate(BaseModel):
    name: str = Field(..., max_length=120)
    symbol: str = Field("XAUUSD", max_length=20)
    timeframe: str = Field(..., max_length=10)
    start_date: datetime
    end_date: datetime
    model_used: Optional[str] = None
    notes: Optional[str] = None
    sample_size: int = Field(20, ge=1, le=200)


class BacktestPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    model_used: str
    status: str
    total_setups_generated: int
    total_setups_filled: int
    wins: int
    losses: int
    win_rate: Optional[float] = None
    avg_realized_rr: Optional[float] = None
    total_pnl_R: Optional[float] = None
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: Optional[float] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class FewShotPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    symbol: str
    timeframe: str
    market_regime: Optional[str] = None
    summary_text: str
    quality_score: float
    realized_rr: Optional[float] = None
    is_active: bool
    use_count: int = 0
    created_at: datetime
    last_used_at: Optional[datetime] = None


class FewShotPromote(BaseModel):
    analysis_id: str
    market_regime: Optional[str] = Field(None, max_length=40)
    realized_rr: Optional[float] = None
    quality_score: float = Field(0.0, ge=0.0, le=10.0)


class TrainingStats(BaseModel):
    total_outcomes: int
    outcomes_active: int
    outcomes_closed: int
    wins: int = 0
    losses: int = 0
    overall_win_rate: Optional[float] = None
    avg_realized_rr: Optional[float] = None
    feedback_count: int
    avg_accuracy_rating: Optional[float] = None
    avg_usefulness_rating: Optional[float] = None
    by_timeframe: dict = {}
    by_direction: dict = {}
    by_status: dict = {}
    few_shot_count_active: int = 0
    few_shot_total_uses: int = 0
    classifier_trained: bool = False
    classifier_accuracy: Optional[float] = None
    classifier_trained_at: Optional[str] = None
    classifier_samples: int = 0
    vector_store: dict = {}


class DashboardStats(BaseModel):
    """Owner dashboard summary."""
    total_analyses: int
    total_cost_usd: float
    analyses_this_month: int
    cost_this_month: float
    by_timeframe: dict = {}
    by_bias: dict = {}
    last_analysis_at: Optional[datetime] = None

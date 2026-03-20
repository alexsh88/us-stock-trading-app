import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.models.analysis import RunStatus


class AnalysisRunRequest(BaseModel):
    top_n: int = Field(default=5, ge=1, le=50)
    mode: str = Field(default="swing", pattern="^(swing|intraday)$")


class AnalysisRunResponse(BaseModel):
    id: uuid.UUID
    status: RunStatus
    top_n: int
    mode: str
    tickers_screened: Optional[int] = None
    signals_generated: Optional[int] = None
    error_message: Optional[str] = None
    celery_task_id: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AgentScores(BaseModel):
    technical: Optional[float] = None
    fundamental: Optional[float] = None
    sentiment: Optional[float] = None
    catalyst: Optional[float] = None


class TechnicalIndicators(BaseModel):
    adx: Optional[float] = None
    regime: Optional[str] = None           # "trending" | "neutral" | "choppy"
    mtf_aligned: Optional[bool] = None
    bb_squeeze: Optional[bool] = None
    squeeze_released: Optional[bool] = None
    breakout_score: Optional[int] = None   # 0–3
    breakout_details: Optional[str] = None
    vol_ratio: Optional[float] = None
    swing_resistance: Optional[float] = None
    swing_support: Optional[float] = None
    rsi: Optional[float] = None
    macd_signal: Optional[str] = None      # "bullish" | "bearish"
    bb_position: Optional[str] = None
    vwap_relation: Optional[str] = None
    stop_loss_method: Optional[str] = None  # e.g. "Fib61.8($142.30)", "Chandelier-2.5x"
    target_method: Optional[str] = None     # e.g. "pattern-double_bottom", "WeeklyR1", "Fib127"


class TradeSignalResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    ticker: str
    decision: str
    confidence_score: float
    trading_mode: str
    entry_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    stop_loss_method: Optional[str] = None
    take_profit_price: Optional[float] = None
    take_profit_price_2: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    position_size_pct: Optional[float] = None
    agent_scores: AgentScores = AgentScores()
    indicators: Optional[TechnicalIndicators] = None
    key_risks: list[str] = []
    reasoning: Optional[str] = None
    detected_patterns: Optional[dict] = None
    is_paper: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_scores(cls, signal: object) -> "TradeSignalResponse":
        s = signal
        ind = None
        if s.indicators:
            ind = TechnicalIndicators(**{k: v for k, v in s.indicators.items() if k in TechnicalIndicators.model_fields})
        return cls(
            id=s.id,
            run_id=s.run_id,
            ticker=s.ticker,
            decision=s.decision,
            confidence_score=s.confidence_score,
            trading_mode=s.trading_mode,
            entry_price=s.entry_price,
            stop_loss_price=s.stop_loss_price,
            stop_loss_method=s.stop_loss_method,
            take_profit_price=s.take_profit_price,
            take_profit_price_2=s.take_profit_price_2,
            risk_reward_ratio=s.risk_reward_ratio,
            position_size_pct=s.position_size_pct,
            agent_scores=AgentScores(
                technical=s.technical_score,
                fundamental=s.fundamental_score,
                sentiment=s.sentiment_score,
                catalyst=s.catalyst_score,
            ),
            indicators=ind,
            key_risks=s.key_risks or [],
            reasoning=s.reasoning,
            detected_patterns=s.detected_patterns,
            is_paper=s.is_paper,
            created_at=s.created_at,
        )

import uuid
import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Boolean, Enum as SAEnum, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class TradeDecision(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    SKIP = "SKIP"


class TradingMode(str, enum.Enum):
    SWING = "swing"
    INTRADAY = "intraday"


class TradeSignal(Base):
    __tablename__ = "trade_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_runs.id"))
    ticker: Mapped[str] = mapped_column(String(10))
    decision: Mapped[TradeDecision] = mapped_column(SAEnum(TradeDecision))
    confidence_score: Mapped[float] = mapped_column(Float)
    trading_mode: Mapped[TradingMode] = mapped_column(SAEnum(TradingMode))

    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss_method: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    take_profit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit_price_2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_reward_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    position_size_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    technical_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fundamental_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    catalyst_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    key_risks: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(String(5000), nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)

    # Rich technical metadata: adx, regime, mtf_aligned, bb_squeeze, breakout_score, etc.
    indicators: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Chart pattern detection results (all bullish/bearish patterns found for this ticker)
    detected_patterns: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["AnalysisRun"] = relationship("AnalysisRun", back_populates="signals")  # type: ignore[name-defined]

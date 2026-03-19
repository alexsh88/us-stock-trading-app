import uuid
import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Boolean, Integer, Enum as SAEnum, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class SignalOutcome(Base):
    """Actual outcome for each trade signal, populated nightly by backtest task."""
    __tablename__ = "signal_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trade_signals.id"), unique=True)
    ticker: Mapped[str] = mapped_column(String(10))

    # Signal metadata (denormalized for fast analytics queries)
    signal_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decision: Mapped[str] = mapped_column(String(10))  # BUY / SELL / HOLD
    confidence_score: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    technical_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fundamental_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    catalyst_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trading_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Actual price outcomes at multiple horizons
    price_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_2d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_3d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_5d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Return at each horizon
    return_1d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_2d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_3d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_5d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # SL/TP hit detection (uses OHLC High/Low — more accurate than Close only)
    sl_hit: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    tp_hit: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    sl_hit_day: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # which day (1-5) SL was hit
    tp_hit_day: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # which day (1-5) TP was hit

    # R-multiple: actual PnL / initial risk
    r_multiple: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Direction accuracy: did price go the right way at each horizon?
    correct_direction_1d: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    correct_direction_3d: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    correct_direction_5d: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)  # False until all 5 days filled


class FactorIC(Base):
    """Daily Information Coefficient for each agent factor score.
    Spearman rank correlation between score and forward return.
    """
    __tablename__ = "factor_ic"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    factor: Mapped[str] = mapped_column(String(30))   # technical, fundamental, sentiment, catalyst, confidence
    horizon: Mapped[int] = mapped_column(Integer)     # 1, 2, 3, or 5 (days)
    trading_mode: Mapped[str] = mapped_column(String(20), default="swing")

    ic: Mapped[float] = mapped_column(Float)          # Spearman correlation
    n_signals: Mapped[int] = mapped_column(Integer)   # sample size
    ic_mean_30d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # rolling 30-day IC mean
    ic_ir: Mapped[Optional[float]] = mapped_column(Float, nullable=True)         # IC / IC_std (information ratio)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

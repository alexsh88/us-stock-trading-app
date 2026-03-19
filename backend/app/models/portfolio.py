import uuid
import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Boolean, Integer, Enum as SAEnum, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class PositionStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)
    initial_capital: Mapped[float] = mapped_column(Float, default=100000.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    positions: Mapped[list["Position"]] = relationship("Position", back_populates="portfolio")


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("portfolios.id"))
    signal_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("trade_signals.id"), nullable=True)
    ticker: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # stop_loss | take_profit | manual
    status: Mapped[PositionStatus] = mapped_column(SAEnum(PositionStatus), default=PositionStatus.OPEN)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    portfolio: Mapped["Portfolio"] = relationship("Portfolio", back_populates="positions")

    @property
    def unrealized_pnl(self) -> Optional[float]:
        if self.current_price and self.status == PositionStatus.OPEN:
            return (self.current_price - self.entry_price) * self.quantity
        return None

    @property
    def realized_pnl(self) -> Optional[float]:
        if self.exit_price and self.status == PositionStatus.CLOSED:
            return (self.exit_price - self.entry_price) * self.quantity
        return None

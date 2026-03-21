import uuid
import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Boolean, Integer, Enum as SAEnum, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class IbkrOrderType(str, enum.Enum):
    PARENT = "PARENT"           # Entry limit order
    STOP = "STOP"               # Stop-loss order (linked to parent)
    TAKE_PROFIT = "TAKE_PROFIT" # T1 limit sell (50% qty)
    TAKE_PROFIT_2 = "TAKE_PROFIT_2"  # T2 limit sell (25% qty, placed after T1 fills)


class IbkrOrderStatus(str, enum.Enum):
    SUBMITTED = "Submitted"
    PRESUBMITTED = "PreSubmitted"
    FILLED = "Filled"
    CANCELLED = "Cancelled"
    INACTIVE = "Inactive"
    UNKNOWN = "Unknown"


class IbkrOrder(Base):
    __tablename__ = "ibkr_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    position_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("positions.id"), nullable=True)
    signal_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("trade_signals.id"), nullable=True)

    ticker: Mapped[str] = mapped_column(String(10))
    order_type: Mapped[IbkrOrderType] = mapped_column(SAEnum(IbkrOrderType))
    action: Mapped[str] = mapped_column(String(10))       # BUY or SELL
    quantity: Mapped[int] = mapped_column(Integer)
    limit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # TWS IDs — orderId is transient (changes on reconnect), permId is stable
    tws_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tws_perm_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Parent orderId for linked stop/TP orders (for cancellation)
    parent_tws_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    status: Mapped[IbkrOrderStatus] = mapped_column(
        SAEnum(IbkrOrderStatus), default=IbkrOrderStatus.SUBMITTED
    )
    filled_qty: Mapped[int] = mapped_column(Integer, default=0)
    avg_fill_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

import uuid
import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Enum as SAEnum, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class RunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[RunStatus] = mapped_column(SAEnum(RunStatus), default=RunStatus.PENDING)
    top_n: Mapped[int] = mapped_column(Integer, default=5)
    mode: Mapped[str] = mapped_column(String(20), default="swing")
    tickers_screened: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    signals_generated: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    signals: Mapped[list["TradeSignal"]] = relationship("TradeSignal", back_populates="run")  # type: ignore[name-defined]

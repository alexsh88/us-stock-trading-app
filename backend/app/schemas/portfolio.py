import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PortfolioResponse(BaseModel):
    id: uuid.UUID
    name: str
    is_paper: bool
    initial_capital: float
    created_at: datetime

    model_config = {"from_attributes": True}


class PositionResponse(BaseModel):
    id: uuid.UUID
    portfolio_id: uuid.UUID
    ticker: str
    quantity: int
    entry_price: float
    stop_loss_price: Optional[float] = None
    stop_loss_method: Optional[str] = None
    take_profit_price: Optional[float] = None
    target2_price: Optional[float] = None
    scale_out_stage: int = 0
    partial_realized_pnl: Optional[float] = None
    current_price: Optional[float] = None
    exit_price: Optional[float] = None
    close_reason: Optional[str] = None
    status: str
    is_paper: bool
    unrealized_pnl: Optional[float] = None
    realized_pnl: Optional[float] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    ibkr_parent_order_id: Optional[int] = None
    ibkr_stop_order_id: Optional[int] = None
    ibkr_tp1_order_id: Optional[int] = None
    ibkr_tp2_order_id: Optional[int] = None

    model_config = {"from_attributes": True}


class OpenPositionRequest(BaseModel):
    portfolio_id: uuid.UUID
    signal_id: Optional[uuid.UUID] = None
    ticker: str
    quantity: int
    entry_price: float
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    target2_price: Optional[float] = None
    is_paper: bool = True

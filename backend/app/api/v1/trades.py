import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_db_session
from app.models.portfolio import Position, PositionStatus, Portfolio
from app.schemas.portfolio import PositionResponse, OpenPositionRequest

logger = structlog.get_logger()
router = APIRouter()


@router.post("/paper", response_model=PositionResponse, status_code=201)
async def open_paper_trade(
    request: OpenPositionRequest,
    db: AsyncSession = Depends(get_db_session),
):
    request.is_paper = True  # Force paper mode for this endpoint
    position = Position(
        portfolio_id=request.portfolio_id,
        signal_id=request.signal_id,
        ticker=request.ticker,
        quantity=request.quantity,
        entry_price=request.entry_price,
        stop_loss_price=request.stop_loss_price,
        take_profit_price=request.take_profit_price,
        is_paper=True,
    )
    db.add(position)
    await db.commit()
    await db.refresh(position)
    return position


@router.get("/paper", response_model=list[PositionResponse])
async def list_paper_trades(
    portfolio_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    query = select(Position).where(Position.is_paper == True)  # noqa: E712
    if portfolio_id:
        query = query.where(Position.portfolio_id == portfolio_id)
    result = await db.execute(query.order_by(Position.opened_at.desc()))
    return result.scalars().all()


@router.patch("/paper/{position_id}/close", response_model=PositionResponse)
async def close_paper_trade(
    position_id: uuid.UUID,
    exit_price: float,
    close_reason: str = "manual",
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(
        select(Position).where(Position.id == position_id, Position.is_paper == True)  # noqa: E712
    )
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=404, detail="Paper position not found")
    if position.status == PositionStatus.CLOSED:
        raise HTTPException(status_code=400, detail="Position already closed")

    from datetime import datetime, timezone
    position.exit_price = exit_price
    position.status = PositionStatus.CLOSED
    position.close_reason = close_reason
    position.closed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(position)
    return position

import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_db_session
from app.models.portfolio import Portfolio, Position, PositionStatus
from app.schemas.portfolio import PortfolioResponse, PositionResponse

logger = structlog.get_logger()
router = APIRouter()


@router.get("/", response_model=list[PortfolioResponse])
async def list_portfolios(db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Portfolio).order_by(Portfolio.created_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=PortfolioResponse, status_code=201)
async def create_portfolio(
    name: str,
    is_paper: bool = True,
    initial_capital: float = 100000.0,
    db: AsyncSession = Depends(get_db_session),
):
    portfolio = Portfolio(name=name, is_paper=is_paper, initial_capital=initial_capital)
    db.add(portfolio)
    await db.commit()
    await db.refresh(portfolio)
    return portfolio


@router.get("/{portfolio_id}/positions", response_model=list[PositionResponse])
async def get_portfolio_positions(
    portfolio_id: uuid.UUID,
    status: str | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    query = select(Position).where(Position.portfolio_id == portfolio_id)
    if status:
        query = query.where(Position.status == status)
    result = await db.execute(query.order_by(Position.opened_at.desc()))
    return result.scalars().all()


@router.get("/{portfolio_id}/summary")
async def get_portfolio_summary(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    positions_result = await db.execute(
        select(Position).where(Position.portfolio_id == portfolio_id)
    )
    positions = positions_result.scalars().all()

    open_positions = [p for p in positions if p.status == PositionStatus.OPEN]
    closed_positions = [p for p in positions if p.status == PositionStatus.CLOSED]

    total_realized_pnl = sum(p.realized_pnl or 0 for p in closed_positions)
    total_unrealized_pnl = sum(p.unrealized_pnl or 0 for p in open_positions)
    winning_trades = [p for p in closed_positions if (p.realized_pnl or 0) > 0]
    win_rate = len(winning_trades) / len(closed_positions) if closed_positions else 0

    # R-multiple: realized_pnl / initial_risk per trade
    # initial_risk = (entry - stop) * qty; if no stop, assume 5% of entry
    r_multiples = []
    for p in closed_positions:
        pnl = p.realized_pnl
        if pnl is None:
            continue
        stop = p.stop_loss_price or (p.entry_price * 0.95)
        risk = (p.entry_price - stop) * p.quantity
        if risk > 0:
            r_multiples.append(pnl / risk)

    avg_r_multiple = round(sum(r_multiples) / len(r_multiples), 2) if r_multiples else None
    stop_loss_hits = sum(1 for p in closed_positions if p.close_reason == "stop_loss")
    take_profit_hits = sum(1 for p in closed_positions if p.close_reason == "take_profit")

    return {
        "portfolio_id": str(portfolio_id),
        "name": portfolio.name,
        "is_paper": portfolio.is_paper,
        "initial_capital": portfolio.initial_capital,
        "open_positions": len(open_positions),
        "closed_positions": len(closed_positions),
        "total_realized_pnl": round(total_realized_pnl, 2),
        "total_unrealized_pnl": round(total_unrealized_pnl, 2),
        "win_rate": round(win_rate, 4),
        "avg_r_multiple": avg_r_multiple,
        "stop_loss_hits": stop_loss_hits,
        "take_profit_hits": take_profit_hits,
    }

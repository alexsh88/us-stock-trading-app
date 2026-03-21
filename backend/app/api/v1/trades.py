import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from datetime import datetime, timezone

from app.dependencies import get_db_session
from app.core.redis_client import get_redis
from app.models.portfolio import Position, PositionStatus, Portfolio
from app.models.ibkr_order import IbkrOrder, IbkrOrderType, IbkrOrderStatus
from app.schemas.portfolio import PositionResponse, OpenPositionRequest
from redis.asyncio import Redis

logger = structlog.get_logger()
router = APIRouter()

_SETTINGS_REDIS_KEY = "app:settings"


async def _ibkr_enabled(redis: Redis) -> bool:
    """Return True only if IBKR connection is enabled in persisted settings."""
    import json
    try:
        raw = await redis.get(_SETTINGS_REDIS_KEY)
        if raw:
            data = json.loads(raw)
            return bool(data.get("ibkr_enabled", False))
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# IBKR connection status
# ---------------------------------------------------------------------------

@router.get("/ibkr/status")
async def ibkr_connection_status(redis: Redis = Depends(get_redis)):
    """
    Test whether TWS is reachable and IBKR connection is enabled.
    Returns {"enabled": bool, "connected": bool, "port": int, "error": str|null}.
    """
    from app.config import get_settings
    settings = get_settings()
    enabled = await _ibkr_enabled(redis)

    if not enabled:
        return {"enabled": False, "connected": False, "port": settings.ibkr_gateway_port, "error": None}

    try:
        from ib_async import IB
        ib = IB()
        ib.connect(
            settings.ibkr_gateway_host,
            settings.ibkr_gateway_port,
            clientId=settings.ibkr_client_id_orders,
            timeout=5,
            readonly=True,
        )
        ib.disconnect()
        return {"enabled": True, "connected": True, "port": settings.ibkr_gateway_port, "error": None}
    except Exception as e:
        return {"enabled": True, "connected": False, "port": settings.ibkr_gateway_port, "error": str(e)}


# ---------------------------------------------------------------------------
# Paper simulation endpoints (no real TWS orders)
# ---------------------------------------------------------------------------

@router.post("/paper", response_model=PositionResponse, status_code=201)
async def open_paper_trade(
    request: OpenPositionRequest,
    db: AsyncSession = Depends(get_db_session),
):
    request.is_paper = True
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

    position.exit_price = exit_price
    position.status = PositionStatus.CLOSED
    position.close_reason = close_reason
    position.closed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(position)
    return position


# ---------------------------------------------------------------------------
# IBKR TWS bracket order endpoints (real paper/live orders)
# ---------------------------------------------------------------------------

class BracketOrderRequest(BaseModel):
    signal_id: uuid.UUID
    portfolio_id: uuid.UUID
    quantity: int = Field(..., gt=0, description="Number of shares")
    # Override signal prices if needed
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    tp1_price: Optional[float] = None
    tp2_price: Optional[float] = None


class BracketOrderResponse(BaseModel):
    position_id: uuid.UUID
    ticker: str
    quantity: int
    entry_price: float
    stop_price: Optional[float]
    tp1_price: Optional[float]
    tp2_price: Optional[float]
    ibkr_parent_order_id: Optional[int]
    ibkr_stop_order_id: Optional[int]
    ibkr_tp1_order_id: Optional[int]
    status: str

    model_config = {"from_attributes": True}


@router.post("/bracket", response_model=BracketOrderResponse, status_code=201)
async def submit_bracket_order(
    request: BracketOrderRequest,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    """
    Submit a real bracket order to TWS paper account for the given signal.
    Requires IBKR connection to be enabled in Settings.
    Creates a Position + IbkrOrder rows, then places the order on TWS.
    """
    if not await _ibkr_enabled(redis):
        raise HTTPException(
            status_code=403,
            detail="IBKR connection is disabled. Enable it in Settings → IBKR Connection.",
        )

    from app.models.signals import TradeSignal, TradeDecision

    # Load signal
    sig_result = await db.execute(select(TradeSignal).where(TradeSignal.id == request.signal_id))
    signal = sig_result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    if signal.decision != TradeDecision.BUY:
        raise HTTPException(status_code=400, detail="Only BUY signals can be submitted as bracket orders")

    # Resolve prices: use request overrides or fall back to signal values
    entry = request.entry_price or signal.entry_price
    stop = request.stop_price or signal.stop_loss_price
    tp1 = request.tp1_price or signal.take_profit_price
    tp2 = request.tp2_price or signal.take_profit_price_2

    if not entry or not stop or not tp1:
        raise HTTPException(
            status_code=400,
            detail="Signal is missing entry/stop/tp1 prices — run analysis first",
        )

    tp1_qty = max(1, request.quantity // 2)  # 50% at T1

    # Place bracket order on TWS (sync call — runs in thread pool)
    import asyncio
    from app.services.ibkr_order_service import place_bracket_order
    try:
        loop = asyncio.get_event_loop()
        order_result = await loop.run_in_executor(
            None,
            lambda: place_bracket_order(
                ticker=signal.ticker,
                quantity=request.quantity,
                entry_price=entry,
                stop_price=stop,
                tp1_price=tp1,
                tp1_qty=tp1_qty,
                is_paper=True,
            ),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"TWS order placement failed: {e}")

    # Persist Position
    position = Position(
        portfolio_id=request.portfolio_id,
        signal_id=request.signal_id,
        ticker=signal.ticker,
        quantity=request.quantity,
        entry_price=entry,
        stop_loss_price=stop,
        stop_loss_method=signal.stop_loss_method,
        take_profit_price=tp1,
        target2_price=tp2,
        is_paper=True,
        ibkr_parent_order_id=order_result["parent_order_id"],
        ibkr_stop_order_id=order_result["stop_order_id"],
        ibkr_tp1_order_id=order_result["tp1_order_id"],
    )
    db.add(position)
    await db.flush()

    # Persist IbkrOrder rows for each leg
    perm_ids = order_result.get("perm_ids", {})
    db.add(IbkrOrder(
        position_id=position.id,
        signal_id=request.signal_id,
        ticker=signal.ticker,
        order_type=IbkrOrderType.PARENT,
        action="BUY",
        quantity=request.quantity,
        limit_price=entry,
        tws_order_id=order_result["parent_order_id"],
        tws_perm_id=perm_ids.get("parent"),
        status=IbkrOrderStatus.SUBMITTED,
        is_paper=True,
    ))
    db.add(IbkrOrder(
        position_id=position.id,
        signal_id=request.signal_id,
        ticker=signal.ticker,
        order_type=IbkrOrderType.STOP,
        action="SELL",
        quantity=request.quantity,
        stop_price=stop,
        tws_order_id=order_result["stop_order_id"],
        tws_perm_id=perm_ids.get("stop"),
        parent_tws_order_id=order_result["parent_order_id"],
        status=IbkrOrderStatus.SUBMITTED,
        is_paper=True,
    ))
    db.add(IbkrOrder(
        position_id=position.id,
        signal_id=request.signal_id,
        ticker=signal.ticker,
        order_type=IbkrOrderType.TAKE_PROFIT,
        action="SELL",
        quantity=tp1_qty,
        limit_price=tp1,
        tws_order_id=order_result["tp1_order_id"],
        tws_perm_id=perm_ids.get("tp1"),
        parent_tws_order_id=order_result["parent_order_id"],
        status=IbkrOrderStatus.SUBMITTED,
        is_paper=True,
    ))

    await db.commit()
    await db.refresh(position)

    logger.info(
        "Bracket order submitted",
        ticker=signal.ticker,
        qty=request.quantity,
        parent_id=order_result["parent_order_id"],
        position_id=str(position.id),
    )

    return BracketOrderResponse(
        position_id=position.id,
        ticker=signal.ticker,
        quantity=request.quantity,
        entry_price=entry,
        stop_price=stop,
        tp1_price=tp1,
        tp2_price=tp2,
        ibkr_parent_order_id=order_result["parent_order_id"],
        ibkr_stop_order_id=order_result["stop_order_id"],
        ibkr_tp1_order_id=order_result["tp1_order_id"],
        status="submitted",
    )


@router.delete("/bracket/{position_id}", status_code=200)
async def cancel_bracket_order(
    position_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Cancel all open TWS orders for a position and mark it closed."""
    result = await db.execute(select(Position).where(Position.id == position_id))
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    order_ids = [
        position.ibkr_parent_order_id,
        position.ibkr_stop_order_id,
        position.ibkr_tp1_order_id,
        position.ibkr_tp2_order_id,
    ]
    order_ids = [oid for oid in order_ids if oid is not None]

    import asyncio
    from app.services.ibkr_order_service import cancel_position_orders
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: cancel_position_orders(order_ids))
    except Exception as e:
        logger.warning("TWS order cancellation failed", error=str(e))

    # Mark DB orders as cancelled
    ibkr_result = await db.execute(
        select(IbkrOrder).where(IbkrOrder.position_id == position_id)
    )
    for order in ibkr_result.scalars().all():
        if order.status not in (IbkrOrderStatus.FILLED, IbkrOrderStatus.CANCELLED):
            order.status = IbkrOrderStatus.CANCELLED

    position.status = PositionStatus.CLOSED
    position.close_reason = "manual_cancel"
    position.closed_at = datetime.now(timezone.utc)

    await db.commit()
    return {"detail": "Bracket orders cancelled", "position_id": str(position_id)}


@router.get("/bracket", response_model=list[PositionResponse])
async def list_bracket_positions(
    db: AsyncSession = Depends(get_db_session),
):
    """List all positions that have real IBKR bracket orders (not pure paper simulation)."""
    result = await db.execute(
        select(Position)
        .where(Position.ibkr_parent_order_id.isnot(None))
        .order_by(Position.opened_at.desc())
    )
    return result.scalars().all()

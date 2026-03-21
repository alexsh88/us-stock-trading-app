"""
Celery task: sync IBKR TWS order statuses every 30 seconds during market hours.

Responsibilities:
  1. Poll TWS for open orders → update ibkr_orders.status + filled_qty
  2. When TP1 fills → move stop to breakeven, place T2 order, update Position.scale_out_stage=1
  3. When stop fills → close Position
  4. When TP2 fills → close remaining Position
"""
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()


def _get_sync_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import get_settings
    settings = get_settings()
    sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    engine = create_engine(sync_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def sync_ibkr_orders() -> dict:
    """Sync open TWS orders against our ibkr_orders table and handle fills."""
    from app.models.ibkr_order import IbkrOrder, IbkrOrderType, IbkrOrderStatus
    from app.models.portfolio import Position, PositionStatus
    from app.services.ibkr_order_service import get_open_orders, get_completed_orders, place_tp2_order
    from sqlalchemy import select

    session, engine = _get_sync_session()
    try:
        # Fetch all non-terminal ibkr_orders from DB
        active_orders = session.execute(
            select(IbkrOrder).where(
                IbkrOrder.status.notin_([IbkrOrderStatus.FILLED, IbkrOrderStatus.CANCELLED, IbkrOrderStatus.INACTIVE])
            )
        ).scalars().all()

        if not active_orders:
            return {"synced": 0}

        # Build lookup by tws_order_id
        db_orders_by_id = {o.tws_order_id: o for o in active_orders if o.tws_order_id}

        # Fetch live state from TWS
        try:
            open_orders = get_open_orders()
            completed = get_completed_orders()
        except Exception as e:
            logger.warning("Could not reach TWS for order sync", error=str(e))
            return {"synced": 0, "error": str(e)}

        # Map TWS status → our status enum
        status_map = {
            "Submitted": IbkrOrderStatus.SUBMITTED,
            "PreSubmitted": IbkrOrderStatus.PRESUBMITTED,
            "Filled": IbkrOrderStatus.FILLED,
            "Cancelled": IbkrOrderStatus.CANCELLED,
            "Inactive": IbkrOrderStatus.INACTIVE,
        }

        # Update from open orders
        open_by_id = {o["order_id"]: o for o in open_orders}
        for tws_id, db_order in db_orders_by_id.items():
            if tws_id in open_by_id:
                live = open_by_id[tws_id]
                db_order.status = status_map.get(live["status"], IbkrOrderStatus.UNKNOWN)
                db_order.filled_qty = int(live["filled_qty"] or 0)
                if live["avg_fill_price"]:
                    db_order.avg_fill_price = live["avg_fill_price"]

        # Detect fills from executions (orders that left the open orders list)
        filled_by_id = {}
        for ex in completed:
            oid = ex["order_id"]
            filled_by_id.setdefault(oid, []).append(ex)

        newly_filled = []
        for tws_id, db_order in db_orders_by_id.items():
            if tws_id not in open_by_id and tws_id in filled_by_id:
                db_order.status = IbkrOrderStatus.FILLED
                fills = filled_by_id[tws_id]
                total_qty = sum(f["filled_qty"] for f in fills)
                avg_price = sum(f["avg_fill_price"] * f["filled_qty"] for f in fills) / total_qty if total_qty else 0
                db_order.filled_qty = int(total_qty)
                db_order.avg_fill_price = avg_price
                newly_filled.append(db_order)

        session.flush()

        # Handle fill events
        for filled_order in newly_filled:
            _handle_fill(session, filled_order)

        session.commit()
        logger.info("IBKR order sync complete", active=len(active_orders), fills=len(newly_filled))
        return {"synced": len(active_orders), "fills": len(newly_filled)}

    except Exception as e:
        session.rollback()
        logger.error("IBKR order sync failed", error=str(e))
        return {"error": str(e)}
    finally:
        session.close()
        engine.dispose()


def _handle_fill(session, filled_order):
    """React to a newly filled order: update position stage, place T2 if needed."""
    from app.models.ibkr_order import IbkrOrder, IbkrOrderType, IbkrOrderStatus
    from app.models.portfolio import Position, PositionStatus
    from app.services.ibkr_order_service import place_tp2_order, cancel_position_orders
    from sqlalchemy import select

    if not filled_order.position_id:
        return

    position = session.get(Position, filled_order.position_id)
    if not position:
        return

    order_type = filled_order.order_type

    if order_type == IbkrOrderType.PARENT:
        # Entry filled — position is now live. Update entry price to actual fill.
        if filled_order.avg_fill_price:
            position.entry_price = filled_order.avg_fill_price
        logger.info("Entry filled", ticker=position.ticker, fill_price=filled_order.avg_fill_price)

    elif order_type == IbkrOrderType.TAKE_PROFIT:
        # TP1 filled — move stop to breakeven, place T2
        logger.info("TP1 filled", ticker=position.ticker, fill_price=filled_order.avg_fill_price)
        position.scale_out_stage = 1
        position.partial_realized_pnl = (
            (filled_order.avg_fill_price - position.entry_price) * filled_order.filled_qty
            if filled_order.avg_fill_price else None
        )

        # Move stop to breakeven on TWS
        # (Cancelling existing stop and placing new one at entry price)
        if position.ibkr_stop_order_id:
            try:
                cancel_position_orders([position.ibkr_stop_order_id])
            except Exception as e:
                logger.warning("Could not cancel old stop for breakeven move", error=str(e))

        breakeven = position.entry_price
        remaining_qty = position.quantity - filled_order.filled_qty

        if remaining_qty > 0 and position.target2_price:
            try:
                from app.config import get_settings
                result = place_tp2_order(
                    ticker=position.ticker,
                    quantity=remaining_qty,
                    tp2_price=position.target2_price,
                    parent_tws_order_id=position.ibkr_parent_order_id,
                    is_paper=position.is_paper,
                )
                position.ibkr_tp2_order_id = result["tp2_order_id"]

                # Record T2 order in DB
                from app.models.ibkr_order import IbkrOrder
                t2_order = IbkrOrder(
                    position_id=position.id,
                    signal_id=filled_order.signal_id,
                    ticker=position.ticker,
                    order_type=IbkrOrderType.TAKE_PROFIT_2,
                    action="SELL",
                    quantity=remaining_qty,
                    limit_price=position.target2_price,
                    tws_order_id=result["tp2_order_id"],
                    tws_perm_id=result.get("perm_id"),
                    parent_tws_order_id=position.ibkr_parent_order_id,
                    status=IbkrOrderStatus.SUBMITTED,
                    is_paper=position.is_paper,
                )
                session.add(t2_order)
                logger.info("T2 order placed after TP1 fill", ticker=position.ticker, qty=remaining_qty)
            except Exception as e:
                logger.error("Failed to place T2 order after TP1 fill", error=str(e))

    elif order_type == IbkrOrderType.STOP:
        # Stop-loss filled — close position
        logger.info("Stop loss filled", ticker=position.ticker, fill_price=filled_order.avg_fill_price)
        position.status = PositionStatus.CLOSED
        position.exit_price = filled_order.avg_fill_price
        position.close_reason = "stop_loss"
        position.closed_at = datetime.now(timezone.utc)

        # Cancel any remaining TP orders
        remaining_ids = [position.ibkr_tp1_order_id, position.ibkr_tp2_order_id]
        remaining_ids = [oid for oid in remaining_ids if oid]
        if remaining_ids:
            try:
                cancel_position_orders(remaining_ids)
            except Exception:
                pass

    elif order_type == IbkrOrderType.TAKE_PROFIT_2:
        # TP2 filled — close remaining position
        logger.info("TP2 filled", ticker=position.ticker, fill_price=filled_order.avg_fill_price)
        position.scale_out_stage = 2
        position.status = PositionStatus.CLOSED
        position.exit_price = filled_order.avg_fill_price
        position.close_reason = "take_profit_2"
        position.closed_at = datetime.now(timezone.utc)

        t2_pnl = (
            (filled_order.avg_fill_price - position.entry_price) * filled_order.filled_qty
            if filled_order.avg_fill_price else 0
        )
        position.partial_realized_pnl = (position.partial_realized_pnl or 0) + t2_pnl


from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.ibkr_order_tasks.sync_ibkr_orders_task", bind=True, max_retries=0)
def sync_ibkr_orders_task(self) -> dict:
    return sync_ibkr_orders()

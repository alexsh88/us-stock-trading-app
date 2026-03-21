"""
IBKR bracket order placement via ib_async.

Connects to TWS (paper: 7497, live: 7496) or IB Gateway (paper: 4002, live: 4001).
Uses a separate clientId from data services to avoid order-management conflicts.

Bracket order structure:
  Parent: LMT BUY  full_qty  @ entry_price
  Stop:   STP SELL full_qty  @ stop_price     (linked to parent, OCO with TP1)
  TP1:    LMT SELL tp1_qty   @ tp1_price      (50% — scale-out stage 1)

T2 is placed separately after TP1 fills (detected by sync task).
"""
import structlog
from typing import Optional

logger = structlog.get_logger()


def _connect_ib(settings, client_id: int, timeout: int = 10):
    from ib_async import IB
    ib = IB()
    ib.connect(
        settings.ibkr_gateway_host,
        settings.ibkr_gateway_port,
        clientId=client_id,
        timeout=timeout,
        readonly=False,
    )
    return ib


def place_bracket_order(
    ticker: str,
    quantity: int,
    entry_price: float,
    stop_price: float,
    tp1_price: float,
    tp1_qty: Optional[int] = None,      # defaults to 50% of quantity
    is_paper: bool = True,
) -> dict:
    """
    Place a bracket order on TWS.

    Returns:
        {
          "parent_order_id": int,
          "stop_order_id": int,
          "tp1_order_id": int,
          "perm_ids": {parent: int, stop: int, tp1: int},
          "status": "submitted",
        }

    Raises RuntimeError on any failure (caller should catch and surface as HTTP 502).
    """
    try:
        from ib_async import IB, Stock, LimitOrder, StopOrder, Order
        from app.config import get_settings
    except ImportError as e:
        raise RuntimeError(f"ib_async not installed: {e}")

    settings = get_settings()
    if tp1_qty is None:
        tp1_qty = max(1, quantity // 2)

    ib = _connect_ib(settings, client_id=settings.ibkr_client_id_orders)
    try:
        contract = Stock(ticker, "SMART", "USD")
        ib.qualifyContracts(contract)
        if not contract.conId:
            raise RuntimeError(f"Could not qualify contract for {ticker}")

        # Build bracket: parent LMT buy → stop + take-profit linked via OCA
        bracket = ib.bracketOrder(
            action="BUY",
            quantity=quantity,
            limitPrice=round(entry_price, 2),
            takeProfitPrice=round(tp1_price, 2),
            stopLossPrice=round(stop_price, 2),
        )
        # bracket[0] = parent, bracket[1] = take-profit, bracket[2] = stop-loss
        parent_order, tp1_order, stop_order = bracket

        # Adjust TP1 quantity to tp1_qty (partial exit, not full position)
        tp1_order.totalQuantity = tp1_qty

        # Place all three
        parent_trade = ib.placeOrder(contract, parent_order)
        tp1_trade = ib.placeOrder(contract, tp1_order)
        stop_trade = ib.placeOrder(contract, stop_order)

        # Wait briefly for TWS to assign order IDs
        ib.sleep(1.0)

        result = {
            "parent_order_id": parent_order.orderId,
            "stop_order_id": stop_order.orderId,
            "tp1_order_id": tp1_order.orderId,
            "perm_ids": {
                "parent": parent_order.permId,
                "stop": stop_order.permId,
                "tp1": tp1_order.permId,
            },
            "status": "submitted",
        }

        logger.info(
            "Bracket order placed",
            ticker=ticker,
            qty=quantity,
            entry=entry_price,
            stop=stop_price,
            tp1=tp1_price,
            tp1_qty=tp1_qty,
            parent_id=parent_order.orderId,
            is_paper=is_paper,
        )
        return result

    finally:
        ib.disconnect()


def place_tp2_order(
    ticker: str,
    quantity: int,
    tp2_price: float,
    parent_tws_order_id: int,
    is_paper: bool = True,
) -> dict:
    """
    Place a standalone T2 limit sell order (called after T1 fills).
    Returns {"tp2_order_id": int, "perm_id": int}.
    """
    try:
        from ib_async import IB, Stock, LimitOrder
        from app.config import get_settings
    except ImportError as e:
        raise RuntimeError(f"ib_async not installed: {e}")

    settings = get_settings()
    ib = _connect_ib(settings, client_id=settings.ibkr_client_id_orders)
    try:
        contract = Stock(ticker, "SMART", "USD")
        ib.qualifyContracts(contract)
        if not contract.conId:
            raise RuntimeError(f"Could not qualify contract for {ticker}")

        order = LimitOrder(
            action="SELL",
            totalQuantity=quantity,
            lmtPrice=round(tp2_price, 2),
        )
        trade = ib.placeOrder(contract, order)
        ib.sleep(1.0)

        logger.info("T2 order placed", ticker=ticker, qty=quantity, tp2=tp2_price)
        return {"tp2_order_id": order.orderId, "perm_id": order.permId}
    finally:
        ib.disconnect()


def cancel_position_orders(order_ids: list[int]) -> None:
    """Cancel all open orders for a position by TWS order ID."""
    try:
        from ib_async import IB, Order
        from app.config import get_settings
    except ImportError:
        return

    if not order_ids:
        return

    settings = get_settings()
    ib = _connect_ib(settings, client_id=settings.ibkr_client_id_orders)
    try:
        open_orders = ib.reqOpenOrders()
        open_ids = {o.order.orderId for o in open_orders}
        for oid in order_ids:
            if oid and oid in open_ids:
                cancel_order = Order()
                cancel_order.orderId = oid
                ib.cancelOrder(cancel_order)
                logger.info("Order cancelled", order_id=oid)
        ib.sleep(0.5)
    finally:
        ib.disconnect()


def get_open_orders() -> list[dict]:
    """
    Fetch all open orders from TWS.
    Returns list of dicts with orderId, permId, ticker, status, filledQty, avgFillPrice.
    """
    try:
        from ib_async import IB
        from app.config import get_settings
    except ImportError:
        return []

    settings = get_settings()
    ib = _connect_ib(settings, client_id=settings.ibkr_client_id_orders, timeout=8)
    try:
        trades = ib.reqOpenOrders()
        result = []
        for trade in trades:
            result.append({
                "order_id": trade.order.orderId,
                "perm_id": trade.order.permId,
                "ticker": trade.contract.symbol if trade.contract else None,
                "action": trade.order.action,
                "qty": trade.order.totalQuantity,
                "limit_price": trade.order.lmtPrice or None,
                "stop_price": trade.order.auxPrice or None,
                "status": trade.orderStatus.status,
                "filled_qty": trade.orderStatus.filled,
                "avg_fill_price": trade.orderStatus.avgFillPrice or None,
            })
        return result
    finally:
        ib.disconnect()


def get_completed_orders() -> list[dict]:
    """
    Fetch recently completed (filled/cancelled) executions from TWS.
    Used by sync task to detect fills that are no longer in open orders.
    """
    try:
        from ib_async import IB, ExecutionFilter
        from app.config import get_settings
    except ImportError:
        return []

    settings = get_settings()
    ib = _connect_ib(settings, client_id=settings.ibkr_client_id_orders, timeout=8)
    try:
        fills = ib.reqExecutions(ExecutionFilter())
        result = []
        for fill in fills:
            result.append({
                "order_id": fill.execution.orderId,
                "perm_id": fill.execution.permId,
                "ticker": fill.contract.symbol if fill.contract else None,
                "filled_qty": fill.execution.shares,
                "avg_fill_price": fill.execution.price,
                "side": fill.execution.side,  # BOT or SLD
            })
        return result
    finally:
        ib.disconnect()

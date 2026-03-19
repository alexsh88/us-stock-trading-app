import structlog
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone

logger = structlog.get_logger()

# Close positions that haven't hit SL/TP after this many trading days
MAX_HOLDING_DAYS = 5


def _trading_days_held(entry_dt: datetime, now: datetime) -> int:
    """Count business days between entry and now (inclusive of today)."""
    try:
        start = pd.Timestamp(entry_dt.date())
        end = pd.Timestamp(now.date())
        return len(pd.bdate_range(start, end))
    except Exception:
        return 0


def _get_sync_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import get_settings

    settings = get_settings()
    sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    engine = create_engine(sync_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def monitor_paper_positions() -> dict:
    """Check all open paper positions against SL/TP levels and close automatically."""
    from app.models.portfolio import Position, PositionStatus

    session, engine = _get_sync_session()
    closed_count = 0

    try:
        positions = (
            session.query(Position)
            .filter(Position.is_paper == True, Position.status == PositionStatus.OPEN)  # noqa: E712
            .all()
        )

        if not positions:
            return {"positions_checked": 0, "positions_closed": 0}

        # Batch download current prices for all open positions in one call
        tickers = list({p.ticker for p in positions})
        prices: dict[str, float] = {}
        try:
            if len(tickers) == 1:
                hist = yf.download(tickers[0], period="1d", interval="1m", progress=False, auto_adjust=True)
                if not hist.empty:
                    prices[tickers[0]] = float(hist["Close"].dropna().iloc[-1])
            else:
                hist_all = yf.download(
                    tickers, period="1d", interval="1m",
                    progress=False, auto_adjust=True, group_by="ticker"
                )
                for t in tickers:
                    try:
                        close = hist_all[t]["Close"].dropna()
                        if not close.empty:
                            prices[t] = float(close.iloc[-1])
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("Batch price download failed in monitor", error=str(e))

        now = datetime.now(timezone.utc)
        for position in positions:
            try:
                current_price = prices.get(position.ticker)
                if current_price is None:
                    continue

                position.current_price = current_price

                if position.stop_loss_price and current_price <= position.stop_loss_price:
                    position.exit_price = position.stop_loss_price
                    position.status = PositionStatus.CLOSED
                    position.close_reason = "stop_loss"
                    position.closed_at = now
                    closed_count += 1
                    logger.info(
                        "Stop loss hit",
                        ticker=position.ticker,
                        entry=position.entry_price,
                        exit=position.stop_loss_price,
                        pnl=round((position.stop_loss_price - position.entry_price) * position.quantity, 2),
                    )

                elif position.take_profit_price and current_price >= position.take_profit_price:
                    position.exit_price = position.take_profit_price
                    position.status = PositionStatus.CLOSED
                    position.close_reason = "take_profit"
                    position.closed_at = now
                    closed_count += 1
                    logger.info(
                        "Take profit hit",
                        ticker=position.ticker,
                        entry=position.entry_price,
                        exit=position.take_profit_price,
                        pnl=round((position.take_profit_price - position.entry_price) * position.quantity, 2),
                    )

                else:
                    # Time-based stop: close after MAX_HOLDING_DAYS trading days
                    entry_dt = getattr(position, "opened_at", None) or getattr(position, "created_at", None)
                    if entry_dt:
                        entry_dt_utc = entry_dt if entry_dt.tzinfo else entry_dt.replace(tzinfo=timezone.utc)
                        days_held = _trading_days_held(entry_dt_utc, now)
                        if days_held >= MAX_HOLDING_DAYS:
                            position.exit_price = round(current_price, 2)
                            position.status = PositionStatus.CLOSED
                            position.close_reason = "time_stop"
                            position.closed_at = now
                            closed_count += 1
                            logger.info(
                                "Time stop hit",
                                ticker=position.ticker,
                                days_held=days_held,
                                entry=position.entry_price,
                                exit=current_price,
                                pnl=round((current_price - position.entry_price) * position.quantity, 2),
                            )

            except Exception as e:
                logger.warning("Monitor failed for position", ticker=position.ticker, error=str(e))

        session.commit()
        logger.info("Paper position monitor complete", checked=len(positions), closed=closed_count)
        return {"positions_checked": len(positions), "positions_closed": closed_count}

    finally:
        session.close()
        engine.dispose()


from app.tasks.celery_app import celery_app
monitor_paper_positions = celery_app.task(name="app.tasks.paper_trade_tasks.monitor_paper_positions")(monitor_paper_positions)

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


# ── Technical helpers ─────────────────────────────────────────────────────────

def _calculate_chandelier_stop(hist: pd.DataFrame, period: int = 10, multiplier: float = 2.5) -> float | None:
    """Chandelier Exit: highest_close(period) - multiplier × ATR(period)."""
    try:
        high = hist["High"].squeeze()
        low = hist["Low"].squeeze()
        close = hist["Close"].squeeze()
        if len(close) < period + 1:
            return None
        prev_close = close.shift(1)
        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        atr = float(tr.ewm(alpha=1.0 / period, adjust=False).mean().iloc[-1])
        if atr == 0:
            return None
        highest_close = float(close.tail(period).max())
        return round(highest_close - multiplier * atr, 2)
    except Exception:
        return None


def _calculate_adx(hist: pd.DataFrame, period: int = 14) -> float | None:
    """Wilder's ADX — returns latest ADX value or None."""
    try:
        high = hist["High"].squeeze()
        low = hist["Low"].squeeze()
        close = hist["Close"].squeeze()
        if len(close) < period + 2:
            return None
        prev_close = close.shift(1)
        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        dm_plus_raw = high - high.shift(1)
        dm_minus_raw = low.shift(1) - low
        dm_plus = dm_plus_raw.where((dm_plus_raw > dm_minus_raw) & (dm_plus_raw > 0), 0.0)
        dm_minus = dm_minus_raw.where((dm_minus_raw > dm_plus_raw) & (dm_minus_raw > 0), 0.0)
        atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
        di_plus = 100 * dm_plus.ewm(alpha=1.0 / period, adjust=False).mean() / atr
        di_minus = 100 * dm_minus.ewm(alpha=1.0 / period, adjust=False).mean() / atr
        denom = (di_plus + di_minus).replace(0, float("nan"))
        dx = 100 * (di_plus - di_minus).abs() / denom
        adx = dx.ewm(alpha=1.0 / period, adjust=False).mean()
        return round(float(adx.iloc[-1]), 1)
    except Exception:
        return None


def _calculate_psar(hist: pd.DataFrame, af_start: float = 0.02, af_max: float = 0.20) -> float | None:
    """Parabolic SAR — returns the current SAR value only when in an uptrend.
    Returns None if the current trend is down (PSAR would be above price — not useful as a stop).
    """
    try:
        high = hist["High"].squeeze().dropna().values
        low = hist["Low"].squeeze().dropna().values
        n = len(high)
        if n < 10:
            return None

        psar = float(low[0])
        ep = float(high[0])
        af = af_start
        uptrend = True

        for i in range(1, n):
            if uptrend:
                psar = psar + af * (ep - psar)
                psar = min(psar, float(low[i - 1]), float(low[max(0, i - 2)]))
                if float(low[i]) < psar:
                    uptrend = False
                    psar = ep
                    ep = float(low[i])
                    af = af_start
                else:
                    if float(high[i]) > ep:
                        ep = float(high[i])
                        af = min(af + af_start, af_max)
            else:
                psar = psar + af * (ep - psar)
                psar = max(psar, float(high[i - 1]), float(high[max(0, i - 2)]))
                if float(high[i]) > psar:
                    uptrend = True
                    psar = ep
                    ep = float(high[i])
                    af = af_start
                else:
                    if float(low[i]) < ep:
                        ep = float(low[i])
                        af = min(af + af_start, af_max)

        return round(psar, 2) if uptrend else None
    except Exception:
        return None


def _get_trailing_hist(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Download 30d daily OHLCV for tickers that need trailing stop computation."""
    result: dict[str, pd.DataFrame] = {}
    if not tickers:
        return result
    try:
        if len(tickers) == 1:
            df = yf.download(tickers[0], period="30d", interval="1d", progress=False, auto_adjust=True)
            if not df.empty:
                result[tickers[0]] = df
        else:
            df_all = yf.download(
                tickers, period="30d", interval="1d",
                progress=False, auto_adjust=True, group_by="ticker",
            )
            for t in tickers:
                try:
                    df = df_all[t].dropna(how="all")
                    if not df.empty:
                        result[t] = df
                except Exception:
                    pass
    except Exception as e:
        logger.warning("Daily hist fetch failed for trailing", error=str(e))
    return result


# ── Position helpers ──────────────────────────────────────────────────────────

def _close_position(position, exit_price: float, reason: str, now: datetime) -> None:
    from app.models.portfolio import PositionStatus
    position.exit_price = round(exit_price, 2)
    position.status = PositionStatus.CLOSED
    position.close_reason = reason
    position.closed_at = now
    total_pnl = (exit_price - position.entry_price) * position.quantity + (position.partial_realized_pnl or 0)
    logger.info(
        "Position closed",
        ticker=position.ticker,
        reason=reason,
        stage=position.scale_out_stage,
        exit=exit_price,
        qty=position.quantity,
        total_pnl=round(total_pnl, 2),
    )


def _check_time_stop(position, current_price: float, now: datetime) -> bool:
    entry_dt = getattr(position, "opened_at", None) or getattr(position, "created_at", None)
    if entry_dt:
        entry_dt_utc = entry_dt if entry_dt.tzinfo else entry_dt.replace(tzinfo=timezone.utc)
        if _trading_days_held(entry_dt_utc, now) >= MAX_HOLDING_DAYS:
            _close_position(position, current_price, "time_stop", now)
            return True
    return False


def _update_trailing_stop(position, current_price: float, hist: pd.DataFrame | None) -> None:
    """Ratchet the trailing stop upward using chandelier (always) and PSAR (when ADX > 25).
    Never moves the stop down — only ratchets up."""
    if hist is None or hist.empty:
        return

    current_stop = position.stop_loss_price or 0.0
    new_stop: float | None = None
    new_method: str | None = None

    # Chandelier (always computed in trailing mode)
    chandelier = _calculate_chandelier_stop(hist)
    if chandelier and chandelier > current_stop and chandelier < current_price:
        new_stop = chandelier
        new_method = "Chandelier-trail"

    # PSAR override when profitable AND ADX > 25 (confirmed trend)
    if current_price > position.entry_price:
        adx = _calculate_adx(hist)
        if adx and adx > 25:
            psar = _calculate_psar(hist)
            candidate_stop = new_stop or current_stop
            if psar and psar > candidate_stop and psar < current_price:
                new_stop = psar
                new_method = f"PSAR(ADX={adx:.0f})"

    if new_stop:
        position.stop_loss_price = new_stop
        position.stop_loss_method = new_method
        logger.debug(
            "Trailing stop ratcheted",
            ticker=position.ticker,
            stop=new_stop,
            method=new_method,
            stage=position.scale_out_stage,
        )


# ── Main monitor task ─────────────────────────────────────────────────────────

def monitor_paper_positions() -> dict:
    """Check all open paper positions and apply the 3-stage scale-out logic.

    Stage 0 (full position):
      - Stop hit → close all
      - T1 hit → close 50%, stop→breakeven, stage=1
      - Time stop → close all

    Stage 1 (50% remains):
      - Stop hit → close remaining
      - T2 hit → close 50% of remaining (25% of original), stage=2
      - Nightly → update trailing stop (chandelier ± PSAR)

    Stage 2 (25% remains — pure trail):
      - Stop hit → close remaining
      - Nightly → update trailing stop
    """
    from app.models.portfolio import Position, PositionStatus

    session, engine = _get_sync_session()
    closed_count = 0
    partial_count = 0

    try:
        positions = (
            session.query(Position)
            .filter(Position.is_paper == True, Position.status == PositionStatus.OPEN)  # noqa: E712
            .all()
        )

        if not positions:
            return {"positions_checked": 0, "positions_closed": 0, "partial_closes": 0}

        # ── Batch fetch intraday prices for all open positions ────────────────
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
                    progress=False, auto_adjust=True, group_by="ticker",
                )
                for t in tickers:
                    try:
                        close = hist_all[t]["Close"].dropna()
                        if not close.empty:
                            prices[t] = float(close.iloc[-1])
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("Batch intraday price download failed", error=str(e))

        # ── Batch fetch daily OHLCV for positions needing trailing stops ──────
        trailing_tickers = list({p.ticker for p in positions if p.scale_out_stage >= 1})
        daily_hist: dict[str, pd.DataFrame] = _get_trailing_hist(trailing_tickers)

        now = datetime.now(timezone.utc)

        for position in positions:
            try:
                current_price = prices.get(position.ticker)
                if current_price is None:
                    continue

                position.current_price = current_price
                stop = position.stop_loss_price
                entry = position.entry_price
                hist_daily = daily_hist.get(position.ticker)

                # ── Stage 0: full position, watching for T1 ───────────────────
                if position.scale_out_stage == 0:
                    if stop and current_price <= stop:
                        _close_position(position, stop, "stop_loss", now)
                        closed_count += 1

                    elif position.take_profit_price and current_price >= position.take_profit_price:
                        # T1 hit — partial close 50%
                        t1_price = position.take_profit_price
                        qty_to_close = max(position.quantity // 2, 1)
                        pnl_booked = (t1_price - entry) * qty_to_close
                        position.quantity -= qty_to_close
                        position.partial_realized_pnl = (position.partial_realized_pnl or 0) + pnl_booked
                        position.stop_loss_price = entry  # stop to breakeven
                        position.stop_loss_method = "breakeven"
                        position.scale_out_stage = 1
                        partial_count += 1
                        logger.info(
                            "T1 hit — 50%% closed, stop→breakeven",
                            ticker=position.ticker,
                            t1=t1_price,
                            qty_closed=qty_to_close,
                            qty_remaining=position.quantity,
                            pnl_booked=round(pnl_booked, 2),
                        )

                    else:
                        if _check_time_stop(position, current_price, now):
                            closed_count += 1

                # ── Stage 1: 50% remains, watching for T2 ────────────────────
                elif position.scale_out_stage == 1:
                    if stop and current_price <= stop:
                        _close_position(position, stop, "stop_loss_after_t1", now)
                        closed_count += 1

                    elif position.target2_price and current_price >= position.target2_price:
                        # T2 hit — partial close 50% of remaining (25% of original)
                        t2_price = position.target2_price
                        qty_to_close = max(position.quantity // 2, 1)
                        pnl_booked = (t2_price - entry) * qty_to_close
                        position.quantity -= qty_to_close
                        position.partial_realized_pnl = (position.partial_realized_pnl or 0) + pnl_booked
                        position.scale_out_stage = 2
                        partial_count += 1
                        logger.info(
                            "T2 hit — 25%% closed, trailing remainder",
                            ticker=position.ticker,
                            t2=t2_price,
                            qty_closed=qty_to_close,
                            qty_remaining=position.quantity,
                            pnl_booked=round(pnl_booked, 2),
                        )
                        # Immediately start trailing on the remainder
                        _update_trailing_stop(position, current_price, hist_daily)

                    else:
                        # No target hit — ratchet trailing stop nightly
                        _update_trailing_stop(position, current_price, hist_daily)

                # ── Stage 2: 25% remains, pure chandelier/PSAR trail ─────────
                elif position.scale_out_stage == 2:
                    if stop and current_price <= stop:
                        _close_position(position, stop, "trailing_stop", now)
                        closed_count += 1
                    else:
                        _update_trailing_stop(position, current_price, hist_daily)

            except Exception as e:
                logger.warning("Monitor failed for position", ticker=position.ticker, error=str(e))

        session.commit()
        logger.info(
            "Paper position monitor complete",
            checked=len(positions),
            closed=closed_count,
            partial_closes=partial_count,
        )
        return {
            "positions_checked": len(positions),
            "positions_closed": closed_count,
            "partial_closes": partial_count,
        }

    finally:
        session.close()
        engine.dispose()


from app.tasks.celery_app import celery_app
monitor_paper_positions = celery_app.task(name="app.tasks.paper_trade_tasks.monitor_paper_positions")(monitor_paper_positions)

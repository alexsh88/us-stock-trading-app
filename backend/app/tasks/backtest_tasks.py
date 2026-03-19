"""
Nightly backtest task: evaluates past trade signals using actual OHLCV data.

Pipeline per signal:
  1. Download 5 trading days of 1-day OHLCV for the ticker starting from signal_date
  2. Check SL/TP hit using intraday High/Low (more accurate than Close-only)
  3. Record returns at 1/2/3/5-day horizons
  4. Compute R-multiple = realized_return / initial_risk
  5. Run Spearman IC analysis across all completed signals for each factor × horizon

Runs nightly at 5:30 PM ET (after market close; enough time for yfinance to update).
"""
import uuid
import time
import structlog
from datetime import datetime, timezone, timedelta
from typing import Optional

import yfinance as yf
import numpy as np

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


def _fetch_ohlcv(ticker: str, start: datetime, days: int = 7) -> Optional[dict]:
    """Download daily OHLCV for ticker starting at start date.
    Returns dict keyed by integer offset (1=day1, 2=day2 ...) with OHLC values.
    """
    try:
        end = start + timedelta(days=days + 5)  # extra buffer for weekends/holidays
        hist = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if hist.empty:
            return None

        # Drop the signal date row if present (we want forward returns)
        hist = hist[hist.index > start.strftime("%Y-%m-%d")]
        if hist.empty:
            return None

        result = {}
        for i, (idx, row) in enumerate(hist.iterrows(), start=1):
            if i > 5:
                break
            result[i] = {
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "date": idx,
            }
        return result if result else None
    except Exception as e:
        logger.warning("OHLCV download failed", ticker=ticker, error=str(e))
        return None


def _detect_sl_tp(ohlcv: dict, entry: float, sl: Optional[float], tp: Optional[float]) -> dict:
    """Check if SL or TP was hit using daily High/Low.
    Day-level detection: if Low <= SL, SL hit. If High >= TP, TP hit.
    If both in same day, assume SL hit first (conservative).
    """
    sl_hit = False
    tp_hit = False
    sl_day = None
    tp_day = None

    for day_num in sorted(ohlcv.keys()):
        candle = ohlcv[day_num]
        if not sl_hit and sl and candle["low"] <= sl:
            sl_hit = True
            sl_day = day_num
        if not tp_hit and tp and candle["high"] >= tp:
            tp_hit = True
            tp_day = day_num

        # If both hit same day: SL wins (conservative)
        if sl_hit and tp_hit and sl_day == tp_day:
            tp_hit = False
            tp_day = None

        # Once SL or TP is hit, stop scanning
        if sl_hit or tp_hit:
            break

    return {"sl_hit": sl_hit, "tp_hit": tp_hit, "sl_day": sl_day, "tp_day": tp_day}


def run_nightly_backtest() -> dict:
    """Evaluate all pending signals and compute factor IC."""
    from app.models.signals import TradeSignal
    from app.models.backtest import SignalOutcome, FactorIC

    session, engine = _get_sync_session()
    created = 0
    updated = 0
    errors = 0

    try:
        now = datetime.now(timezone.utc)

        # ── Step 1: Create SignalOutcome rows for any signals that don't have one yet ──
        # Only process BUY signals that are at least 1 day old
        cutoff = now - timedelta(days=1)
        existing_ids = {row[0] for row in session.query(SignalOutcome.signal_id).all()}

        new_signals = (
            session.query(TradeSignal)
            .filter(
                TradeSignal.decision == "BUY",
                TradeSignal.created_at <= cutoff,
                ~TradeSignal.id.in_(existing_ids),
            )
            .all()
        )

        for sig in new_signals:
            outcome = SignalOutcome(
                id=uuid.uuid4(),
                signal_id=sig.id,
                ticker=sig.ticker,
                signal_date=sig.created_at,
                decision=sig.decision.value if hasattr(sig.decision, "value") else sig.decision,
                confidence_score=sig.confidence_score,
                entry_price=sig.entry_price,
                stop_loss_price=sig.stop_loss_price,
                take_profit_price=sig.take_profit_price,
                technical_score=sig.technical_score,
                fundamental_score=sig.fundamental_score,
                sentiment_score=sig.sentiment_score,
                catalyst_score=sig.catalyst_score,
                trading_mode=sig.trading_mode.value if hasattr(sig.trading_mode, "value") else sig.trading_mode,
                is_complete=False,
            )
            session.add(outcome)
            created += 1

        session.commit()

        # ── Step 2: Fill in OHLCV data for incomplete outcomes ──
        incomplete = (
            session.query(SignalOutcome)
            .filter(SignalOutcome.is_complete == False)  # noqa: E712
            .all()
        )

        # Group by ticker to batch downloads
        by_ticker: dict[str, list] = {}
        for outcome in incomplete:
            by_ticker.setdefault(outcome.ticker, []).append(outcome)

        for ticker, outcomes in by_ticker.items():
            time.sleep(0.1)  # gentle rate limiting
            for outcome in outcomes:
                if outcome.entry_price is None:
                    continue

                ohlcv = _fetch_ohlcv(ticker, outcome.signal_date, days=7)
                if not ohlcv:
                    errors += 1
                    continue

                entry = outcome.entry_price
                horizons = {1: "return_1d", 2: "return_2d", 3: "return_3d", 5: "return_5d"}
                prices = {1: "price_1d", 2: "price_2d", 3: "price_3d", 5: "price_5d"}

                for h, col in horizons.items():
                    if h in ohlcv:
                        close = ohlcv[h]["close"]
                        setattr(outcome, prices[h], close)
                        ret = (close - entry) / entry if entry else None
                        setattr(outcome, col, ret)

                # Direction accuracy
                if 1 in ohlcv:
                    outcome.correct_direction_1d = ohlcv[1]["close"] > entry
                if 3 in ohlcv:
                    outcome.correct_direction_3d = ohlcv[3]["close"] > entry
                if 5 in ohlcv:
                    outcome.correct_direction_5d = ohlcv[5]["close"] > entry

                # SL / TP detection
                hit = _detect_sl_tp(ohlcv, entry, outcome.stop_loss_price, outcome.take_profit_price)
                outcome.sl_hit = hit["sl_hit"]
                outcome.tp_hit = hit["tp_hit"]
                outcome.sl_hit_day = hit["sl_day"]
                outcome.tp_hit_day = hit["tp_day"]

                # R-multiple
                if outcome.stop_loss_price and entry > outcome.stop_loss_price:
                    risk_per_share = entry - outcome.stop_loss_price
                    if outcome.tp_hit and outcome.take_profit_price:
                        realized = outcome.take_profit_price - entry
                    elif outcome.sl_hit:
                        realized = outcome.stop_loss_price - entry
                    elif 5 in ohlcv:
                        realized = ohlcv[5]["close"] - entry
                    else:
                        realized = None
                    if realized is not None and risk_per_share > 0:
                        outcome.r_multiple = round(realized / risk_per_share, 3)

                # Mark complete once day 5 data is available
                days_elapsed = (now - outcome.signal_date).days
                outcome.is_complete = days_elapsed >= 5 and 5 in ohlcv

                updated += 1

        session.commit()

        # ── Step 3: Compute factor IC ──
        ic_rows = _compute_factor_ic(session, now)
        for row in ic_rows:
            session.add(row)
        session.commit()

        # ── Step 4: Update cached factor weights from latest IC ──
        _refresh_ic_weights()

        logger.info(
            "Nightly backtest complete",
            created=created, updated=updated, errors=errors, ic_rows=len(ic_rows)
        )
        return {"created": created, "updated": updated, "errors": errors, "ic_rows": len(ic_rows)}

    finally:
        session.close()
        engine.dispose()


def _compute_factor_ic(session, now: datetime) -> list:
    """Compute Spearman IC for each factor × horizon combination.
    Only uses signals from the last 90 days with complete outcomes.
    """
    from app.models.backtest import SignalOutcome, FactorIC

    cutoff_90d = now - timedelta(days=90)
    outcomes = (
        session.query(SignalOutcome)
        .filter(
            SignalOutcome.is_complete == True,  # noqa: E712
            SignalOutcome.signal_date >= cutoff_90d,
        )
        .all()
    )

    if len(outcomes) < 5:  # Need minimum sample for meaningful IC
        return []

    factors = ["technical_score", "fundamental_score", "sentiment_score", "catalyst_score", "confidence_score"]
    horizons = [(1, "return_1d"), (2, "return_2d"), (3, "return_3d"), (5, "return_5d")]
    ic_rows = []

    for factor in factors:
        for horizon_days, return_col in horizons:
            pairs = [
                (getattr(o, factor), getattr(o, return_col))
                for o in outcomes
                if getattr(o, factor) is not None and getattr(o, return_col) is not None
            ]
            if len(pairs) < 5:
                continue

            scores, returns = zip(*pairs)
            ic = _spearman(scores, returns)
            if ic is None or np.isnan(ic):
                continue

            # Rolling 30-day IC mean and IR
            cutoff_30d = now - timedelta(days=30)
            recent_ic_values = (
                session.query(FactorIC.ic)
                .filter(
                    FactorIC.factor == factor,
                    FactorIC.horizon == horizon_days,
                    FactorIC.date >= cutoff_30d,
                )
                .all()
            )
            if recent_ic_values:
                vals = [r[0] for r in recent_ic_values] + [ic]
                ic_mean_30d = float(np.mean(vals))
                ic_ir = float(np.mean(vals) / np.std(vals)) if np.std(vals) > 0 else None
            else:
                ic_mean_30d = None
                ic_ir = None

            ic_rows.append(FactorIC(
                id=uuid.uuid4(),
                date=now,
                factor=factor,
                horizon=horizon_days,
                trading_mode="swing",
                ic=round(float(ic), 4),
                n_signals=len(pairs),
                ic_mean_30d=round(ic_mean_30d, 4) if ic_mean_30d is not None else None,
                ic_ir=round(ic_ir, 3) if ic_ir is not None else None,
            ))

    return ic_rows


def _refresh_ic_weights() -> None:
    """Re-derive and cache IC weights after the nightly backtest completes."""
    from app.agents.cache_utils import _compute_ic_weights_from_db, set_factor_weights, fit_platt_calibration
    for mode in ("swing", "intraday"):
        try:
            weights = _compute_ic_weights_from_db(mode)
            if weights:
                set_factor_weights(mode, weights)
                logger.info("IC weights refreshed", mode=mode, weights=weights)
        except Exception as e:
            logger.warning("IC weights refresh failed", mode=mode, error=str(e))

        # Platt calibration — only fits when >= 50 complete signals exist
        try:
            fit_platt_calibration(mode)
        except Exception as e:
            logger.debug("Platt calibration failed (likely insufficient data)", mode=mode, error=str(e))


def _spearman(x: tuple, y: tuple) -> float | None:
    """Compute Spearman rank correlation using only numpy."""
    import numpy as np
    ax = np.array(x, dtype=float)
    ay = np.array(y, dtype=float)
    if len(ax) < 3:
        return None
    rx = np.argsort(np.argsort(ax)).astype(float)
    ry = np.argsort(np.argsort(ay)).astype(float)
    # Pearson on ranks
    rx -= rx.mean()
    ry -= ry.mean()
    denom = np.sqrt((rx ** 2).sum() * (ry ** 2).sum())
    return float((rx * ry).sum() / denom) if denom > 0 else 0.0


from app.tasks.celery_app import celery_app
run_nightly_backtest = celery_app.task(name="app.tasks.backtest_tasks.run_nightly_backtest")(run_nightly_backtest)

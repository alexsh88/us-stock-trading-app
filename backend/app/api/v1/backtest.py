import structlog
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from datetime import datetime, timezone, timedelta

from app.dependencies import get_db_session
from app.models.backtest import SignalOutcome, FactorIC

logger = structlog.get_logger()
router = APIRouter()


@router.get("/summary")
async def get_backtest_summary(db: AsyncSession = Depends(get_db_session)):
    """Overall signal performance summary across all evaluated signals."""
    result = await db.execute(
        select(SignalOutcome).where(SignalOutcome.is_complete == True)  # noqa: E712
    )
    outcomes = result.scalars().all()

    if not outcomes:
        return {"total_signals": 0, "message": "No completed signal evaluations yet"}

    total = len(outcomes)
    with_returns = [o for o in outcomes if o.return_5d is not None]
    tp_hits = sum(1 for o in outcomes if o.tp_hit)
    sl_hits = sum(1 for o in outcomes if o.sl_hit)

    avg_r = None
    r_vals = [o.r_multiple for o in outcomes if o.r_multiple is not None]
    if r_vals:
        avg_r = round(sum(r_vals) / len(r_vals), 3)

    dir_1d = [o for o in outcomes if o.correct_direction_1d is not None]
    dir_5d = [o for o in outcomes if o.correct_direction_5d is not None]

    return {
        "total_signals": total,
        "complete_evaluations": len(with_returns),
        "tp_hit_rate": round(tp_hits / total, 4) if total else 0,
        "sl_hit_rate": round(sl_hits / total, 4) if total else 0,
        "avg_r_multiple": avg_r,
        "direction_accuracy_1d": round(sum(1 for o in dir_1d if o.correct_direction_1d) / len(dir_1d), 4) if dir_1d else None,
        "direction_accuracy_5d": round(sum(1 for o in dir_5d if o.correct_direction_5d) / len(dir_5d), 4) if dir_5d else None,
        "avg_return_5d": round(sum(o.return_5d for o in with_returns) / len(with_returns), 4) if with_returns else None,
    }


@router.get("/factor-ic")
async def get_factor_ic(
    horizon: int = 3,
    days: int = 30,
    db: AsyncSession = Depends(get_db_session),
):
    """Get the most recent IC values for each factor at the given horizon."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(FactorIC)
        .where(FactorIC.horizon == horizon, FactorIC.date >= cutoff)
        .order_by(desc(FactorIC.date))
    )
    rows = result.scalars().all()

    # Latest IC per factor
    seen = set()
    latest: list[dict] = []
    for row in rows:
        if row.factor not in seen:
            seen.add(row.factor)
            latest.append({
                "factor": row.factor,
                "horizon_days": row.horizon,
                "ic": row.ic,
                "ic_mean_30d": row.ic_mean_30d,
                "ic_ir": row.ic_ir,
                "n_signals": row.n_signals,
                "date": row.date.isoformat(),
            })

    return {"horizon_days": horizon, "factors": latest}


@router.get("/outcomes")
async def list_signal_outcomes(
    limit: int = 50,
    complete_only: bool = False,
    db: AsyncSession = Depends(get_db_session),
):
    """List recent signal outcomes for inspection."""
    query = select(SignalOutcome).order_by(desc(SignalOutcome.signal_date)).limit(limit)
    if complete_only:
        query = query.where(SignalOutcome.is_complete == True)  # noqa: E712
    result = await db.execute(query)
    outcomes = result.scalars().all()

    return [
        {
            "ticker": o.ticker,
            "signal_date": o.signal_date.isoformat() if o.signal_date else None,
            "confidence_score": o.confidence_score,
            "return_1d": o.return_1d,
            "return_3d": o.return_3d,
            "return_5d": o.return_5d,
            "sl_hit": o.sl_hit,
            "tp_hit": o.tp_hit,
            "r_multiple": o.r_multiple,
            "correct_direction_1d": o.correct_direction_1d,
            "correct_direction_5d": o.correct_direction_5d,
            "is_complete": o.is_complete,
        }
        for o in outcomes
    ]


@router.post("/run-now", status_code=202)
async def trigger_backtest(background_tasks: BackgroundTasks):
    """Manually trigger the nightly backtest task (for testing)."""
    from app.tasks.backtest_tasks import run_nightly_backtest
    run_nightly_backtest.delay()
    return {"message": "Backtest task queued"}

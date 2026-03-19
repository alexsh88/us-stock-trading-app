import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_db_session
from app.models.analysis import AnalysisRun, RunStatus
from app.models.signals import TradeSignal
from app.schemas.analysis import AnalysisRunRequest, AnalysisRunResponse, TradeSignalResponse

logger = structlog.get_logger()
router = APIRouter()


@router.post("/run", response_model=AnalysisRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_analysis(
    request: AnalysisRunRequest,
    db: AsyncSession = Depends(get_db_session),
):
    run = AnalysisRun(
        top_n=request.top_n,
        mode=request.mode,
        status=RunStatus.PENDING,
    )
    db.add(run)
    await db.flush()

    # Enqueue Celery task
    try:
        from app.tasks.analysis_tasks import run_on_demand
        from app.api.v1.settings import _current_settings
        # Always use saved settings as source of truth for mode and watchlist
        mode = _current_settings.trading_mode or request.mode
        top_n = request.top_n
        watchlist = _current_settings.watchlist or ""
        sector_top_n = _current_settings.sector_top_n
        task = run_on_demand.delay(str(run.id), mode, top_n, watchlist, sector_top_n)
        run.mode = mode  # update the run record to reflect actual mode used
        run.celery_task_id = task.id
        run.status = RunStatus.RUNNING
    except Exception as e:
        logger.warning("Could not enqueue Celery task", error=str(e))
        run.status = RunStatus.PENDING

    await db.commit()
    await db.refresh(run)
    return run


@router.get("/history", response_model=list[AnalysisRunResponse])
async def get_run_history(limit: int = 20, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(
        select(AnalysisRun).order_by(AnalysisRun.created_at.desc()).limit(limit)
    )
    return result.scalars().all()


@router.get("/latest", response_model=AnalysisRunResponse)
async def get_latest_run(db: AsyncSession = Depends(get_db_session)):
    # Prefer the most recent completed run; fall back to any run if none completed
    result = await db.execute(
        select(AnalysisRun)
        .where(AnalysisRun.status == "COMPLETED")
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        result = await db.execute(
            select(AnalysisRun).order_by(AnalysisRun.created_at.desc()).limit(1)
        )
        run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="No analysis runs found")
    return run


@router.get("/{run_id}", response_model=AnalysisRunResponse)
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    return run


@router.get("/{run_id}/signals", response_model=list[TradeSignalResponse])
async def get_run_signals(run_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(
        select(TradeSignal)
        .where(TradeSignal.run_id == run_id)
        .order_by(TradeSignal.confidence_score.desc())
    )
    signals = result.scalars().all()
    return [TradeSignalResponse.from_orm_with_scores(s) for s in signals]

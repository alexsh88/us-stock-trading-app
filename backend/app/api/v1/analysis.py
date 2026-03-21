import re
import json
import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from redis.asyncio import Redis

from app.dependencies import get_db_session
from app.core.redis_client import get_redis
from app.models.analysis import AnalysisRun, RunStatus
from app.models.signals import TradeSignal
from app.schemas.analysis import AnalysisRunRequest, AnalysisRunResponse, TradeSignalResponse
from app.schemas.settings import AppSettings
from app.config import get_settings as _get_app_config

logger = structlog.get_logger()
router = APIRouter()

_SETTINGS_REDIS_KEY = "app:settings"


async def _load_settings(redis: Redis) -> AppSettings:
    """Fetch persisted app settings from Redis, falling back to config defaults."""
    try:
        raw = await redis.get(_SETTINGS_REDIS_KEY)
        if raw:
            return AppSettings(**json.loads(raw))
    except Exception:
        pass
    cfg = _get_app_config()
    return AppSettings(
        top_n=cfg.default_top_n,
        trading_mode=cfg.default_trading_mode,
        paper_trading=cfg.paper_trading,
    )


class SingleTickerRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=6)
    mode: str = Field(default="swing", pattern="^(swing|intraday)$")


@router.post("/run", response_model=AnalysisRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_analysis(
    request: AnalysisRunRequest,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    saved = await _load_settings(redis)

    run = AnalysisRun(
        top_n=request.top_n,
        mode=saved.trading_mode or request.mode,
        status=RunStatus.PENDING,
    )
    db.add(run)
    await db.flush()

    # Enqueue Celery task
    try:
        from app.tasks.analysis_tasks import run_on_demand
        mode = saved.trading_mode or request.mode
        top_n = request.top_n
        watchlist = saved.watchlist or ""
        sector_top_n = saved.sector_top_n
        pinned_sectors = ",".join(saved.pinned_sectors) if saved.pinned_sectors else ""
        task = run_on_demand.delay(str(run.id), mode, top_n, watchlist, sector_top_n, pinned_sectors)
        run.mode = mode
        run.celery_task_id = task.id
        run.status = RunStatus.RUNNING
    except Exception as e:
        logger.error("Could not enqueue Celery task — is the worker running?", error=str(e))
        run.status = RunStatus.FAILED
        run.error_message = f"Task queue unavailable: {e}"

    await db.commit()
    await db.refresh(run)
    return run


@router.post("/single", response_model=AnalysisRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_single_ticker(
    request: SingleTickerRequest,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    ticker = request.ticker.upper().strip()
    if not re.match(r"^[A-Z]{1,6}$", ticker):
        raise HTTPException(status_code=422, detail="Ticker must be 1–6 uppercase letters")

    saved = await _load_settings(redis)

    run = AnalysisRun(
        top_n=1,
        mode=request.mode,
        status=RunStatus.PENDING,
    )
    db.add(run)
    await db.flush()

    try:
        from app.tasks.analysis_tasks import run_on_demand
        pinned_str = ",".join(saved.pinned_sectors) if saved.pinned_sectors else ""
        task = run_on_demand.delay(str(run.id), request.mode, 1, ticker, saved.sector_top_n, pinned_str)
        run.celery_task_id = task.id
        run.status = RunStatus.RUNNING
    except Exception as e:
        logger.error("Could not enqueue single-ticker task — is the worker running?", ticker=ticker, error=str(e))
        run.status = RunStatus.FAILED
        run.error_message = f"Task queue unavailable: {e}"

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
    # Prefer the most recent completed batch run (exclude single-ticker lookups)
    # Single-ticker runs always have tickers_screened=1; batch runs have >1 or NULL (still running)
    result = await db.execute(
        select(AnalysisRun)
        .where(AnalysisRun.status == "COMPLETED")
        .where((AnalysisRun.tickers_screened == None) | (AnalysisRun.tickers_screened > 1))
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        result = await db.execute(
            select(AnalysisRun)
            .where((AnalysisRun.tickers_screened == None) | (AnalysisRun.tickers_screened > 1))
            .order_by(AnalysisRun.created_at.desc())
            .limit(1)
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

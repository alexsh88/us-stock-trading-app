import uuid
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()


def _get_sync_session():
    """Create a synchronous SQLAlchemy session using psycopg2 (safe for Celery)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import get_settings

    settings = get_settings()
    # Replace asyncpg driver with psycopg2 for sync use in Celery
    sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    engine = create_engine(sync_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def run_morning_analysis(mode: str = "swing", top_n: int = 5, watchlist: str = "") -> dict:
    """Celery task: triggered by Beat at 9:00 AM ET."""
    return _run_sync(str(uuid.uuid4()), mode, top_n, watchlist)


def run_on_demand(run_id: str, mode: str = "swing", top_n: int = 5, watchlist: str = "") -> dict:
    """Celery task: triggered by API endpoint."""
    return _run_sync(run_id, mode, top_n, watchlist)


def _run_sync(run_id: str, mode: str, top_n: int, watchlist: str = "") -> dict:
    from app.models.analysis import AnalysisRun, RunStatus
    from app.models.signals import TradeSignal, TradeDecision, TradingMode
    from app.agents.graph import trading_graph

    logger.info("Starting analysis run", run_id=run_id, mode=mode, top_n=top_n)

    session, engine = _get_sync_session()
    try:
        # Find or create run record
        run = session.query(AnalysisRun).filter(AnalysisRun.id == uuid.UUID(run_id)).first()
        if not run:
            run = AnalysisRun(id=uuid.UUID(run_id), status=RunStatus.RUNNING, top_n=top_n, mode=mode)
            session.add(run)
        else:
            run.status = RunStatus.RUNNING
        session.commit()

        try:
            # Parse custom watchlist — bypass screener if provided
            custom_tickers = [t.strip().upper() for t in watchlist.split(",") if t.strip()] if watchlist else []

            initial_state = {
                "mode": mode,
                "top_n": top_n,
                "run_id": run_id,
                "candidate_tickers": custom_tickers,  # pre-populated = screener skipped
                "market_regime": {"sizing_multiplier": 1.0, "entry_allowed": True, "regime": "unknown"},
                "favored_sectors": [],
                "sector_scores": {},
                "technical_scores": {},
                "fundamental_scores": {},
                "sentiment_scores": {},
                "catalyst_scores": {},
                "risk_metrics": {},
                "trade_signals": [],
                "errors": [],
            }

            # thread_id isolates this run's checkpoint state from other concurrent runs
            config = {"configurable": {"thread_id": run_id}}
            final_state = trading_graph.invoke(initial_state, config=config)
            signals = final_state.get("trade_signals", [])

            from app.agents.cache_utils import calibrate_confidence

            for sig_data in signals:
                ticker = sig_data["ticker"]
                tech_meta = final_state.get("technical_scores", {}).get(ticker, {})
                # Apply Platt calibration if parameters exist (no-op when < 50 outcomes)
                sig_data["confidence_score"] = calibrate_confidence(
                    sig_data["confidence_score"], mode
                )
                # Persist rich technical metadata so the frontend can display it
                indicators = {k: tech_meta[k] for k in (
                    "adx", "regime", "mtf_aligned", "bb_squeeze", "squeeze_released",
                    "breakout_score", "breakout_details", "vol_ratio",
                    "swing_resistance", "swing_support",
                    "rsi", "macd_signal", "bb_position", "vwap_relation",
                ) if k in tech_meta} or None

                signal = TradeSignal(
                    run_id=run.id,
                    ticker=ticker,
                    decision=TradeDecision(sig_data["decision"]),
                    confidence_score=sig_data["confidence_score"],
                    trading_mode=TradingMode(sig_data.get("trading_mode", "swing")),
                    entry_price=sig_data.get("entry_price"),
                    stop_loss_price=sig_data.get("stop_loss_price"),
                    stop_loss_method=sig_data.get("stop_loss_method"),
                    take_profit_price=sig_data.get("take_profit_price"),
                    risk_reward_ratio=sig_data.get("risk_reward_ratio"),
                    position_size_pct=sig_data.get("position_size_pct"),
                    technical_score=sig_data.get("technical_score"),
                    fundamental_score=sig_data.get("fundamental_score"),
                    sentiment_score=sig_data.get("sentiment_score"),
                    catalyst_score=sig_data.get("catalyst_score"),
                    key_risks=sig_data.get("key_risks", []),
                    reasoning=sig_data.get("reasoning", ""),
                    is_paper=True,
                    indicators=indicators,
                )
                session.add(signal)

            run.status = RunStatus.COMPLETED
            run.signals_generated = len(signals)
            run.tickers_screened = len(final_state.get("candidate_tickers", []))
            run.completed_at = datetime.now(timezone.utc)
            session.commit()

            logger.info("Analysis run completed", run_id=run_id, signals=len(signals))
            return {"run_id": run_id, "signals": len(signals), "status": "completed"}

        except Exception as e:
            run.status = RunStatus.FAILED
            run.error_message = str(e)[:1000]
            session.commit()
            logger.error("Analysis run failed", run_id=run_id, error=str(e))
            raise

    finally:
        session.close()
        engine.dispose()


# Register tasks with Celery
from app.tasks.celery_app import celery_app

run_morning_analysis = celery_app.task(name="app.tasks.analysis_tasks.run_morning_analysis")(run_morning_analysis)
run_on_demand = celery_app.task(name="app.tasks.analysis_tasks.run_on_demand")(run_on_demand)

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


def run_morning_analysis(mode: str = "swing", top_n: int = 5, watchlist: str = "", sector_top_n: int = 3) -> dict:
    """Celery task: triggered by Beat at 9:00 AM ET."""
    return _run_sync(str(uuid.uuid4()), mode, top_n, watchlist, sector_top_n)


def run_on_demand(run_id: str, mode: str = "swing", top_n: int = 5, watchlist: str = "", sector_top_n: int = 3) -> dict:
    """Celery task: triggered by API endpoint."""
    return _run_sync(run_id, mode, top_n, watchlist, sector_top_n)


def _run_sync(run_id: str, mode: str, top_n: int, watchlist: str = "", sector_top_n: int = 3) -> dict:
    from app.models.analysis import AnalysisRun, RunStatus
    from app.models.signals import TradeSignal, TradeDecision, TradingMode
    from app.agents.graph import trading_graph

    logger.info("Starting analysis run", run_id=run_id, mode=mode, top_n=top_n, sector_top_n=sector_top_n)

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
            # Parse custom watchlist — bypass screener + sector filter if provided
            custom_tickers = [t.strip().upper() for t in watchlist.split(",") if t.strip()] if watchlist else []

            initial_state = {
                "mode": mode,
                "top_n": top_n,
                "sector_top_n": sector_top_n,
                "watchlist_active": bool(custom_tickers),
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
                "news_headlines": {},
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
                    detected_patterns=sig_data.get("detected_patterns"),
                )
                session.add(signal)

            run.status = RunStatus.COMPLETED
            run.signals_generated = len(signals)
            run.tickers_screened = len(final_state.get("candidate_tickers", []))
            run.completed_at = datetime.now(timezone.utc)
            session.commit()

            # Immediately seed SignalOutcome placeholders so nightly backtest
            # only needs to fill in the OHLCV data (no cold-start delay)
            _seed_signal_outcomes(session, run_id)

            # Store headlines in news_embeddings for historical pattern retrieval
            _store_news_headlines(session, final_state.get("news_headlines", {}))

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


def _store_news_headlines(session, news_headlines: dict) -> None:
    """Persist raw headlines to news_embeddings table.
    Embeddings (embedding_vec) are left NULL for now — a separate nightly job
    can backfill them using an embedding API when one is configured.
    """
    if not news_headlines:
        return
    try:
        from sqlalchemy import text
        now = datetime.now(timezone.utc)
        rows = []
        for ticker, headlines in news_headlines.items():
            for headline in headlines:
                rows.append({"ticker": ticker, "headline": headline,
                             "source": "finnhub_ibkr", "published_at": now})
        if rows:
            session.execute(
                text("""
                    INSERT INTO news_embeddings (ticker, headline, source, published_at)
                    VALUES (:ticker, :headline, :source, :published_at)
                    ON CONFLICT DO NOTHING
                """),
                rows,
            )
            session.commit()
            logger.debug("News headlines stored", count=len(rows))
    except Exception as e:
        logger.warning("News headlines storage failed", error=str(e))


def _seed_signal_outcomes(session, run_id: str) -> None:
    """Create SignalOutcome placeholder rows for all BUY signals in this run.
    The nightly backtest will fill in the actual OHLCV-based returns.
    """
    try:
        import uuid as _uuid
        from app.models.signals import TradeSignal, TradeDecision
        from app.models.backtest import SignalOutcome

        existing_ids = {row[0] for row in session.query(SignalOutcome.signal_id).all()}
        signals = (
            session.query(TradeSignal)
            .filter(
                TradeSignal.run_id == _uuid.UUID(run_id),
                TradeSignal.decision == TradeDecision.BUY,
            )
            .all()
        )
        seeded = 0
        for sig in signals:
            if sig.id in existing_ids:
                continue
            outcome = SignalOutcome(
                id=_uuid.uuid4(),
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
            seeded += 1
        if seeded:
            session.commit()
            logger.info("Signal outcomes seeded", run_id=run_id, count=seeded)
    except Exception as e:
        logger.warning("Signal outcome seeding failed", error=str(e))


# Register tasks with Celery
from app.tasks.celery_app import celery_app

run_morning_analysis = celery_app.task(name="app.tasks.analysis_tasks.run_morning_analysis")(run_morning_analysis)
run_on_demand = celery_app.task(name="app.tasks.analysis_tasks.run_on_demand")(run_on_demand)

from celery import Celery
from celery.schedules import crontab
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "trading",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.analysis_tasks",
        "app.tasks.market_data_tasks",
        "app.tasks.paper_trade_tasks",
        "app.tasks.backtest_tasks",
        "app.tasks.embedding_tasks",
        "app.tasks.market_data_ingest_tasks",
        "app.tasks.ibkr_order_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/New_York",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Beat schedule — 9:00 AM ET (after IB Gateway daily restart window)
celery_app.conf.beat_schedule = {
    "morning-analysis-swing": {
        "task": "app.tasks.analysis_tasks.run_morning_analysis",
        "schedule": crontab(hour=9, minute=0, day_of_week="1-5"),
        "args": ("swing", 5),
    },
    "monitor-paper-positions": {
        "task": "app.tasks.paper_trade_tasks.monitor_paper_positions",
        "schedule": crontab(minute="*/5", hour="9-16", day_of_week="1-5"),
    },
    "nightly-backtest": {
        "task": "app.tasks.backtest_tasks.run_nightly_backtest",
        "schedule": crontab(hour=17, minute=30, day_of_week="1-5"),
    },
    "nightly-embedding-backfill": {
        "task": "app.tasks.embedding_tasks.run_embedding_backfill",
        "schedule": crontab(hour=6, minute=0),  # 6:00 AM ET daily, before morning analysis
    },
    "nightly-ohlcv-ingest": {
        "task": "app.tasks.market_data_ingest_tasks.run_daily_ingest",
        "schedule": crontab(hour=16, minute=35, day_of_week="1-5"),  # 4:35 PM ET after market close
    },
    "sync-ibkr-orders": {
        "task": "app.tasks.ibkr_order_tasks.sync_ibkr_orders_task",
        # Every 30 seconds during market hours (Mon-Fri 9:00–16:30 ET)
        "schedule": 30.0,
    },
}

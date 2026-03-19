from contextlib import asynccontextmanager
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.database import init_db
from app.core.redis_client import init_redis, close_redis
from app.api.v1 import analysis, trades, portfolio, market_data, settings as settings_router, backtest

logger = structlog.get_logger()
app_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up", environment=app_settings.environment)
    await init_db()
    await init_redis()
    yield
    # Shutdown
    logger.info("Shutting down")
    await close_redis()


app = FastAPI(
    title=app_settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002", "https://*.fly.dev"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "environment": app_settings.environment}


app.include_router(analysis.router, prefix="/api/v1/analysis", tags=["analysis"])
app.include_router(trades.router, prefix="/api/v1/trades", tags=["trades"])
app.include_router(portfolio.router, prefix="/api/v1/portfolio", tags=["portfolio"])
app.include_router(market_data.router, prefix="/api/v1/market-data", tags=["market-data"])
app.include_router(settings_router.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(backtest.router, prefix="/api/v1/backtest", tags=["backtest"])

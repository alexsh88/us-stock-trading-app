import json
import structlog
from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from app.core.redis_client import get_redis
from app.config import get_settings
from app.schemas.settings import AppSettings, AppSettingsResponse

logger = structlog.get_logger()
router = APIRouter()

REDIS_KEY = "app:settings"


def _defaults() -> AppSettings:
    cfg = get_settings()
    return AppSettings(
        top_n=cfg.default_top_n,
        trading_mode=cfg.default_trading_mode,
        paper_trading=cfg.paper_trading,
    )


@router.get("/", response_model=AppSettingsResponse)
async def get_app_settings(redis: Redis = Depends(get_redis)):
    raw = await redis.get(REDIS_KEY)
    if raw:
        try:
            return AppSettings(**json.loads(raw))
        except Exception:
            pass
    return _defaults()


@router.patch("/", response_model=AppSettingsResponse)
async def update_app_settings(settings: AppSettings, redis: Redis = Depends(get_redis)):
    await redis.set(REDIS_KEY, settings.model_dump_json())
    logger.info("Settings saved", top_n=settings.top_n, mode=settings.trading_mode)
    return settings

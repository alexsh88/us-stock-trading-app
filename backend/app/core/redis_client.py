import redis.asyncio as aioredis
import structlog
from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

_redis_client: aioredis.Redis | None = None


async def init_redis() -> None:
    global _redis_client
    _redis_client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    await _redis_client.ping()
    logger.info("Redis connected")


async def close_redis() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None


def get_redis() -> aioredis.Redis:
    if _redis_client is None:
        raise RuntimeError("Redis not initialized")
    return _redis_client

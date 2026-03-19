import asyncio
import json
import structlog

logger = structlog.get_logger()


def stream_quotes_to_redis(tickers: list[str]) -> None:
    """Fetch quotes and publish to Redis pub/sub channels."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_stream_async(tickers))
    finally:
        loop.close()


async def _stream_async(tickers: list[str]) -> None:
    import redis.asyncio as aioredis
    import yfinance as yf
    from app.config import get_settings

    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)

    try:
        for ticker in tickers:
            try:
                hist = yf.download(ticker, period="1d", interval="1m", progress=False, auto_adjust=True)
                if hist.empty:
                    continue

                price = float(hist["Close"].iloc[-1])
                volume = float(hist["Volume"].iloc[-1])

                quote = json.dumps({"ticker": ticker, "price": price, "volume": volume, "source": "yfinance"})
                await redis.publish(f"quotes:{ticker}", quote)
                await redis.setex(f"quote:{ticker}", 60, quote)

            except Exception as e:
                logger.warning("Quote stream failed", ticker=ticker, error=str(e))
    finally:
        await redis.aclose()


from app.tasks.celery_app import celery_app
stream_quotes_to_redis = celery_app.task(name="app.tasks.market_data_tasks.stream_quotes_to_redis")(stream_quotes_to_redis)

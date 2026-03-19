import asyncio
import json
import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
import redis.asyncio as aioredis

from app.dependencies import get_redis_client

logger = structlog.get_logger()
router = APIRouter()


@router.get("/stream")
async def stream_quotes(
    tickers: str = Query(..., description="Comma-separated ticker symbols"),
    redis: aioredis.Redis = Depends(get_redis_client),
):
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]

    async def event_generator():
        pubsub = redis.pubsub()
        channels = [f"quotes:{ticker}" for ticker in ticker_list]
        await pubsub.subscribe(*channels)

        try:
            yield f"data: {json.dumps({'type': 'connected', 'tickers': ticker_list})}\n\n"
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(*channels)
            await pubsub.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/ohlcv/{ticker}")
async def get_ohlcv(ticker: str, period: str = "3mo", redis: aioredis.Redis = Depends(get_redis_client)):
    cache_key = f"ohlcv_v2:{ticker.upper()}:{period}"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    try:
        import yfinance as yf
        import pandas as pd

        hist = yf.download(ticker.upper(), period=period, interval="1d", progress=False, auto_adjust=True)
        if hist.empty:
            return {"ticker": ticker.upper(), "candles": [], "bb": [], "swing_highs": [], "swing_lows": []}

        close = hist["Close"].squeeze()
        high = hist["High"].squeeze()
        low = hist["Low"].squeeze()
        volume = hist["Volume"].squeeze()

        # Bollinger Bands (20, 2)
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_upper_s = sma20 + 2 * std20
        bb_lower_s = sma20 - 2 * std20

        # Swing high/low levels (n=5 pivot bars)
        n = 5
        highs_arr = high.values
        lows_arr = low.values
        swing_highs: list[float] = []
        swing_lows: list[float] = []
        for i in range(n, len(highs_arr) - n):
            if all(highs_arr[i] > highs_arr[i - j] for j in range(1, n + 1)) and \
               all(highs_arr[i] > highs_arr[i + j] for j in range(1, n + 1)):
                swing_highs.append(round(float(highs_arr[i]), 4))
            if all(lows_arr[i] < lows_arr[i - j] for j in range(1, n + 1)) and \
               all(lows_arr[i] < lows_arr[i + j] for j in range(1, n + 1)):
                swing_lows.append(round(float(lows_arr[i]), 4))

        candles = []
        bb_data = []
        for i, (ts, row) in enumerate(hist.iterrows()):
            candles.append({
                "time": int(ts.timestamp()),
                "open": round(float(row["Open"].item()), 4),
                "high": round(float(row["High"].item()), 4),
                "low": round(float(row["Low"].item()), 4),
                "close": round(float(row["Close"].item()), 4),
                "volume": int(row["Volume"].item()),
            })
            u = bb_upper_s.iloc[i]
            m = sma20.iloc[i]
            l = bb_lower_s.iloc[i]
            if pd.notna(u) and pd.notna(m) and pd.notna(l):
                bb_data.append({
                    "time": int(ts.timestamp()),
                    "upper": round(float(u), 4),
                    "mid": round(float(m), 4),
                    "lower": round(float(l), 4),
                })

        result = {
            "ticker": ticker.upper(),
            "candles": candles,
            "bb": bb_data,
            "swing_highs": swing_highs[-5:],   # last 5 swing highs (resistance)
            "swing_lows": swing_lows[-5:],     # last 5 swing lows (support)
        }
        await redis.setex(cache_key, 3600, json.dumps(result))  # cache 1h
        return result
    except Exception as e:
        logger.warning("OHLCV fetch failed", ticker=ticker, error=str(e))
        return {"ticker": ticker.upper(), "candles": [], "bb": [], "swing_highs": [], "swing_lows": []}


@router.get("/quote/{ticker}")
async def get_quote(ticker: str, redis: aioredis.Redis = Depends(get_redis_client)):
    cached = await redis.get(f"quote:{ticker.upper()}")
    if cached:
        return json.loads(cached)

    # Fallback: try yfinance
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker.upper())
        info = stock.fast_info
        quote = {
            "ticker": ticker.upper(),
            "price": info.last_price,
            "volume": info.last_volume,
            "source": "yfinance",
        }
        await redis.setex(f"quote:{ticker.upper()}", 60, json.dumps(quote))
        return quote
    except Exception as e:
        logger.warning("Quote fetch failed", ticker=ticker, error=str(e))
        return {"ticker": ticker.upper(), "price": None, "error": "Quote unavailable"}

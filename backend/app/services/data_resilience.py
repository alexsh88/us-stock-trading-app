"""
Circuit breaker and multi-source fallback for price/OHLCV data fetching.

Fallback chain: yfinance → Twelve Data → Tiingo → cached value
Circuit state is shared across all Celery workers via Redis so one worker's
failure immediately prevents others from hammering the same broken source.
"""
import structlog
import pandas as pd
from typing import Optional

logger = structlog.get_logger()

# ── Circuit breakers (lazy-initialized) ──────────────────────────────────────
_breakers: dict = {}


def _get_breaker(name: str):
    if name in _breakers:
        return _breakers[name]
    try:
        import pybreaker
        from app.agents.cache_utils import _sync_redis
        r = _sync_redis()
        if r:
            storage = pybreaker.CircuitRedisStorage(pybreaker.STATE_CLOSED, r, namespace=f"cb:{name}")
        else:
            storage = pybreaker.CircuitMemoryStorage(pybreaker.STATE_CLOSED)
        breaker = pybreaker.CircuitBreaker(
            fail_max=3,
            reset_timeout=300,  # 5 minutes
            state_storage=storage,
            name=name,
        )
        _breakers[name] = breaker
        return breaker
    except ImportError:
        return None  # pybreaker not installed — degrade gracefully


def _fetch_yfinance(tickers: list[str], period: str = "3mo") -> Optional[pd.DataFrame]:
    import yfinance as yf
    data = yf.download(tickers, period=period, interval="1d",
                       progress=False, auto_adjust=True, group_by="ticker")
    if data.empty:
        raise ValueError("yfinance returned empty data")
    return data


def _fetch_twelve_data(tickers: list[str], period: str = "3mo") -> Optional[dict[str, pd.DataFrame]]:
    """Fetch OHLCV from Twelve Data. Returns dict of ticker → DataFrame."""
    from app.config import get_settings, has_twelve_data_key
    if not has_twelve_data_key():
        raise ValueError("No Twelve Data API key configured")
    from twelvedata import TDClient
    td = TDClient(apikey=get_settings().twelve_data_api_key)
    outputsize = 65 if period == "3mo" else 30
    result = {}
    for ticker in tickers:
        try:
            ts = td.time_series(symbol=ticker, interval="1day", outputsize=outputsize).as_pandas()
            if not ts.empty:
                ts = ts.rename(columns={"open": "Open", "high": "High", "low": "Low",
                                         "close": "Close", "volume": "Volume"})
                ts.index = pd.to_datetime(ts.index)
                result[ticker] = ts.sort_index()
        except Exception as e:
            logger.debug("Twelve Data fetch failed for ticker", ticker=ticker, error=str(e))
    if not result:
        raise ValueError("Twelve Data returned no data")
    return result


def fetch_ohlcv_with_fallback(
    tickers: list[str],
    period: str = "3mo",
) -> tuple[Optional[object], str]:
    """
    Fetch OHLCV data with automatic fallback across sources.
    Returns (data, source_name). Data format matches yfinance multi-ticker output
    for compatibility with existing nodes.
    """
    yf_breaker = _get_breaker("yfinance")
    td_breaker = _get_breaker("twelvedata")

    # Try yfinance first
    try:
        if yf_breaker:
            data = yf_breaker.call(_fetch_yfinance, tickers, period)
        else:
            data = _fetch_yfinance(tickers, period)
        return data, "yfinance"
    except Exception as e:
        logger.warning("yfinance failed, trying Twelve Data", error=str(e))

    # Try Twelve Data
    try:
        if td_breaker:
            data = td_breaker.call(_fetch_twelve_data, tickers, period)
        else:
            data = _fetch_twelve_data(tickers, period)
        # Wrap in a format that mimics yfinance multi-ticker output
        return _twelve_data_to_yf_format(data, tickers), "twelvedata"
    except Exception as e:
        logger.warning("Twelve Data failed", error=str(e))

    logger.error("All price data sources failed", tickers=tickers)
    return None, "none"


def _twelve_data_to_yf_format(data: dict[str, pd.DataFrame], tickers: list[str]) -> pd.DataFrame:
    """Convert Twelve Data dict to yfinance-style multi-level DataFrame."""
    if len(tickers) == 1:
        ticker = tickers[0]
        return data.get(ticker, pd.DataFrame())

    # Build multi-level columns like yfinance: (field, ticker)
    dfs = []
    for ticker in tickers:
        if ticker in data:
            df = data[ticker].copy()
            df.columns = pd.MultiIndex.from_tuples([(col, ticker) for col in df.columns])
            dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, axis=1).sort_index()

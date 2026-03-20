"""
Nightly OHLCV ingest + precomputed technicals refresh.

Schedule:
  - run_daily_ingest:    4:35 PM ET Mon-Fri (after market close, before backtest at 5:30 PM)
  - run_ohlcv_backfill:  triggered manually via CLI or admin endpoint

Flow:
  1. Fetch OHLCV for all universe tickers (yfinance)
  2. Upsert rows into market_data_ohlcv
  3. Refresh TimescaleDB continuous aggregate (ohlcv_daily_candles)
  4. Read SMA20/SMA50/VWAP20 from daily_sma_v (1 SQL query for all tickers)
  5. Bulk-load last 200 closes per ticker; compute EMA150 in Python
  6. Bulk upsert into precomputed_technicals
"""
import math
import structlog
from datetime import date, datetime, timezone
from celery import shared_task

logger = structlog.get_logger()


def _get_universe_tickers() -> list[str]:
    """Deduplicated list of all tickers across all sector pools + ETFs."""
    from app.agents.nodes.screener import ETF_SECTOR_STOCKS, FALLBACK_UNIVERSE

    seen: set[str] = set()
    tickers: list[str] = []
    for etf in ETF_SECTOR_STOCKS:
        if etf not in seen:
            seen.add(etf)
            tickers.append(etf)
    for stocks in ETF_SECTOR_STOCKS.values():
        for t in stocks:
            if t not in seen:
                seen.add(t)
                tickers.append(t)
    for t in FALLBACK_UNIVERSE:
        if t not in seen:
            seen.add(t)
            tickers.append(t)
    return tickers


def _get_sync_conn():
    """psycopg2 connection for use in Celery workers."""
    import psycopg2
    from app.config import get_settings
    db_url = get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    return psycopg2.connect(db_url)


def _fetch_and_upsert_ohlcv(tickers: list[str], period: str, cur) -> int:
    """Download OHLCV, upsert into market_data_ohlcv. Returns row count."""
    import yfinance as yf
    import pandas as pd

    try:
        raw = yf.download(
            tickers, period=period, interval="1d",
            progress=False, auto_adjust=True, group_by="ticker",
        )
    except Exception as e:
        logger.error("yfinance download failed", error=str(e))
        return 0

    if raw is None or raw.empty:
        return 0

    rows: list[tuple] = []
    today = date.today()

    def safe_float(v) -> float | None:
        try:
            f = float(v)
            return None if math.isnan(f) else f
        except Exception:
            return None

    for ticker in tickers:
        try:
            if len(tickers) == 1:
                hist = raw
            else:
                hist = raw[ticker] if ticker in raw.columns.get_level_values(0) else pd.DataFrame()
            if hist.empty:
                continue
            for ts, row in hist.iterrows():
                d = ts.date() if hasattr(ts, "date") else today
                open_  = safe_float(row["Open"])
                high_  = safe_float(row["High"])
                low_   = safe_float(row["Low"])
                close_ = safe_float(row["Close"])
                vol_   = safe_float(row["Volume"])
                if None in (open_, high_, low_, close_, vol_):
                    continue
                rows.append((
                    datetime(d.year, d.month, d.day, 21, 0, tzinfo=timezone.utc),
                    ticker,
                    open_, high_, low_, close_, int(vol_), None,
                ))
        except Exception as e:
            logger.warning("OHLCV parse failed", ticker=ticker, error=str(e))

    if not rows:
        return 0

    cur.executemany(
        """
        INSERT INTO market_data_ohlcv (time, ticker, open, high, low, close, volume, vwap)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker, time) DO UPDATE SET
            open   = EXCLUDED.open,
            high   = EXCLUDED.high,
            low    = EXCLUDED.low,
            close  = EXCLUDED.close,
            volume = EXCLUDED.volume
        """,
        rows,
    )
    return len(rows)


def _refresh_precomputed_technicals(tickers: list[str], cur) -> int:
    """
    Refresh precomputed_technicals using TimescaleDB views.

    - SMA20/SMA50/VWAP20: ONE query to daily_sma_v (materialised, all tickers)
    - EMA150: ONE bulk query for last 200 closes from ohlcv_daily_candles, computed in Python
    - ONE bulk executemany upsert

    Reduced from ~N per-ticker SQL queries to 2 queries + 1 bulk upsert.
    Assumes ohlcv_daily_candles has already been refreshed this run.
    """
    import pandas as pd

    today = date.today()
    if not tickers:
        return 0

    placeholders = ",".join(["%s"] * len(tickers))

    # ── 1. SMA20/SMA50/VWAP20 from daily_sma_v (one query, all tickers) ───────
    cur.execute(
        f"""
        SELECT ticker, sma20, sma50, vwap20, close, volume, bucket::date
        FROM (
            SELECT ticker, sma20, sma50, vwap20, close, volume, bucket,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY bucket DESC) AS rn
            FROM daily_sma_v
            WHERE ticker IN ({placeholders})
        ) latest
        WHERE rn = 1 AND sma20 IS NOT NULL
        """,
        tickers,
    )
    # {ticker: (sma20, sma50, vwap20, last_close, last_volume, last_date)}
    sma_map: dict[str, tuple] = {
        row[0]: (row[1], row[2], row[3], row[4], row[5], row[6])
        for row in cur.fetchall()
    }

    if not sma_map:
        logger.warning("daily_sma_v returned no rows — CAGG may need a manual refresh")
        return 0

    # ── 2. Bulk load last 200 closes per ticker (for EMA150) ───────────────────
    cur.execute(
        f"""
        SELECT ticker, close
        FROM (
            SELECT ticker, bucket, close,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY bucket DESC) AS rn
            FROM ohlcv_daily_candles
            WHERE ticker IN ({placeholders})
        ) t
        WHERE rn <= 200
        ORDER BY ticker, bucket ASC
        """,
        tickers,
    )
    closes: dict[str, list[float]] = {}
    for ticker, close_val in cur.fetchall():
        closes.setdefault(ticker, []).append(float(close_val))
    # rows are ASC by bucket so each list is time-ordered oldest→newest

    # ── 3. Compute EMA150 + assemble upsert rows ───────────────────────────────
    upsert_rows: list[tuple] = []
    for ticker, (sma20, sma50, vwap20, last_close, last_volume, last_date_) in sma_map.items():
        close_list = closes.get(ticker, [])
        if len(close_list) < 20:
            continue
        try:
            ema150 = float(
                pd.Series(close_list, dtype=float).ewm(span=150, adjust=False).mean().iloc[-1]
            )
        except Exception:
            continue
        if math.isnan(ema150) or math.isnan(float(sma20)):
            continue

        upsert_rows.append((
            ticker,
            float(sma20),
            float(sma50) if sma50 is not None else None,
            float(vwap20) if vwap20 is not None else None,
            ema150,
            float(last_close),
            int(last_volume) if last_volume is not None else None,
            last_date_ if last_date_ is not None else today,
        ))

    if not upsert_rows:
        return 0

    # ── 4. Bulk upsert ─────────────────────────────────────────────────────────
    cur.executemany(
        """
        INSERT INTO precomputed_technicals
            (ticker, updated_at, sma20, sma50, vwap20, ema150,
             last_close, last_volume, last_date)
        VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker) DO UPDATE SET
            updated_at   = NOW(),
            sma20        = EXCLUDED.sma20,
            sma50        = EXCLUDED.sma50,
            vwap20       = EXCLUDED.vwap20,
            ema150       = EXCLUDED.ema150,
            last_close   = EXCLUDED.last_close,
            last_volume  = EXCLUDED.last_volume,
            last_date    = EXCLUDED.last_date
        """,
        upsert_rows,
    )
    return len(upsert_rows)


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------

@shared_task(name="app.tasks.market_data_ingest_tasks.run_daily_ingest", bind=True, max_retries=2)
def run_daily_ingest(self) -> dict:
    """Nightly ingest: fetch today's candle for full universe, refresh precomputed_technicals."""
    tickers = _get_universe_tickers()
    logger.info("Daily OHLCV ingest starting", ticker_count=len(tickers))

    rows_written = 0
    technicals_updated = 0
    conn = _get_sync_conn()
    try:
        # Step 1: upsert today's candles
        with conn.cursor() as cur:
            rows_written = _fetch_and_upsert_ohlcv(tickers, period="5d", cur=cur)
            logger.info("OHLCV upsert complete", rows=rows_written)
        conn.commit()

        # Step 2: refresh CAGG so daily_sma_v reflects today's candle
        # (must run outside a transaction block)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CALL refresh_continuous_aggregate('ohlcv_daily_candles', NULL, NULL);")
        conn.autocommit = False

        # Step 3: refresh precomputed_technicals (reads daily_sma_v + ohlcv_daily_candles)
        with conn.cursor() as cur:
            technicals_updated = _refresh_precomputed_technicals(tickers, cur=cur)
            logger.info("precomputed_technicals refreshed", tickers_updated=technicals_updated)
        conn.commit()

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("Daily ingest failed", error=str(e))
        raise self.retry(exc=e, countdown=120)
    finally:
        conn.close()

    return {"status": "ok", "rows_written": rows_written, "technicals_updated": technicals_updated}


@shared_task(name="app.tasks.market_data_ingest_tasks.run_ohlcv_backfill", bind=True, max_retries=1)
def run_ohlcv_backfill(self, period: str = "1y") -> dict:
    """
    One-shot backfill: ingest up to 1 year of OHLCV history for the full universe.
    Trigger manually:
      docker compose exec celery-worker celery -A app.tasks.celery_app call \\
        app.tasks.market_data_ingest_tasks.run_ohlcv_backfill
    """
    tickers = _get_universe_tickers()
    logger.info("OHLCV backfill starting", ticker_count=len(tickers), period=period)

    batch_size = 50
    total_rows = 0
    conn = _get_sync_conn()
    try:
        # Step 1: upsert all historical candles in batches
        with conn.cursor() as cur:
            for i in range(0, len(tickers), batch_size):
                batch = tickers[i: i + batch_size]
                rows = _fetch_and_upsert_ohlcv(batch, period=period, cur=cur)
                total_rows += rows
                logger.info("Backfill batch complete",
                            batch=i // batch_size + 1, tickers=len(batch), rows=rows)
        conn.commit()

        # Step 2: refresh CAGG before querying daily_sma_v
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CALL refresh_continuous_aggregate('ohlcv_daily_candles', NULL, NULL);")
        conn.autocommit = False

        # Step 3: refresh precomputed_technicals
        with conn.cursor() as cur:
            technicals_updated = _refresh_precomputed_technicals(tickers, cur=cur)
        conn.commit()

        logger.info("OHLCV backfill complete",
                    total_rows=total_rows, technicals_updated=technicals_updated)
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("Backfill failed", error=str(e))
        raise self.retry(exc=e, countdown=30)
    finally:
        conn.close()

    return {"status": "ok", "total_rows": total_rows, "technicals_updated": technicals_updated}

"""TimescaleDB continuous aggregates + precomputed technicals

Revision ID: 004
Revises: 003
Create Date: 2026-03-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 0. Ensure market_data_ohlcv exists as a TimescaleDB hypertable.
    #    Migration 001 defined this table but was never applied (the DB was
    #    bootstrapped manually and stamped at 002).  Create it here if absent.
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_data_ohlcv (
            time    TIMESTAMPTZ  NOT NULL,
            ticker  VARCHAR(10)  NOT NULL,
            open    DOUBLE PRECISION NOT NULL,
            high    DOUBLE PRECISION NOT NULL,
            low     DOUBLE PRECISION NOT NULL,
            close   DOUBLE PRECISION NOT NULL,
            volume  BIGINT       NOT NULL,
            vwap    DOUBLE PRECISION
        );
    """)
    # Convert to hypertable (no-op if already one)
    op.execute(
        "SELECT create_hypertable('market_data_ohlcv', 'time', if_not_exists => TRUE);"
    )
    # Unique constraint for upserts
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'market_data_ohlcv'
                  AND indexname  = 'uq_ohlcv_ticker_time'
            ) THEN
                CREATE UNIQUE INDEX uq_ohlcv_ticker_time
                    ON market_data_ohlcv (ticker, time);
            END IF;
        END$$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'market_data_ohlcv'
                  AND indexname  = 'ix_ohlcv_ticker_time'
            ) THEN
                CREATE INDEX ix_ohlcv_ticker_time ON market_data_ohlcv (ticker, time);
            END IF;
        END$$;
    """)

    # -------------------------------------------------------------------------
    # 1. Continuous aggregate: compress market_data_ohlcv into daily candles.
    #    The source hypertable may already contain intraday rows; this ensures
    #    exactly one OHLCV candle per (ticker, day) regardless.
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_daily_candles
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 day', time) AS bucket,
            ticker,
            first(open,   time) AS open,
            max(high)           AS high,
            min(low)            AS low,
            last(close,   time) AS close,
            sum(volume)         AS volume
        FROM market_data_ohlcv
        GROUP BY bucket, ticker
        WITH NO DATA;
    """)

    # Auto-refresh: keep the aggregate up to date as new rows arrive.
    # start_offset=7d means recompute only the last 7 days on each refresh.
    op.execute("""
        SELECT add_continuous_aggregate_policy(
            'ohlcv_daily_candles',
            start_offset  => INTERVAL '7 days',
            end_offset    => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour',
            if_not_exists => TRUE
        );
    """)

    # -------------------------------------------------------------------------
    # 2. Regular view: SMA20, SMA50, VWAP20 over the daily candles.
    #    Uses window functions — fast because they operate on the already-
    #    materialised aggregate rather than raw tick data.
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE VIEW daily_sma_v AS
        SELECT
            bucket,
            ticker,
            close,
            volume,
            AVG(close) OVER w20  AS sma20,
            AVG(close) OVER w50  AS sma50,
            -- VWAP approximation: (typical_price × volume) / volume over 20 days
            SUM(close * volume) OVER w20 /
                NULLIF(SUM(volume) OVER w20, 0) AS vwap20
        FROM ohlcv_daily_candles
        WINDOW
            w20 AS (PARTITION BY ticker ORDER BY bucket
                    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
            w50 AS (PARTITION BY ticker ORDER BY bucket
                    ROWS BETWEEN 49 PRECEDING AND CURRENT ROW);
    """)

    # -------------------------------------------------------------------------
    # 3. precomputed_technicals — stores the latest long-lookback indicator
    #    values per ticker.  The nightly ingest task upserts here after each
    #    data fetch so the technical node can skip recomputing them.
    #
    #    Includes ema150 (stored as a value, not recomputed from rolling window)
    #    so the technical node can drop from period="1y" → period="3mo" for
    #    tickers that already have a warm EMA value in the DB.
    # -------------------------------------------------------------------------
    op.create_table(
        "precomputed_technicals",
        sa.Column("ticker",     sa.String(10),             primary_key=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # SMA / VWAP (computed over ohlcv_daily_candles)
        sa.Column("sma20",   sa.Float(), nullable=True),
        sa.Column("sma50",   sa.Float(), nullable=True),
        sa.Column("vwap20",  sa.Float(), nullable=True),
        # EMA150 — stored so the technical node can warm-start an ewm() series
        # using just the last 3 months of daily data instead of 1 year.
        sa.Column("ema150",  sa.Float(), nullable=True),
        # Latest candle metadata (for quick freshness checks)
        sa.Column("last_close",  sa.Float(),     nullable=True),
        sa.Column("last_volume", sa.BigInteger(), nullable=True),
        sa.Column("last_date",   sa.Date(),       nullable=True),
    )


def downgrade() -> None:
    op.drop_table("precomputed_technicals")
    op.execute("DROP VIEW IF EXISTS daily_sma_v;")
    op.execute("""
        SELECT remove_continuous_aggregate_policy('ohlcv_daily_candles', if_not_exists => TRUE);
    """)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS ohlcv_daily_candles;")

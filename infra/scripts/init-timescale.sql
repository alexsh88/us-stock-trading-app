-- TimescaleDB initialization — runs before Alembic migrations
-- This creates the TimescaleDB extension and any pre-migration setup

-- Enable TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- The hypertable conversion happens in Alembic after the table is created
-- But we need the extension ready before any table creation

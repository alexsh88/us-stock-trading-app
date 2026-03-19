-- TimescaleDB initialization — runs before Alembic migrations
-- This creates the TimescaleDB extension and any pre-migration setup

-- Enable TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Enable pgvector (included in timescaledb-ha image)
CREATE EXTENSION IF NOT EXISTS vector;

-- The hypertable conversion happens in Alembic after the table is created
-- But we need the extension ready before any table creation

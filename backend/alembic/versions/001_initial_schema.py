"""Initial schema with TimescaleDB hypertable

Revision ID: 001
Revises:
Create Date: 2026-03-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # analysis_runs
    op.create_table(
        "analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("top_n", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("mode", sa.String(20), nullable=False, server_default="swing"),
        sa.Column("tickers_screened", sa.Integer(), nullable=True),
        sa.Column("signals_generated", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # trade_signals
    op.create_table(
        "trade_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("trading_mode", sa.String(20), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("stop_loss_price", sa.Float(), nullable=True),
        sa.Column("stop_loss_method", sa.String(100), nullable=True),
        sa.Column("take_profit_price", sa.Float(), nullable=True),
        sa.Column("risk_reward_ratio", sa.Float(), nullable=True),
        sa.Column("position_size_pct", sa.Float(), nullable=True),
        sa.Column("technical_score", sa.Float(), nullable=True),
        sa.Column("fundamental_score", sa.Float(), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("catalyst_score", sa.Float(), nullable=True),
        sa.Column("key_risks", postgresql.JSON(), nullable=True),
        sa.Column("reasoning", sa.String(5000), nullable=True),
        sa.Column("is_paper", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_trade_signals_ticker", "trade_signals", ["ticker"])
    op.create_index("ix_trade_signals_run_id", "trade_signals", ["run_id"])

    # portfolios
    op.create_table(
        "portfolios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_paper", sa.Boolean(), server_default="true"),
        sa.Column("initial_capital", sa.Float(), server_default="100000.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # positions
    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trade_signals.id"), nullable=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_loss_price", sa.Float(), nullable=True),
        sa.Column("take_profit_price", sa.Float(), nullable=True),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), server_default="open"),
        sa.Column("is_paper", sa.Boolean(), server_default="true"),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_positions_portfolio_id", "positions", ["portfolio_id"])
    op.create_index("ix_positions_ticker", "positions", ["ticker"])

    # market_data_ohlcv — TimescaleDB hypertable
    op.create_table(
        "market_data_ohlcv",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("vwap", sa.Float(), nullable=True),
    )

    # Convert to hypertable (TimescaleDB)
    op.execute("SELECT create_hypertable('market_data_ohlcv', 'time', if_not_exists => TRUE);")
    op.execute("SELECT add_compression_policy('market_data_ohlcv', INTERVAL '7 days');")
    op.create_index("ix_ohlcv_ticker_time", "market_data_ohlcv", ["ticker", "time"])


def downgrade() -> None:
    op.drop_table("market_data_ohlcv")
    op.drop_table("positions")
    op.drop_table("portfolios")
    op.drop_table("trade_signals")
    op.drop_table("analysis_runs")

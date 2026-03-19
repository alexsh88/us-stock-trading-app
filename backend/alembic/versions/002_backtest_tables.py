"""Add signal_outcomes and factor_ic tables for backtesting

Revision ID: 002
Revises: 001
Create Date: 2026-03-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signal_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trade_signals.id"), unique=True, nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("signal_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column("entry_price", sa.Float, nullable=True),
        sa.Column("stop_loss_price", sa.Float, nullable=True),
        sa.Column("take_profit_price", sa.Float, nullable=True),
        sa.Column("technical_score", sa.Float, nullable=True),
        sa.Column("fundamental_score", sa.Float, nullable=True),
        sa.Column("sentiment_score", sa.Float, nullable=True),
        sa.Column("catalyst_score", sa.Float, nullable=True),
        sa.Column("trading_mode", sa.String(20), nullable=True),
        sa.Column("price_1d", sa.Float, nullable=True),
        sa.Column("price_2d", sa.Float, nullable=True),
        sa.Column("price_3d", sa.Float, nullable=True),
        sa.Column("price_5d", sa.Float, nullable=True),
        sa.Column("return_1d", sa.Float, nullable=True),
        sa.Column("return_2d", sa.Float, nullable=True),
        sa.Column("return_3d", sa.Float, nullable=True),
        sa.Column("return_5d", sa.Float, nullable=True),
        sa.Column("sl_hit", sa.Boolean, nullable=True),
        sa.Column("tp_hit", sa.Boolean, nullable=True),
        sa.Column("sl_hit_day", sa.Integer, nullable=True),
        sa.Column("tp_hit_day", sa.Integer, nullable=True),
        sa.Column("r_multiple", sa.Float, nullable=True),
        sa.Column("correct_direction_1d", sa.Boolean, nullable=True),
        sa.Column("correct_direction_3d", sa.Boolean, nullable=True),
        sa.Column("correct_direction_5d", sa.Boolean, nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_complete", sa.Boolean, default=False, nullable=False),
    )
    op.create_index("ix_signal_outcomes_ticker", "signal_outcomes", ["ticker"])
    op.create_index("ix_signal_outcomes_signal_date", "signal_outcomes", ["signal_date"])
    op.create_index("ix_signal_outcomes_is_complete", "signal_outcomes", ["is_complete"])

    op.create_table(
        "factor_ic",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("factor", sa.String(30), nullable=False),
        sa.Column("horizon", sa.Integer, nullable=False),
        sa.Column("trading_mode", sa.String(20), nullable=False, server_default="swing"),
        sa.Column("ic", sa.Float, nullable=False),
        sa.Column("n_signals", sa.Integer, nullable=False),
        sa.Column("ic_mean_30d", sa.Float, nullable=True),
        sa.Column("ic_ir", sa.Float, nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_factor_ic_factor_date", "factor_ic", ["factor", "date"])


def downgrade() -> None:
    op.drop_table("factor_ic")
    op.drop_table("signal_outcomes")

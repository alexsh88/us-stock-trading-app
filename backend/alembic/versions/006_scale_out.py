"""Add partial scale-out support: take_profit_price_2 on signals, scale-out fields on positions

Revision ID: 006
Revises: 005
Create Date: 2026-03-20
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Second take-profit target on signals (Fib 1.618x or next resistance level)
    op.add_column(
        "trade_signals",
        sa.Column("take_profit_price_2", sa.Float, nullable=True),
    )

    # Scale-out tracking on positions
    op.add_column("positions", sa.Column("target2_price", sa.Float, nullable=True))
    op.add_column("positions", sa.Column("scale_out_stage", sa.Integer, nullable=False, server_default="0"))
    op.add_column("positions", sa.Column("partial_realized_pnl", sa.Float, nullable=True))
    op.add_column("positions", sa.Column("stop_loss_method", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("trade_signals", "take_profit_price_2")
    op.drop_column("positions", "target2_price")
    op.drop_column("positions", "scale_out_stage")
    op.drop_column("positions", "partial_realized_pnl")
    op.drop_column("positions", "stop_loss_method")

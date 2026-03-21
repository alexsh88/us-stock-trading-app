"""Add ibkr_orders table and IBKR order tracking columns on positions

Revision ID: 007
Revises: 006
Create Date: 2026-03-21
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum types
    op.execute("CREATE TYPE ibkrordertype AS ENUM ('PARENT', 'STOP', 'TAKE_PROFIT', 'TAKE_PROFIT_2')")
    op.execute("CREATE TYPE ibkrorderstatus AS ENUM ('Submitted', 'PreSubmitted', 'Filled', 'Cancelled', 'Inactive', 'Unknown')")

    # Create ibkr_orders table
    op.create_table(
        "ibkr_orders",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("position_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("signal_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("trade_signals.id"), nullable=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("order_type", sa.Enum("PARENT", "STOP", "TAKE_PROFIT", "TAKE_PROFIT_2", name="ibkrordertype", create_type=False), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("limit_price", sa.Float, nullable=True),
        sa.Column("stop_price", sa.Float, nullable=True),
        sa.Column("tws_order_id", sa.Integer, nullable=True),
        sa.Column("tws_perm_id", sa.Integer, nullable=True),
        sa.Column("parent_tws_order_id", sa.Integer, nullable=True),
        sa.Column("status", sa.Enum("Submitted", "PreSubmitted", "Filled", "Cancelled", "Inactive", "Unknown", name="ibkrorderstatus", create_type=False), nullable=False, server_default="Submitted"),
        sa.Column("filled_qty", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_fill_price", sa.Float, nullable=True),
        sa.Column("is_paper", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_ibkr_orders_position_id", "ibkr_orders", ["position_id"])
    op.create_index("ix_ibkr_orders_tws_order_id", "ibkr_orders", ["tws_order_id"])

    # Add IBKR order ID columns to positions
    op.add_column("positions", sa.Column("ibkr_parent_order_id", sa.Integer, nullable=True))
    op.add_column("positions", sa.Column("ibkr_stop_order_id", sa.Integer, nullable=True))
    op.add_column("positions", sa.Column("ibkr_tp1_order_id", sa.Integer, nullable=True))
    op.add_column("positions", sa.Column("ibkr_tp2_order_id", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("positions", "ibkr_tp2_order_id")
    op.drop_column("positions", "ibkr_tp1_order_id")
    op.drop_column("positions", "ibkr_stop_order_id")
    op.drop_column("positions", "ibkr_parent_order_id")
    op.drop_index("ix_ibkr_orders_tws_order_id", table_name="ibkr_orders")
    op.drop_index("ix_ibkr_orders_position_id", table_name="ibkr_orders")
    op.drop_table("ibkr_orders")
    op.execute("DROP TYPE IF EXISTS ibkrordertype")
    op.execute("DROP TYPE IF EXISTS ibkrorderstatus")

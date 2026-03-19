"""Add detected_patterns JSONB column to trade_signals

Revision ID: 005
Revises: 004
Create Date: 2026-03-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trade_signals",
        sa.Column("detected_patterns", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trade_signals", "detected_patterns")

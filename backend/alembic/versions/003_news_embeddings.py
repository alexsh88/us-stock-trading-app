"""Add news_embeddings table with pgvector for semantic similarity search

Revision ID: 003
Revises: 002
Create Date: 2026-03-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure pgvector extension is available (timescaledb-ha image includes it)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "news_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(10), nullable=False, index=True),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "embedding",
            postgresql.ARRAY(sa.Float()),
            nullable=True,
            comment="1536-dim text-embedding-3-small vector stored as float array",
        ),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # IVFFlat index for approximate nearest-neighbor search on embedding column
    # Only create if the vector type is available (pgvector loaded)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
                -- Add proper vector column and index using raw DDL
                ALTER TABLE news_embeddings ADD COLUMN IF NOT EXISTS embedding_vec vector(1536);
                CREATE INDEX IF NOT EXISTS news_embeddings_vec_idx
                    ON news_embeddings USING ivfflat (embedding_vec vector_cosine_ops)
                    WITH (lists = 100);
            END IF;
        END
        $$;
    """)

    # Composite index for ticker + time queries
    op.create_index(
        "ix_news_embeddings_ticker_published",
        "news_embeddings",
        ["ticker", "published_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_news_embeddings_ticker_published", table_name="news_embeddings")
    op.drop_table("news_embeddings")

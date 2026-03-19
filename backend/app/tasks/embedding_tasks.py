"""
Nightly embedding backfill task.

For each news_embeddings row where embedding_vec IS NULL, calls OpenAI
text-embedding-3-small to generate a 1536-dim vector and stores it back.

Runs at 6:00 AM ET daily (before the morning analysis run).
Cost: ~$0.002 / 1M tokens; a full day of headlines ≈ 100-200 rows ≈ $0.000005 — negligible.
"""
import structlog

logger = structlog.get_logger()

EMBEDDING_MODEL = "text-embedding-3-small"
EMBED_DIMENSIONS = 1536
BATCH_SIZE = 100  # OpenAI allows up to 2048 per request


def _get_sync_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import get_settings

    settings = get_settings()
    sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    engine = create_engine(sync_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _has_openai_key() -> bool:
    try:
        from app.config import get_settings
        key = get_settings().openai_api_key
        return bool(key) and not key.startswith("your_") and len(key) > 20
    except Exception:
        return False


def _embed_texts(client, texts: list[str]) -> list[list[float]]:
    """Call OpenAI embedding API for a batch of texts. Returns list of vectors."""
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
        dimensions=EMBED_DIMENSIONS,
    )
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


def run_embedding_backfill() -> dict:
    """
    Celery task: fills NULL embedding_vec rows in news_embeddings.
    Processes up to 500 rows per run to stay within rate limits.
    """
    if not _has_openai_key():
        logger.info("Embedding backfill skipped — no OpenAI API key configured")
        return {"status": "skipped", "reason": "no_openai_key"}

    try:
        from openai import OpenAI
        from sqlalchemy import text
        from app.config import get_settings

        settings = get_settings()
        client = OpenAI(api_key=settings.openai_api_key)
    except ImportError as e:
        logger.warning("Embedding backfill skipped — openai package not installed", error=str(e))
        return {"status": "skipped", "reason": "openai_not_installed"}

    session, engine = _get_sync_session()
    total_embedded = 0

    try:
        # Fetch rows needing embeddings (up to 500 per run)
        rows = session.execute(
            text("""
                SELECT id, headline, ticker
                FROM news_embeddings
                WHERE embedding_vec IS NULL
                ORDER BY published_at DESC
                LIMIT 500
            """)
        ).fetchall()

        if not rows:
            logger.info("Embedding backfill: no pending rows")
            return {"status": "ok", "embedded": 0}

        logger.info("Embedding backfill starting", pending=len(rows))

        # Process in batches
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i: i + BATCH_SIZE]
            row_ids = [r[0] for r in batch]
            texts = [r[1] for r in batch]  # headline text

            try:
                vectors = _embed_texts(client, texts)

                for row_id, vector in zip(row_ids, vectors):
                    # pgvector accepts Python lists for the vector column
                    session.execute(
                        text("""
                            UPDATE news_embeddings
                            SET embedding_vec = CAST(:vec AS vector)
                            WHERE id = :id
                        """),
                        {"vec": f"[{','.join(str(v) for v in vector)}]", "id": row_id},
                    )

                session.commit()
                total_embedded += len(batch)
                logger.info("Embedding batch complete", batch_size=len(batch), total=total_embedded)

            except Exception as e:
                session.rollback()
                logger.error("Embedding batch failed", error=str(e), batch_start=i)
                break

        logger.info("Embedding backfill complete", total_embedded=total_embedded)
        return {"status": "ok", "embedded": total_embedded}

    except Exception as e:
        logger.error("Embedding backfill failed", error=str(e))
        raise
    finally:
        session.close()
        engine.dispose()


def fetch_similar_headlines(
    ticker: str,
    headlines: list[str],
    limit: int = 5,
) -> list[dict]:
    """
    For a given ticker and its current headlines, find the most semantically
    similar past headlines that have completed signal outcomes (T+5 data available).

    Returns list of dicts: {headline, ticker, return_5d, signal_date}
    Used by the synthesizer to provide historical context.
    """
    if not _has_openai_key() or not headlines:
        return []

    try:
        from openai import OpenAI
        from sqlalchemy import text
        from app.config import get_settings

        settings = get_settings()
        client = OpenAI(api_key=settings.openai_api_key)

        # Embed the current headlines (combined as one query vector)
        query_text = " | ".join(headlines[:5])  # cap at 5 headlines
        vectors = _embed_texts(client, [query_text])
        query_vec = vectors[0]
        vec_str = f"[{','.join(str(v) for v in query_vec)}]"

        session, engine = _get_sync_session()
        try:
            rows = session.execute(
                text("""
                    SELECT
                        ne.headline,
                        ne.ticker,
                        so.return_5d,
                        so.return_1d,
                        so.tp_hit,
                        so.sl_hit,
                        ne.published_at,
                        1 - (ne.embedding_vec <=> CAST(:vec AS vector)) AS similarity
                    FROM news_embeddings ne
                    JOIN trade_signals ts ON ts.ticker = ne.ticker
                        AND DATE(ts.created_at) = DATE(ne.published_at)
                    JOIN signal_outcomes so ON so.signal_id = ts.id
                    WHERE ne.embedding_vec IS NOT NULL
                      AND so.is_complete = TRUE
                      AND so.return_5d IS NOT NULL
                    ORDER BY ne.embedding_vec <=> CAST(:vec AS vector)
                    LIMIT :limit
                """),
                {"vec": vec_str, "limit": limit},
            ).fetchall()

            return [
                {
                    "headline": row[0],
                    "ticker": row[1],
                    "return_5d": round(row[2] * 100, 1) if row[2] is not None else None,
                    "return_1d": round(row[3] * 100, 1) if row[3] is not None else None,
                    "tp_hit": row[4],
                    "sl_hit": row[5],
                    "date": row[6].strftime("%Y-%m-%d") if row[6] else None,
                    "similarity": round(row[7], 3) if row[7] is not None else None,
                }
                for row in rows
            ]
        finally:
            session.close()
            engine.dispose()

    except Exception as e:
        logger.warning("fetch_similar_headlines failed", ticker=ticker, error=str(e))
        return []


# Register with Celery
from app.tasks.celery_app import celery_app  # noqa: E402

run_embedding_backfill = celery_app.task(
    name="app.tasks.embedding_tasks.run_embedding_backfill"
)(run_embedding_backfill)

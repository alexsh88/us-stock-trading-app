"""
Synchronous Redis cache helpers for Celery agent nodes.

TTLs:
  technical   : 2h   — indicators scored daily, stable intraday
  fundamental : 24h  — quarterly data changes very slowly
  sentiment   : 30m  — news and social signals move fast
  catalyst    : 4h   — earnings dates change slowly
  sector      : 4h   — sector rankings stable through the trading day
"""

import json
import structlog
from datetime import datetime

logger = structlog.get_logger()

TTL_TECHNICAL   = 7_200   # 2 hours
TTL_FUNDAMENTAL = 86_400  # 24 hours
TTL_SENTIMENT   = 1_800   # 30 minutes
TTL_CATALYST    = 14_400  # 4 hours
TTL_SECTOR      = 14_400  # 4 hours

_NODE_TTL: dict[str, int] = {
    "technical":   TTL_TECHNICAL,
    "fundamental": TTL_FUNDAMENTAL,
    "sentiment":   TTL_SENTIMENT,
    "catalyst":    TTL_CATALYST,
}


def _sync_redis():
    """Return a synchronous Redis client. Returns None on any failure."""
    try:
        import redis as _redis
        from app.config import get_settings
        return _redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
        )
    except Exception:
        return None


def _time_bucket(node: str) -> str:
    """Return time-bucket string for the cache key.
    Sentiment uses hourly buckets (30-min TTL keeps it fresh).
    All others use a daily bucket.
    """
    if node == "sentiment":
        return datetime.now().strftime("%Y-%m-%d-%H")
    return datetime.now().strftime("%Y-%m-%d")


def score_get(node: str, ticker: str, mode: str = "") -> dict | None:
    """Return cached LLM score dict {score, reasoning} for a ticker, or None on miss."""
    try:
        r = _sync_redis()
        if r is None:
            return None
        bucket = _time_bucket(node)
        key = f"{node}:v1:{bucket}:{mode}:{ticker}" if mode else f"{node}:v1:{bucket}:{ticker}"
        raw = r.get(key)
        if raw:
            logger.debug("Cache hit", node=node, ticker=ticker)
            return json.loads(raw)
    except Exception as e:
        logger.debug("Cache get error", node=node, ticker=ticker, error=str(e))
    return None


def score_set(node: str, ticker: str, data: dict, mode: str = "") -> None:
    """Persist LLM score dict for a ticker."""
    try:
        r = _sync_redis()
        if r is None:
            return
        ttl = _NODE_TTL.get(node, TTL_TECHNICAL)
        bucket = _time_bucket(node)
        key = f"{node}:v1:{bucket}:{mode}:{ticker}" if mode else f"{node}:v1:{bucket}:{ticker}"
        r.setex(key, ttl, json.dumps(data))
    except Exception as e:
        logger.debug("Cache set error", node=node, ticker=ticker, error=str(e))


def sector_get(mode: str) -> dict | None:
    """Return cached sector rotation result {favored_sectors, sector_scores}, or None."""
    try:
        r = _sync_redis()
        if r is None:
            return None
        key = f"sector:v1:{datetime.now().strftime('%Y-%m-%d')}:{mode}"
        raw = r.get(key)
        if raw:
            logger.debug("Sector cache hit", mode=mode)
            return json.loads(raw)
    except Exception as e:
        logger.debug("Sector cache get error", error=str(e))
    return None


def sector_set(mode: str, data: dict) -> None:
    """Persist sector rotation result."""
    try:
        r = _sync_redis()
        if r is None:
            return
        key = f"sector:v1:{datetime.now().strftime('%Y-%m-%d')}:{mode}"
        r.setex(key, TTL_SECTOR, json.dumps(data))
    except Exception as e:
        logger.debug("Sector cache set error", error=str(e))


# Default weights used when no IC history exists
_DEFAULT_WEIGHTS = {
    "technical":   0.35,
    "fundamental": 0.25,
    "sentiment":   0.20,
    "catalyst":    0.20,
}
_IC_WEIGHTS_TTL = 86_400  # 24h — recomputed nightly after backtest


def get_factor_weights(mode: str = "swing") -> dict[str, float]:
    """Return IC-weighted composite scoring weights for each factor.

    Reads today's weights from Redis (set by the nightly backtest task).
    Falls back to static defaults if not available.

    Returns dict with keys: technical, fundamental, sentiment, catalyst.
    """
    try:
        r = _sync_redis()
        if r:
            key = f"ic_weights:v1:{datetime.now().strftime('%Y-%m-%d')}:{mode}"
            raw = r.get(key)
            if raw:
                weights = json.loads(raw)
                logger.debug("IC weights cache hit", mode=mode)
                return weights
    except Exception as e:
        logger.debug("IC weights cache get error", error=str(e))

    # Cache miss — try to compute from DB
    try:
        weights = _compute_ic_weights_from_db(mode)
        if weights:
            try:
                r = _sync_redis()
                if r:
                    key = f"ic_weights:v1:{datetime.now().strftime('%Y-%m-%d')}:{mode}"
                    r.setex(key, _IC_WEIGHTS_TTL, json.dumps(weights))
            except Exception:
                pass
            return weights
    except Exception as e:
        logger.debug("IC weights DB computation failed", error=str(e))

    return dict(_DEFAULT_WEIGHTS)


def _compute_ic_weights_from_db(mode: str = "swing") -> dict[str, float] | None:
    """Query latest factor IC from DB and compute softmax-normalized weights.

    Returns None if insufficient data (<10 signals or no IC rows).
    """
    from sqlalchemy import create_engine, text
    from app.config import get_settings

    settings = get_settings()
    sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    engine = create_engine(sync_url, pool_pre_ping=True)

    FACTOR_MAP = {
        "technical_score":   "technical",
        "fundamental_score": "fundamental",
        "sentiment_score":   "sentiment",
        "catalyst_score":    "catalyst",
    }
    HORIZON = 3  # 3-day forward return is the most relevant for swing

    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT ON (factor)
                    factor, ic, ic_mean_30d, n_signals
                FROM factor_ic
                WHERE horizon = :horizon AND trading_mode = :mode
                ORDER BY factor, date DESC
            """), {"horizon": HORIZON, "mode": mode}).fetchall()
    finally:
        engine.dispose()

    if not rows:
        return None

    # Build raw IC values (use ic_mean_30d if available, else ic)
    raw: dict[str, float] = {}
    for row in rows:
        factor_key = FACTOR_MAP.get(row[0], row[0].replace("_score", ""))
        ic_val = row[2] if row[2] is not None else row[1]  # ic_mean_30d ?? ic
        # Clamp to [0, 1] — negative IC factors get floored at 0.05 (still used, minimally)
        raw[factor_key] = max(0.05, float(ic_val)) if ic_val is not None else _DEFAULT_WEIGHTS.get(factor_key, 0.25)

    if len(raw) < 4:
        return None  # Not enough factors measured yet

    # Softmax normalization so weights sum to 1.0
    import math
    exp_vals = {k: math.exp(v * 5) for k, v in raw.items()}  # scale before softmax
    total = sum(exp_vals.values())
    weights = {k: round(v / total, 4) for k, v in exp_vals.items()}

    logger.info("IC-computed factor weights", weights=weights, mode=mode)
    return weights


def _fit_logistic(X: "np.ndarray", y: "np.ndarray", lr: float = 0.1, epochs: int = 500) -> tuple[float, float]:
    """Fit logistic regression (A, B) via gradient descent.
    Returns (A, B) such that sigmoid(A*x + B) approximates P(y=1|x).
    """
    import numpy as np
    A, B = 1.0, 0.0
    n = len(X)
    for _ in range(epochs):
        logit = A * X + B
        # Clamp to avoid overflow
        logit = np.clip(logit, -30, 30)
        prob = 1.0 / (1.0 + np.exp(-logit))
        err = prob - y
        dA = float((err * X).mean())
        dB = float(err.mean())
        A -= lr * dA
        B -= lr * dB
    return A, B


def set_factor_weights(mode: str, weights: dict[str, float]) -> None:
    """Explicitly store factor weights (called by backtest task after IC computation)."""
    try:
        r = _sync_redis()
        if r:
            key = f"ic_weights:v1:{datetime.now().strftime('%Y-%m-%d')}:{mode}"
            r.setex(key, _IC_WEIGHTS_TTL, json.dumps(weights))
    except Exception as e:
        logger.debug("IC weights set error", error=str(e))


# ── Platt Scaling (confidence calibration) ────────────────────────────────────

_PLATT_TTL = 86_400  # 24h
_MIN_CALIBRATION_SAMPLES = 50  # require at least this many completed signals


def calibrate_confidence(raw_score: float, mode: str = "swing") -> float:
    """Apply Platt scaling to a raw LLM confidence score.

    Returns a calibrated probability in [0, 1].
    Falls back to raw_score if calibration parameters are not available.
    """
    params = _get_platt_params(mode)
    if params is None:
        return raw_score

    A = params["A"]
    B = params["B"]
    import math
    try:
        return round(1.0 / (1.0 + math.exp(A * raw_score + B)), 4)
    except Exception:
        return raw_score


def _get_platt_params(mode: str) -> dict | None:
    """Return cached Platt parameters {A, B} or None."""
    try:
        r = _sync_redis()
        if r:
            key = f"platt:v1:{datetime.now().strftime('%Y-%m-%d')}:{mode}"
            raw = r.get(key)
            if raw:
                return json.loads(raw)
    except Exception:
        pass
    return None


def fit_platt_calibration(mode: str = "swing") -> dict | None:
    """Fit Platt scaling using completed signal outcomes.

    Uses logistic regression: label = correct_direction_3d, feature = confidence_score.
    Returns {A, B, n_samples} or None if insufficient data.
    """
    from sqlalchemy import create_engine, text
    from app.config import get_settings

    settings = get_settings()
    sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    engine = create_engine(sync_url, pool_pre_ping=True)

    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT confidence_score, correct_direction_3d
                FROM signal_outcomes
                WHERE is_complete = TRUE
                  AND correct_direction_3d IS NOT NULL
                  AND trading_mode = :mode
                ORDER BY signal_date DESC
                LIMIT 500
            """), {"mode": mode}).fetchall()
    finally:
        engine.dispose()

    if len(rows) < _MIN_CALIBRATION_SAMPLES:
        logger.info("Platt calibration: insufficient data", n=len(rows), required=_MIN_CALIBRATION_SAMPLES)
        return None

    import numpy as np

    X = np.array([r[0] for r in rows], dtype=float)
    y = np.array([1.0 if r[1] else 0.0 for r in rows])

    # Platt scaling via gradient descent on logistic loss
    # sigmoid(A * x + B) = P(correct)
    A, B = _fit_logistic(X, y)
    params = {"A": float(A), "B": float(B), "n_samples": len(rows)}

    logger.info("Platt calibration fitted", mode=mode, A=A, B=B, n=len(rows))

    # Cache the parameters
    try:
        r = _sync_redis()
        if r:
            key = f"platt:v1:{datetime.now().strftime('%Y-%m-%d')}:{mode}"
            r.setex(key, _PLATT_TTL, json.dumps(params))
    except Exception as e:
        logger.debug("Platt cache set error", error=str(e))

    return params

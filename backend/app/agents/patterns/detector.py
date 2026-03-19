"""
detect_all_patterns — runs all 7 pattern detectors and returns the best bullish
and best bearish result (for short signals).

Priority for best result selection: highest strength score, then most recent
(largest bars_forming proxy via rs_idx/right_lip order). Strength < 0.42 is
filtered out entirely (noise floor).
"""
import pandas as pd
from typing import Optional
from app.agents.patterns.base import PatternResult
from app.agents.patterns.bull_flag import detect_bull_flag
from app.agents.patterns.double_bottom import detect_double_bottom, detect_double_top
from app.agents.patterns.triangle import detect_ascending_triangle, detect_descending_triangle
from app.agents.patterns.vcp import detect_vcp
from app.agents.patterns.cup_handle import detect_cup_handle
from app.agents.patterns.head_shoulders import detect_inverse_head_shoulders, detect_head_shoulders


def detect_all_patterns(
    hist: pd.DataFrame,
    weekly_hist: Optional[pd.DataFrame] = None,
) -> dict:
    """
    Run all pattern detectors against the daily OHLCV DataFrame.

    Returns a dict with:
      "best_bullish":  PatternResult | None  — highest-strength bullish pattern
      "best_bearish":  PatternResult | None  — highest-strength bearish pattern
      "all_bullish":   list[PatternResult]   — all detected bullish patterns (strength ≥ 0.42)
      "all_bearish":   list[PatternResult]   — all detected bearish patterns

    hist must have columns: Close, High, Low, Volume (capitalised, as from yfinance).
    """
    empty = {"best_bullish": None, "best_bearish": None, "all_bullish": [], "all_bearish": []}

    if hist is None or hist.empty or len(hist) < 20:
        return empty

    try:
        close  = hist["Close"].squeeze()
        high   = hist["High"].squeeze()
        low    = hist["Low"].squeeze()
        volume = hist["Volume"].squeeze()
    except KeyError:
        return empty

    # ── Bullish detectors ───────────────────────────────────────────────────
    bullish_results: list[PatternResult] = []

    for fn in (
        detect_bull_flag,
        detect_double_bottom,
        detect_ascending_triangle,
        detect_vcp,
        detect_cup_handle,
        detect_inverse_head_shoulders,
    ):
        try:
            r = fn(close, high, low, volume)
            if r.detected:
                bullish_results.append(r)
        except Exception:
            pass

    # ── Bearish detectors ───────────────────────────────────────────────────
    bearish_results: list[PatternResult] = []

    for fn in (
        detect_double_top,
        detect_descending_triangle,
        detect_head_shoulders,
    ):
        try:
            r = fn(close, high, low, volume)
            if r.detected:
                bearish_results.append(r)
        except Exception:
            pass

    best_bullish = max(bullish_results, key=lambda r: r.strength) if bullish_results else None
    best_bearish = max(bearish_results, key=lambda r: r.strength) if bearish_results else None

    return {
        "best_bullish": best_bullish,
        "best_bearish": best_bearish,
        "all_bullish": bullish_results,
        "all_bearish": bearish_results,
    }


def pattern_to_dict(r: PatternResult) -> dict:
    """Serialise a PatternResult to a plain dict (for JSON storage)."""
    return {
        "name": r.name,
        "strength": r.strength,
        "pivot": r.pivot,
        "stop": r.pattern_stop,
        "target": r.pattern_target,
        "bars_forming": r.bars_forming,
        "details": r.details,
    }

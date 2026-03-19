"""Shared types and helper utilities for chart pattern detection."""
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd


@dataclass
class PatternResult:
    name: str                          # "bull_flag", "double_bottom", etc.
    detected: bool
    strength: float                    # 0.0–1.0 quality/confidence score
    pivot: Optional[float] = None      # ideal buy point (breakout level)
    pattern_stop: Optional[float] = None   # pattern-specific stop loss
    pattern_target: Optional[float] = None # pattern height projection
    bars_forming: int = 0              # how many bars the pattern spans
    details: str = ""                  # human-readable description


def find_swing_highs(high: pd.Series, n: int = 5) -> list[tuple[int, float]]:
    """Return list of (bar_index, price) for all swing highs in the series."""
    result = []
    arr = high.values
    for i in range(n, len(arr) - n):
        if all(arr[i] > arr[i - j] for j in range(1, n + 1)) and \
           all(arr[i] > arr[i + j] for j in range(1, n + 1)):
            result.append((i, float(arr[i])))
    return result


def find_swing_lows(low: pd.Series, n: int = 5) -> list[tuple[int, float]]:
    """Return list of (bar_index, price) for all swing lows in the series."""
    result = []
    arr = low.values
    for i in range(n, len(arr) - n):
        if all(arr[i] < arr[i - j] for j in range(1, n + 1)) and \
           all(arr[i] < arr[i + j] for j in range(1, n + 1)):
            result.append((i, float(arr[i])))
    return result


def linear_slope(values: list[float]) -> float:
    """Return the linear regression slope of a list of values."""
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    if np.std(x) == 0:
        return 0.0
    return float(np.polyfit(x, y, 1)[0])


def volume_avg(volume: pd.Series, bars: int) -> float:
    """Average volume over the last N bars."""
    v = volume.tail(bars)
    if v.empty:
        return 0.0
    return float(v.mean())


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))

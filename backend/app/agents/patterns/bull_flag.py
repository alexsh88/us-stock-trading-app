"""
Bull Flag pattern detection.

Setup:  Strong impulse pole (≥15% in 5-25 bars) → tight rectangular
        consolidation on declining volume (3-10 bars) → price near pivot.
Signal: BUY when price breaks above the flag's upper boundary.
Stop:   Low of the flag consolidation.
Target: Entry + pole height (measured low-to-high of the pole).
"""
import pandas as pd
from app.agents.patterns.base import PatternResult, clamp


def detect_bull_flag(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    min_pole_pct: float = 15.0,
    max_flag_bars: int = 10,
    min_flag_bars: int = 3,
    max_flag_retrace_pct: float = 50.0,
) -> PatternResult:
    """Detect a bull flag in the most recent price data."""
    not_found = PatternResult(name="bull_flag", detected=False, strength=0.0)

    n = len(close)
    if n < 30:
        return not_found

    arr_c = close.values
    arr_h = high.values
    arr_l = low.values
    arr_v = volume.values

    current_price = float(arr_c[-1])

    # --- Step 1: Find the most recent pole ---
    # Scan backwards for a strong directional run ending at a local high.
    # A pole ends at the highest point before the current consolidation.
    best_pole_end = -1
    best_pole_start = -1
    best_pole_pct = 0.0

    for pole_end in range(n - min_flag_bars - 1, max(n - 60, 5), -1):
        for pole_len in range(5, 26):
            pole_start = pole_end - pole_len
            if pole_start < 0:
                break
            pole_low  = float(arr_l[pole_start: pole_end + 1].min())
            pole_high = float(arr_h[pole_end])
            if pole_low <= 0:
                continue
            pct = (pole_high - pole_low) / pole_low * 100
            if pct >= min_pole_pct and pct > best_pole_pct:
                # Pole high must be the highest point in this range
                if float(arr_h[pole_start: pole_end + 1].max()) == pole_high:
                    best_pole_pct = pct
                    best_pole_end = pole_end
                    best_pole_start = pole_start

    if best_pole_end < 0:
        return not_found

    # --- Step 2: Identify flag (consolidation after pole top) ---
    flag_start = best_pole_end + 1
    flag_end   = n - 1

    flag_bars = flag_end - flag_start + 1
    if not (min_flag_bars <= flag_bars <= max_flag_bars):
        return not_found

    flag_close = arr_c[flag_start: flag_end + 1]
    flag_high  = arr_h[flag_start: flag_end + 1]
    flag_low   = arr_l[flag_start: flag_end + 1]
    flag_vol   = arr_v[flag_start: flag_end + 1]

    pole_low   = float(arr_l[best_pole_start: best_pole_end + 1].min())
    pole_high  = float(arr_h[best_pole_end])
    pole_height = pole_high - pole_low

    flag_top    = float(flag_high.max())
    flag_bottom = float(flag_low.min())

    # Flag must stay within a reasonable band (not retrace more than 50% of pole)
    max_retrace = pole_height * (max_flag_retrace_pct / 100)
    actual_retrace = pole_high - float(flag_close[-1])
    if actual_retrace > max_retrace:
        return not_found

    # Flag width (range) should be tighter than pole
    flag_range_pct = (flag_top - flag_bottom) / pole_high * 100
    if flag_range_pct > 15.0:
        return not_found

    # --- Step 3: Volume should contract during the flag ---
    pole_vol_avg = float(arr_v[best_pole_start: best_pole_end + 1].mean()) if best_pole_end > best_pole_start else 1.0
    flag_vol_avg = float(flag_vol.mean()) if len(flag_vol) > 0 else pole_vol_avg
    vol_contraction = pole_vol_avg > 0 and (flag_vol_avg / pole_vol_avg) < 0.85

    # --- Step 4: Price near pivot (top of flag) = ready to break ---
    pivot = flag_top
    dist_from_pivot = (pivot - current_price) / pivot * 100
    near_pivot = dist_from_pivot <= 5.0

    # --- Step 5: Strength score ---
    strength = 0.40

    # Pole gain
    if best_pole_pct >= 30:
        strength += 0.20
    elif best_pole_pct >= 20:
        strength += 0.12
    else:
        strength += 0.06

    # Tight flag
    if flag_range_pct <= 6:
        strength += 0.15
    elif flag_range_pct <= 10:
        strength += 0.08

    # Volume contraction
    if vol_contraction:
        strength += 0.12

    # Flag bar count (3-6 ideal)
    if 3 <= flag_bars <= 6:
        strength += 0.08

    # Near pivot
    if near_pivot:
        strength += 0.10

    # Price must still be above pole_low (no total breakdown)
    if current_price < pole_low:
        return not_found

    strength = clamp(strength)

    if strength < 0.45:
        return not_found

    target = round(pivot + pole_height, 2)
    stop   = round(flag_bottom * 0.998, 2)  # just below flag low

    return PatternResult(
        name="bull_flag",
        detected=True,
        strength=round(strength, 3),
        pivot=round(pivot, 2),
        pattern_stop=stop,
        pattern_target=target,
        bars_forming=flag_bars + (best_pole_end - best_pole_start + 1),
        details=(
            f"Pole +{best_pole_pct:.0f}% in {best_pole_end - best_pole_start + 1} bars, "
            f"flag {flag_bars} bars {(float(flag_close[-1]) - pole_high) / pole_high * 100:+.1f}%, "
            f"vol {'contracted' if vol_contraction else 'flat'}, pivot=${pivot:.2f}"
        ),
    )

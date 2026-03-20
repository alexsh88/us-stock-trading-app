"""
Cup and Handle pattern detection (William O'Neil).

Requires daily data spanning ≥ 4 months (≥85 bars).
Optionally enhanced with weekly data.

Cup:    U-shaped base 6–26 weeks deep; depth 12–35% from left lip.
        Left lip and right lip within 5% of each other.
Handle: 5–15% pullback from right lip over 1–4 weeks.
Pivot:  Handle high (the precise buy point).
Stop:   7–8% below pivot (O'Neil's standard rule).
Target: Pivot + cup depth.
"""
import pandas as pd
import numpy as np
from app.agents.patterns.base import PatternResult, clamp


def _is_u_shaped(close_segment: pd.Series) -> bool:
    """
    Check if a price series is roughly U-shaped (rounded bottom).
    Method: the midpoint of the segment should be near the low,
    and both ends should be higher than the middle.
    """
    n = len(close_segment)
    if n < 10:
        return False
    arr = close_segment.values
    mid_start = n // 3
    mid_end   = 2 * n // 3
    mid_avg   = float(arr[mid_start:mid_end].mean())
    left_avg  = float(arr[:mid_start].mean())
    right_avg = float(arr[mid_end:].mean())
    return left_avg > mid_avg * 1.03 and right_avg > mid_avg * 1.03


def detect_cup_handle(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    min_bars: int = 85,               # ~4 months of daily bars
    min_cup_weeks: int = 6,
    max_cup_depth_pct: float = 35.0,
    min_cup_depth_pct: float = 10.0,
    lip_tolerance_pct: float = 5.0,
    max_handle_pullback_pct: float = 15.0,
) -> PatternResult:
    not_found = PatternResult(name="cup_handle", detected=False, strength=0.0)

    n = len(close)
    if n < min_bars:
        return not_found

    arr_c = close.values
    arr_h = high.values
    arr_l = low.values
    arr_v = volume.values
    current_price = float(arr_c[-1])

    # Scan for left lip in the last 6 months of daily bars (~130 bars)
    scan_start = max(0, n - 130)

    for left_lip_idx in range(scan_start, n - min_cup_weeks * 5):
        left_lip_price = float(arr_h[left_lip_idx])

        # Cup bottom: lowest close after left lip, within 6–26 weeks ahead
        cup_search_end = min(left_lip_idx + 130, n - 10)
        cup_body = close.iloc[left_lip_idx: cup_search_end]
        if len(cup_body) < 30:
            continue

        cup_bottom_idx_local = int(cup_body.values.argmin())
        cup_bottom_price = float(cup_body.values[cup_bottom_idx_local])
        cup_bottom_idx = left_lip_idx + cup_bottom_idx_local

        cup_depth_pct = (left_lip_price - cup_bottom_price) / left_lip_price * 100
        if not (min_cup_depth_pct <= cup_depth_pct <= max_cup_depth_pct):
            continue

        # Right lip: price recovers to within lip_tolerance_pct of left lip
        # Search in bars after the cup bottom
        right_section = close.iloc[cup_bottom_idx + 5:]
        if len(right_section) < 10:
            continue

        recovery = (right_section - left_lip_price * (1 - lip_tolerance_pct / 100))
        recovery_bars = recovery[recovery >= 0]
        if recovery_bars.empty:
            continue

        right_lip_local_idx = int(recovery.index.get_loc(recovery_bars.index[0]))
        right_lip_idx = cup_bottom_idx + 5 + right_lip_local_idx
        if right_lip_idx >= n - 3:
            continue

        right_lip_price = float(arr_h[right_lip_idx])

        # Right lip within tolerance of left lip
        lip_diff_pct = abs(right_lip_price - left_lip_price) / left_lip_price * 100
        if lip_diff_pct > lip_tolerance_pct:
            continue

        # Check U-shape
        cup_segment = close.iloc[left_lip_idx: right_lip_idx + 1]
        if not _is_u_shaped(cup_segment):
            continue

        # Handle: pullback from right lip over remaining bars
        handle_section = close.iloc[right_lip_idx:]
        if len(handle_section) < 3:
            continue

        handle_low = float(handle_section.min())
        handle_pullback_pct = (right_lip_price - handle_low) / right_lip_price * 100
        if handle_pullback_pct > max_handle_pullback_pct:
            continue
        if handle_pullback_pct < 3.0:
            continue  # no meaningful handle

        # Handle high = pivot (the buy point)
        pivot = float(handle_section.max())
        dist_from_pivot = (pivot - current_price) / pivot * 100
        if dist_from_pivot > 5.0:
            continue  # price drifted away

        # Volume: right side of cup should be heavier (accumulation) than left side
        cup_mid = (left_lip_idx + right_lip_idx) // 2
        left_cup_vol  = float(volume.iloc[left_lip_idx: cup_mid].mean()) if cup_mid > left_lip_idx else 1
        right_cup_vol = float(volume.iloc[cup_mid: right_lip_idx + 1].mean()) if right_lip_idx > cup_mid else 1
        vol_confirmation = right_cup_vol >= left_cup_vol * 0.9

        # Handle volume should contract
        handle_vol_avg  = float(volume.iloc[right_lip_idx:].mean()) if right_lip_idx < n else 1
        cup_vol_avg     = float(volume.iloc[left_lip_idx: right_lip_idx].mean()) if right_lip_idx > left_lip_idx else 1
        handle_vol_contracted = handle_vol_avg < cup_vol_avg * 0.85

        # Strength scoring
        cup_bars = right_lip_idx - left_lip_idx
        strength = 0.35

        # Cup depth (sweet spot 12-30%)
        if 12 <= cup_depth_pct <= 30:
            strength += 0.15
        elif cup_depth_pct < 12:
            strength += 0.08

        # Cup duration (6-20 weeks = 30-100 bars is ideal)
        if 30 <= cup_bars <= 100:
            strength += 0.10
        elif cup_bars > 100:
            strength += 0.05

        # Tight handle
        if handle_pullback_pct <= 10:
            strength += 0.12
        elif handle_pullback_pct <= 15:
            strength += 0.06

        # Symmetric lips
        if lip_diff_pct <= 2:
            strength += 0.10
        elif lip_diff_pct <= 3.5:
            strength += 0.06

        if vol_confirmation:
            strength += 0.08
        if handle_vol_contracted:
            strength += 0.07

        if dist_from_pivot <= 2.0:
            strength += 0.08

        strength = clamp(strength)
        if strength < 0.45:
            continue

        cup_depth = left_lip_price - cup_bottom_price
        # O'Neil: 7.5% below pivot — but cap at ATR-2x so high-priced low-volatility
        # stocks don't get a $40 stop when their daily range is only $3.
        try:
            prev_c = close.shift(1)
            tr_s = pd.concat([high - low, (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
            atr14 = float(tr_s.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
            atr_stop = round(current_price - atr14 * 2.0, 2)
        except Exception:
            atr_stop = None
        oneil_stop = round(pivot * 0.925, 2)
        stop = max(oneil_stop, atr_stop) if atr_stop else oneil_stop  # tighter of the two
        target = round(pivot + cup_depth, 2)

        return PatternResult(
            name="cup_handle",
            detected=True,
            strength=round(strength, 3),
            pivot=round(pivot, 2),
            pattern_stop=stop,
            pattern_target=target,
            bars_forming=cup_bars,
            details=(
                f"Cup {cup_bars} bars, depth {cup_depth_pct:.0f}%, "
                f"handle pullback {handle_pullback_pct:.1f}%, "
                f"pivot=${pivot:.2f}, target=${target:.2f}"
            ),
        )

    return not_found

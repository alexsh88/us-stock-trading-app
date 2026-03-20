"""
Ascending Triangle (bullish) and Descending Triangle (bearish) detection.

Ascending Triangle:
  - Flat resistance ceiling (2+ swing highs within 1.5%)
  - Rising support trendline (positive slope through swing lows)
  - Lines converge; price is inside the triangle
  - Pivot: resistance level (breakout point)
  - Stop:  most recent swing low on the support line
  - Target: resistance + triangle height

Descending Triangle:
  - Flat support floor (bearish mirror)
  - Used for short-side signals
"""
import pandas as pd
from app.agents.patterns.base import (
    PatternResult, find_swing_highs, find_swing_lows, linear_slope, clamp
)


def detect_ascending_triangle(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    lookback: int = 252,
    resistance_tolerance_pct: float = 1.5,
) -> PatternResult:
    not_found = PatternResult(name="ascending_triangle", detected=False, strength=0.0)

    n = len(close)
    if n < 25:
        return not_found

    # Work on the recent lookback window
    start = max(0, n - lookback)
    c = close.iloc[start:]
    h = high.iloc[start:]
    l = low.iloc[start:]
    v = volume.iloc[start:]

    current_price = float(c.iloc[-1])

    # --- Swing highs / lows using n=3 pivot (more sensitive in triangle) ---
    sh = find_swing_highs(h, n=3)
    sl = find_swing_lows(l, n=3)

    if len(sh) < 2 or len(sl) < 2:
        return not_found

    # --- Flat resistance: 2+ swing highs within tolerance of each other ---
    sh_prices = [p for _, p in sh]
    avg_high = sum(sh_prices) / len(sh_prices)

    resistance_touches = [p for p in sh_prices if abs(p - avg_high) / avg_high * 100 <= resistance_tolerance_pct]

    if len(resistance_touches) < 2:
        return not_found

    resistance = round(sum(resistance_touches) / len(resistance_touches), 2)

    # Resistance slope must be near-flat
    res_slope = linear_slope(resistance_touches)
    if abs(res_slope) > resistance * 0.005:  # flat = <0.5% slope per bar equivalent
        return not_found

    # --- Rising support: swing lows must have positive slope ---
    sl_prices = [p for _, p in sl]
    if len(sl_prices) < 2:
        return not_found

    sup_slope = linear_slope(sl_prices)
    if sup_slope <= 0:
        return not_found  # support must be rising

    # --- Triangle height (distance from first support touch to resistance) ---
    first_support = sl_prices[0]
    triangle_height = resistance - first_support
    if triangle_height <= 0:
        return not_found

    # --- Price must be inside the triangle (below resistance, above extrapolated support) ---
    if current_price >= resistance * 1.03:
        return not_found  # already broken out (late entry — skip clean detection)

    # Most recent swing low = stop anchor
    recent_support = sl_prices[-1]

    # --- Check convergence: support line should be approaching resistance ---
    # Estimate bars until they would meet
    if sup_slope > 0:
        bars_to_convergence = (resistance - recent_support) / sup_slope
        # Ideal: convergence in 5-25 bars
        good_convergence = 3 <= bars_to_convergence <= 30
    else:
        good_convergence = False

    # --- Near breakout: price within 3% of resistance ---
    near_breakout = (resistance - current_price) / resistance * 100 <= 3.0

    # --- Volume declining inside triangle (typical) ---
    if len(v) >= 10:
        vol_first_half = float(v.iloc[:len(v)//2].mean())
        vol_second_half = float(v.iloc[len(v)//2:].mean())
        vol_declining = vol_second_half < vol_first_half * 0.9
    else:
        vol_declining = False

    # --- Strength ---
    strength = 0.35

    if len(resistance_touches) >= 3:
        strength += 0.15
    elif len(resistance_touches) == 2:
        strength += 0.08

    if len(sl_prices) >= 3:
        strength += 0.10
    elif len(sl_prices) == 2:
        strength += 0.05

    if good_convergence:
        strength += 0.12

    if near_breakout:
        strength += 0.12

    if vol_declining:
        strength += 0.08

    strength = clamp(strength)

    if strength < 0.42:
        return not_found

    pivot  = round(resistance, 2)
    stop   = round(recent_support * 0.995, 2)
    target = round(resistance + triangle_height, 2)

    return PatternResult(
        name="ascending_triangle",
        detected=True,
        strength=round(strength, 3),
        pivot=pivot,
        pattern_stop=stop,
        pattern_target=target,
        bars_forming=len(c),
        details=(
            f"Resistance=${resistance:.2f} ({len(resistance_touches)} touches), "
            f"rising support slope={sup_slope:.3f}, "
            f"price {(resistance - current_price) / resistance * 100:.1f}% from breakout"
        ),
    )


def detect_descending_triangle(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    lookback: int = 252,
    support_tolerance_pct: float = 1.5,
) -> PatternResult:
    """Descending triangle — bearish, used for short signals."""
    not_found = PatternResult(name="descending_triangle", detected=False, strength=0.0)

    n = len(close)
    if n < 25:
        return not_found

    start = max(0, n - lookback)
    c = close.iloc[start:]
    h = high.iloc[start:]
    l = low.iloc[start:]

    current_price = float(c.iloc[-1])

    sh = find_swing_highs(h, n=3)
    sl = find_swing_lows(l, n=3)

    if len(sh) < 2 or len(sl) < 2:
        return not_found

    sl_prices = [p for _, p in sl]
    avg_low = sum(sl_prices) / len(sl_prices)
    support_touches = [p for p in sl_prices if abs(p - avg_low) / avg_low * 100 <= support_tolerance_pct]

    if len(support_touches) < 2:
        return not_found

    support = round(sum(support_touches) / len(support_touches), 2)

    sup_slope = linear_slope(support_touches)
    if abs(sup_slope) > support * 0.005:
        return not_found  # must be flat

    sh_prices = [p for _, p in sh]
    res_slope = linear_slope(sh_prices)
    if res_slope >= 0:
        return not_found  # resistance must be falling

    triangle_height = sh_prices[0] - support
    if triangle_height <= 0:
        return not_found

    if current_price <= support * 0.97:
        return not_found  # already broken down

    near_breakdown = (current_price - support) / support * 100 <= 3.0

    strength = 0.35
    if len(support_touches) >= 3:
        strength += 0.15
    if len(sh_prices) >= 3:
        strength += 0.10
    if near_breakdown:
        strength += 0.15
    strength = clamp(strength)

    if strength < 0.42:
        return not_found

    pivot  = round(support, 2)                       # breakdown level
    stop   = round(sh_prices[-1] * 1.005, 2)         # stop above recent swing high
    target = round(support - triangle_height, 2)     # measured move

    return PatternResult(
        name="descending_triangle",
        detected=True,
        strength=round(strength, 3),
        pivot=pivot,
        pattern_stop=stop,
        pattern_target=target,
        bars_forming=len(c),
        details=(
            f"Support=${support:.2f} ({len(support_touches)} touches), "
            f"falling resistance slope={res_slope:.3f}"
        ),
    )

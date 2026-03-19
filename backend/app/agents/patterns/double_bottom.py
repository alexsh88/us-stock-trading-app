"""
Double Bottom (and Double Top) pattern detection.

Double Bottom: Two lows within 3% of each other, separated by ≥10 bars,
               with a neckline (high between them). Bullish reversal.
Double Top:    Two highs within 3% of each other. Bearish reversal.
               (Included for completeness; used in short-side scoring.)

Stop:   Just below the second bottom (0.5%).
Target: Neckline + (neckline - bottom) — classic pattern projection.
Pivot:  Neckline level (buy on the neckline break).
"""
import pandas as pd
from app.agents.patterns.base import PatternResult, find_swing_lows, find_swing_highs, clamp


def detect_double_bottom(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    tolerance_pct: float = 3.0,
    min_separation: int = 10,
) -> PatternResult:
    not_found = PatternResult(name="double_bottom", detected=False, strength=0.0)

    if len(close) < 30:
        return not_found

    current_price = float(close.iloc[-1])

    # Find swing lows with n=3 (sensitive pivot to catch more patterns)
    swing_lows = find_swing_lows(low, n=3)
    if len(swing_lows) < 2:
        return not_found

    arr_h = high.values

    best: dict = {}

    # Compare all pairs of swing lows
    for i in range(len(swing_lows) - 1):
        for j in range(i + 1, len(swing_lows)):
            idx1, price1 = swing_lows[i]
            idx2, price2 = swing_lows[j]

            if idx2 - idx1 < min_separation:
                continue

            # Both lows must be within tolerance of each other
            avg_low = (price1 + price2) / 2
            if avg_low <= 0:
                continue
            diff_pct = abs(price1 - price2) / avg_low * 100
            if diff_pct > tolerance_pct:
                continue

            # Neckline = highest close between the two lows
            neckline = float(arr_h[idx1: idx2 + 1].max())
            if neckline <= avg_low:
                continue

            # Pattern height
            height = neckline - avg_low

            # Current price should be near or above neckline
            if current_price < avg_low:
                continue

            near_neckline = current_price >= neckline * 0.97  # within 3% below or at/above

            # Volume: second bottom ideally on lower volume than first
            v1 = float(volume.iloc[idx1]) if idx1 < len(volume) else 0
            v2 = float(volume.iloc[idx2]) if idx2 < len(volume) else 0
            vol_confirmation = v2 < v1 * 1.1  # second bottom ≤ first bottom volume

            # Strength scoring
            strength = 0.35
            if diff_pct <= 1.5:
                strength += 0.20  # very symmetric
            elif diff_pct <= 2.5:
                strength += 0.12
            else:
                strength += 0.05

            depth_pct = height / avg_low * 100
            if 8 <= depth_pct <= 25:
                strength += 0.12  # meaningful but not extreme depth
            elif depth_pct > 25:
                strength += 0.05

            if vol_confirmation:
                strength += 0.10

            if near_neckline:
                strength += 0.15  # near the actionable buy point
            elif current_price > neckline:
                strength += 0.08  # already confirmed breakout

            separation_score = min((idx2 - idx1) / 30, 1.0) * 0.08
            strength += separation_score

            strength = clamp(strength)

            # Track the best (most recent + strongest) pair
            recency_score = idx2 + strength
            if not best or recency_score > best.get("score", 0):
                best = {
                    "score": recency_score,
                    "strength": strength,
                    "idx1": idx1, "price1": price1,
                    "idx2": idx2, "price2": price2,
                    "neckline": neckline,
                    "height": height,
                    "near_neckline": near_neckline,
                }

    if not best or best["strength"] < 0.40:
        return not_found

    bottom_price = min(best["price1"], best["price2"])
    pivot  = round(best["neckline"], 2)
    stop   = round(bottom_price * 0.995, 2)
    target = round(pivot + best["height"], 2)

    return PatternResult(
        name="double_bottom",
        detected=True,
        strength=round(best["strength"], 3),
        pivot=pivot,
        pattern_stop=stop,
        pattern_target=target,
        bars_forming=best["idx2"] - best["idx1"],
        details=(
            f"Bottoms at ${best['price1']:.2f} and ${best['price2']:.2f} "
            f"({abs(best['price1'] - best['price2']) / ((best['price1'] + best['price2']) / 2) * 100:.1f}% apart), "
            f"neckline=${pivot:.2f}, target=${target:.2f}"
        ),
    )


def detect_double_top(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    tolerance_pct: float = 3.0,
    min_separation: int = 10,
) -> PatternResult:
    """Double top — bearish reversal. Used for short-side signals."""
    not_found = PatternResult(name="double_top", detected=False, strength=0.0)

    if len(close) < 30:
        return not_found

    current_price = float(close.iloc[-1])
    swing_highs = find_swing_highs(high, n=3)
    if len(swing_highs) < 2:
        return not_found

    arr_l = low.values
    best: dict = {}

    for i in range(len(swing_highs) - 1):
        for j in range(i + 1, len(swing_highs)):
            idx1, price1 = swing_highs[i]
            idx2, price2 = swing_highs[j]

            if idx2 - idx1 < min_separation:
                continue

            avg_top = (price1 + price2) / 2
            if avg_top <= 0:
                continue
            diff_pct = abs(price1 - price2) / avg_top * 100
            if diff_pct > tolerance_pct:
                continue

            neckline = float(arr_l[idx1: idx2 + 1].min())
            if neckline >= avg_top:
                continue

            height = avg_top - neckline
            near_neckline = current_price <= neckline * 1.03

            strength = 0.35
            if diff_pct <= 1.5:
                strength += 0.20
            elif diff_pct <= 2.5:
                strength += 0.12
            else:
                strength += 0.05

            depth_pct = height / avg_top * 100
            if 5 <= depth_pct <= 20:
                strength += 0.12

            if near_neckline:
                strength += 0.15
            elif current_price < neckline:
                strength += 0.08

            strength = clamp(strength)

            recency_score = idx2 + strength
            if not best or recency_score > best.get("score", 0):
                best = {
                    "score": recency_score,
                    "strength": strength,
                    "price1": price1, "price2": price2,
                    "idx1": idx1, "idx2": idx2,
                    "neckline": neckline, "height": height,
                }

    if not best or best["strength"] < 0.40:
        return not_found

    top_price = max(best["price1"], best["price2"])
    pivot  = round(best["neckline"], 2)           # breakdown level
    stop   = round(top_price * 1.005, 2)          # stop above the tops (for shorts)
    target = round(pivot - best["height"], 2)     # short target

    return PatternResult(
        name="double_top",
        detected=True,
        strength=round(best["strength"], 3),
        pivot=pivot,
        pattern_stop=stop,
        pattern_target=target,
        bars_forming=best["idx2"] - best["idx1"],
        details=(
            f"Tops at ${best['price1']:.2f} and ${best['price2']:.2f}, "
            f"neckline=${pivot:.2f}, short target=${target:.2f}"
        ),
    )

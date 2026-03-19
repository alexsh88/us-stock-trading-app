"""
Head and Shoulders (bearish) and Inverse Head and Shoulders (bullish) detection.

Inverse H&S (bullish):
  Three swing lows: left shoulder, head (deepest), right shoulder.
  Head ≥ 5% below both shoulders. Shoulders within 5% of each other.
  Neckline connects the swing highs between shoulder-head and head-shoulder.
  Pivot: neckline level (buy on the break above neckline).
  Stop:  below right shoulder low.
  Target: neckline + (neckline − head).

Head and Shoulders (bearish — for short signals):
  Three swing highs with middle highest. Pivot: neckline breakdown.
"""
import pandas as pd
from app.agents.patterns.base import (
    PatternResult, find_swing_highs, find_swing_lows, clamp
)


def detect_inverse_head_shoulders(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    shoulder_tolerance_pct: float = 6.0,
    head_min_deeper_pct: float = 4.0,
) -> PatternResult:
    not_found = PatternResult(name="inverse_head_shoulders", detected=False, strength=0.0)

    n = len(close)
    if n < 40:
        return not_found

    current_price = float(close.iloc[-1])
    arr_h = high.values

    swing_lows  = find_swing_lows(low, n=4)
    swing_highs = find_swing_highs(high, n=3)

    if len(swing_lows) < 3:
        return not_found

    best: dict = {}

    # Try all combinations of 3 consecutive swing lows as (LS, Head, RS)
    for i in range(len(swing_lows) - 2):
        ls_idx, ls_price  = swing_lows[i]
        hd_idx, hd_price  = swing_lows[i + 1]
        rs_idx, rs_price  = swing_lows[i + 2]

        # Head must be the lowest
        if not (hd_price < ls_price and hd_price < rs_price):
            continue

        # Head must be deeper than both shoulders by min threshold
        head_depth_vs_ls = (ls_price - hd_price) / ls_price * 100
        head_depth_vs_rs = (rs_price - hd_price) / rs_price * 100
        if head_depth_vs_ls < head_min_deeper_pct or head_depth_vs_rs < head_min_deeper_pct:
            continue

        # Shoulders within tolerance of each other
        avg_shoulder = (ls_price + rs_price) / 2
        shoulder_diff_pct = abs(ls_price - rs_price) / avg_shoulder * 100
        if shoulder_diff_pct > shoulder_tolerance_pct:
            continue

        # Minimum separation between lows
        if hd_idx - ls_idx < 5 or rs_idx - hd_idx < 5:
            continue

        # Neckline: highest price between LS-head and head-RS
        neckline_left  = float(arr_h[ls_idx: hd_idx + 1].max())
        neckline_right = float(arr_h[hd_idx: rs_idx + 1].max())
        neckline = round((neckline_left + neckline_right) / 2, 2)

        pattern_height = neckline - hd_price
        if pattern_height <= 0:
            continue

        # Current price: should be near or above neckline
        near_neckline = current_price >= neckline * 0.97
        confirmed = current_price > neckline

        # Volume: right shoulder ideally on lower volume (less selling pressure)
        v_ls = float(volume.iloc[ls_idx]) if ls_idx < len(volume) else 0
        v_rs = float(volume.iloc[rs_idx]) if rs_idx < len(volume) else 0
        vol_confirmation = v_rs < v_ls * 1.1

        strength = 0.35

        if shoulder_diff_pct <= 3:
            strength += 0.15
        elif shoulder_diff_pct <= 5:
            strength += 0.08

        if head_depth_vs_ls >= 8 and head_depth_vs_rs >= 8:
            strength += 0.10
        elif head_depth_vs_ls >= 5 and head_depth_vs_rs >= 5:
            strength += 0.06

        if near_neckline or confirmed:
            strength += 0.15

        if vol_confirmation:
            strength += 0.08

        # Recency
        recency = rs_idx / n
        strength += recency * 0.10

        strength = clamp(strength)

        recency_score = rs_idx + strength
        if not best or recency_score > best.get("score", 0):
            best = {
                "score": recency_score,
                "strength": strength,
                "ls_price": ls_price, "hd_price": hd_price, "rs_price": rs_price,
                "rs_idx": rs_idx,
                "neckline": neckline,
                "height": pattern_height,
            }

    if not best or best["strength"] < 0.42:
        return not_found

    neckline = best["neckline"]
    stop   = round(best["rs_price"] * 0.993, 2)
    target = round(neckline + best["height"], 2)

    return PatternResult(
        name="inverse_head_shoulders",
        detected=True,
        strength=round(best["strength"], 3),
        pivot=neckline,
        pattern_stop=stop,
        pattern_target=target,
        bars_forming=best["rs_idx"],
        details=(
            f"LS=${best['ls_price']:.2f}, Head=${best['hd_price']:.2f} "
            f"({(best['ls_price'] - best['hd_price']) / best['ls_price'] * 100:.0f}% deeper), "
            f"RS=${best['rs_price']:.2f}, neckline=${neckline:.2f}"
        ),
    )


def detect_head_shoulders(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    shoulder_tolerance_pct: float = 6.0,
    head_min_higher_pct: float = 4.0,
) -> PatternResult:
    """Standard H&S (bearish topping pattern) — used for short signals."""
    not_found = PatternResult(name="head_shoulders", detected=False, strength=0.0)

    n = len(close)
    if n < 40:
        return not_found

    current_price = float(close.iloc[-1])
    arr_l = low.values

    swing_highs = find_swing_highs(high, n=4)
    if len(swing_highs) < 3:
        return not_found

    best: dict = {}

    for i in range(len(swing_highs) - 2):
        ls_idx, ls_price = swing_highs[i]
        hd_idx, hd_price = swing_highs[i + 1]
        rs_idx, rs_price = swing_highs[i + 2]

        if not (hd_price > ls_price and hd_price > rs_price):
            continue

        if (hd_price - ls_price) / ls_price * 100 < head_min_higher_pct:
            continue
        if (hd_price - rs_price) / rs_price * 100 < head_min_higher_pct:
            continue

        avg_shoulder = (ls_price + rs_price) / 2
        if abs(ls_price - rs_price) / avg_shoulder * 100 > shoulder_tolerance_pct:
            continue

        if hd_idx - ls_idx < 5 or rs_idx - hd_idx < 5:
            continue

        neckline_left  = float(arr_l[ls_idx: hd_idx + 1].min())
        neckline_right = float(arr_l[hd_idx: rs_idx + 1].min())
        neckline = round((neckline_left + neckline_right) / 2, 2)

        pattern_height = hd_price - neckline
        if pattern_height <= 0:
            continue

        near_breakdown = current_price <= neckline * 1.03

        strength = 0.35
        if abs(ls_price - rs_price) / avg_shoulder * 100 <= 3:
            strength += 0.15
        if near_breakdown or current_price < neckline:
            strength += 0.15
        strength += (rs_idx / n) * 0.10
        strength = clamp(strength)

        recency_score = rs_idx + strength
        if not best or recency_score > best.get("score", 0):
            best = {
                "score": recency_score,
                "strength": strength,
                "hd_price": hd_price, "rs_price": rs_price,
                "neckline": neckline, "height": pattern_height,
                "rs_idx": rs_idx,
            }

    if not best or best["strength"] < 0.42:
        return not_found

    neckline = best["neckline"]
    stop   = round(best["hd_price"] * 1.005, 2)   # stop above the head (for shorts)
    target = round(neckline - best["height"], 2)   # downside projection

    return PatternResult(
        name="head_shoulders",
        detected=True,
        strength=round(best["strength"], 3),
        pivot=neckline,
        pattern_stop=stop,
        pattern_target=target,
        bars_forming=best["rs_idx"],
        details=(
            f"Head=${best['hd_price']:.2f}, RS=${best['rs_price']:.2f}, "
            f"neckline=${neckline:.2f}, short target=${target:.2f}"
        ),
    )

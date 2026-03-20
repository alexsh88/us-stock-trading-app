"""
VCP — Volatility Contraction Pattern (Mark Minervini).

Structure: 2–4 successive price contractions where each phase has a smaller
           % range AND lower volume than the prior phase.
           Final contraction ideally < 8% range.

Pivot:  High of the final (tightest) contraction.
Stop:   Low of the final contraction.
Target: No fixed projection — use swing resistance or ATR-based target.
        Pattern itself provides entry/stop precision, not a target.
"""
import pandas as pd
from app.agents.patterns.base import PatternResult, clamp


def _measure_contraction(
    high_arr, low_arr, vol_arr, start: int, end: int
) -> dict:
    """Measure price range % and average volume for a segment."""
    seg_h = high_arr[start: end + 1]
    seg_l = low_arr[start: end + 1]
    seg_v = vol_arr[start: end + 1]
    seg_high = float(seg_h.max())
    seg_low  = float(seg_l.min())
    if seg_low <= 0:
        return {"range_pct": 999.0, "vol_avg": 0.0}
    return {
        "range_pct": (seg_high - seg_low) / seg_low * 100,
        "vol_avg":   float(seg_v.mean()) if len(seg_v) > 0 else 0.0,
        "high": seg_high,
        "low":  seg_low,
    }


def detect_vcp(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    min_contractions: int = 2,
    max_contractions: int = 4,
    contraction_ratio: float = 0.65,   # each phase ≤ 65% of prior phase range
    max_final_range_pct: float = 10.0, # final contraction must be tight
) -> PatternResult:
    not_found = PatternResult(name="vcp", detected=False, strength=0.0)

    n = len(close)
    if n < 30:
        return not_found

    arr_c = close.values
    arr_h = high.values
    arr_l = low.values
    arr_v = volume.values
    current_price = float(arr_c[-1])

    # Try segment sizes from 8 to 15 bars per contraction phase
    for seg_len in range(8, 16):
        phases = []
        for k in range(max_contractions):
            end_idx   = n - 1 - k * seg_len
            start_idx = end_idx - seg_len + 1
            if start_idx < 0:
                break
            m = _measure_contraction(arr_h, arr_l, arr_v, start_idx, end_idx)
            phases.append(m)

        # phases are ordered most-recent first; reverse to check contraction
        phases = phases[::-1]  # oldest → newest

        if len(phases) < min_contractions:
            continue

        # Check each successive phase contracts
        valid = True
        contraction_count = 0
        for i in range(1, len(phases)):
            prev_range = phases[i - 1]["range_pct"]
            curr_range = phases[i]["range_pct"]
            prev_vol   = phases[i - 1]["vol_avg"]
            curr_vol   = phases[i]["vol_avg"]
            if curr_range < prev_range * contraction_ratio:
                contraction_count += 1
            else:
                valid = False
                break
            # Volume should also contract
            if curr_vol >= prev_vol * 1.1:
                valid = False
                break

        if not valid or contraction_count < min_contractions - 1:
            continue

        # Final phase must be tight
        final_phase = phases[-1]
        if final_phase["range_pct"] > max_final_range_pct:
            continue

        # Current price should be near the pivot (final phase high)
        pivot = final_phase["high"]
        dist_from_pivot = (pivot - current_price) / pivot * 100
        if dist_from_pivot > 5.0:
            continue  # price moved away from setup

        # Strength scoring
        strength = 0.40

        if contraction_count >= 3:
            strength += 0.20
        elif contraction_count == 2:
            strength += 0.10

        if final_phase["range_pct"] <= 5.0:
            strength += 0.15
        elif final_phase["range_pct"] <= 7.0:
            strength += 0.08

        if dist_from_pivot <= 2.0:
            strength += 0.12
        elif dist_from_pivot <= 4.0:
            strength += 0.06

        strength = clamp(strength)

        if strength < 0.45:
            continue

        pivot_price = round(pivot, 2)
        stop_price  = round(final_phase["low"] * 0.997, 2)
        # Measured-move target: pivot + (pivot − final_phase_low)
        # This is the natural "spring" distance projected upward from the breakout.
        target_price = round(pivot_price + (pivot_price - final_phase["low"]), 2)

        return PatternResult(
            name="vcp",
            detected=True,
            strength=round(strength, 3),
            pivot=pivot_price,
            pattern_stop=stop_price,
            pattern_target=target_price,
            bars_forming=len(phases) * seg_len,
            details=(
                f"{contraction_count + 1} contractions, final range {final_phase['range_pct']:.1f}%, "
                f"pivot=${pivot_price:.2f}, price {dist_from_pivot:.1f}% below pivot"
            ),
        )

    return not_found

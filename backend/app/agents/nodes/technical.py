import re
import structlog
import yfinance as yf
import pandas as pd
from typing import Any

logger = structlog.get_logger()

TECHNICAL_SYSTEM = """You are a technical analysis expert. Score each stock 0.0-1.0 for bullish setup quality.
Consider the regime: in TRENDING markets (ADX>25), reward momentum; in CHOPPY markets (ADX<20), reward mean-reversion.
MTF_ALIGNED=yes means weekly trend agrees with daily — prefer these setups.
BB_Squeeze=yes means volatility is compressed and a breakout is imminent — bullish if combined with momentum.
NR7=yes means today's range is the smallest of the last 7 days (Crabel) — strongest when combined with BB_Squeeze (dual volatility compression). Enter on next-session breakout above NR7 high.
Breakout score 3/3 = high-conviction breakout (level + volume + RSI all confirmed).
Short%Float: >25% = crowded short (both squeeze risk AND strong bearish consensus — be cautious). DTC>10 = illiquid short squeeze scenario.
EMA150_pct: distance above/below 150-day EMA (Weinstein Stage 2). +5 to +15% = healthy uptrend. Above +25% = overextended, higher pullback risk. Negative = Stage 3/4 downtrend, avoid longs.
Streak: consecutive up(+) or down(-) days. In CHOPPY regime, Streak>=+5 combined with RSI>65 or price near resistance = high mean-reversion risk, penalise. In TRENDING regime (ADX>25), a long up streak is momentum confirmation, NOT a sell signal on its own.
Pattern: named chart pattern detected (e.g. BullFlag, CupHandle, InvH&S, VCP, DblBottom, AscTriangle). Strength 0-1. A strong pattern (≥0.70) with a defined pivot is a high-conviction entry signal — reward with +0.10 to +0.15 score bonus. No pattern = neutral.
Respond with one line per stock: TICKER|SCORE|REASONING (max 100 chars reasoning).

Examples (use the full 0.0-1.0 range):
NVDA|0.88|Trending ADX=34, MTF aligned, BB squeeze released, breakout 3/3, RSI=66, EMA150=+11% healthy
XOM|0.29|Choppy ADX=15, MTF misaligned (weekly downtrend), no squeeze, breakout 0/3
MSFT|0.63|Neutral ADX=22, MTF aligned, squeeze building 4 bars, breakout 1/3, EMA150=+8%
APA|0.44|Trending but Streak=+7d, EMA150=+29% overextended, RSI=74 overbought — wait for pullback
GME|0.19|Choppy ADX=12, MTF misaligned, vol declining, breakout 0/3, avoid
AAPL|0.82|Trending ADX=31, MTF aligned, CupHandle(str=0.78,pivot=$185.50) near pivot, breakout 2/3"""


def _calc_streak(close: pd.Series) -> int:
    """Count consecutive up or down closes from the most recent bar.
    Returns positive int for an up streak, negative for a down streak, 0 if flat.
    Example: 5 consecutive higher closes → +5; 3 consecutive lower closes → -3.
    """
    changes = close.diff().dropna()
    if changes.empty:
        return 0
    recent = list(reversed(changes.values[-15:]))  # most recent first
    streak = 0
    for i, chg in enumerate(recent):
        if i == 0:
            if chg > 0:
                streak = 1
            elif chg < 0:
                streak = -1
            else:
                break
        else:
            if streak > 0 and chg > 0:
                streak += 1
            elif streak < 0 and chg < 0:
                streak -= 1
            else:
                break
    return streak


def _calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> tuple[float, str]:
    """Calculate ADX. Returns (adx_value, regime: 'trending'|'neutral'|'choppy')."""
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = pd.Series(0.0, index=high.index)
    minus_dm = pd.Series(0.0, index=high.index)
    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move

    alpha = 1.0 / period
    smooth_tr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / smooth_tr.replace(0, float("nan"))
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / smooth_tr.replace(0, float("nan"))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
    adx = dx.ewm(alpha=alpha, adjust=False).mean()

    adx_val = float(adx.iloc[-1]) if not adx.empty and not pd.isna(adx.iloc[-1]) else 0.0
    regime = "trending" if adx_val >= 25 else ("choppy" if adx_val <= 20 else "neutral")
    return adx_val, regime


def _cluster_best_level(levels: list[float], tolerance_pct: float = 1.5) -> float | None:
    """Group nearby price levels and return the midpoint of the most-touched cluster.
    Clusters within tolerance_pct% of each other are merged; the cluster with the
    most touches is the strongest S/R zone.
    """
    if not levels:
        return None
    sorted_l = sorted(levels)
    clusters: list[list[float]] = [[sorted_l[0]]]
    for price in sorted_l[1:]:
        ref = clusters[-1][0]
        if ref > 0 and (price - ref) / ref * 100 <= tolerance_pct:
            clusters[-1].append(price)
        else:
            clusters.append([price])
    # Most touches wins; ties broken by highest price (most recent for resistance)
    best = max(clusters, key=lambda c: (len(c), max(c)))
    return round(sum(best) / len(best), 4)


def _find_swing_levels(high: pd.Series, low: pd.Series, n: int = 5) -> dict:
    """Detect swing highs/lows using n-bar pivot logic.
    A swing high: candle whose high is greater than the n candles on each side.
    Returns recent pivot levels plus clustered S/R for more robust targeting.
    """
    highs = high.values
    lows = low.values
    swing_highs: list[float] = []
    swing_lows: list[float] = []

    for i in range(n, len(highs) - n):
        if all(highs[i] > highs[i - j] for j in range(1, n + 1)) and \
           all(highs[i] > highs[i + j] for j in range(1, n + 1)):
            swing_highs.append(round(float(highs[i]), 4))
        if all(lows[i] < lows[i - j] for j in range(1, n + 1)) and \
           all(lows[i] < lows[i + j] for j in range(1, n + 1)):
            swing_lows.append(round(float(lows[i]), 4))

    return {
        "swing_highs": swing_highs[-3:],
        "swing_lows": swing_lows[-3:],
        "swing_resistance": swing_highs[-1] if swing_highs else None,   # most recent pivot
        "swing_support": swing_lows[-1] if swing_lows else None,
        "clustered_resistance": _cluster_best_level(swing_highs),       # most-touched cluster
        "clustered_support": _cluster_best_level(swing_lows),
    }


def _calc_fib_levels(close: pd.Series, high: pd.Series, low: pd.Series) -> dict:
    """Compute Fibonacci extension targets and retracement stop levels.
    Uses the most significant recent leg: lowest low in last 60 bars (swing_low),
    then highest high after that low (swing_high).
    Extensions: above swing_high (targets).
    Retracements: from swing_high down toward swing_low (stop zones).
    """
    lookback = min(60, len(close))
    seg_low = low.iloc[-lookback:]
    seg_high = high.iloc[-lookback:]

    swing_low_idx = int(seg_low.values.argmin())
    swing_low_price = float(seg_low.iloc[swing_low_idx])

    if swing_low_idx >= lookback - 2:
        return {}  # no room for a subsequent leg

    post_low_high = seg_high.iloc[swing_low_idx:]
    swing_high_price = float(post_low_high.values.max())

    if swing_high_price <= swing_low_price:
        return {}
    height = swing_high_price - swing_low_price
    if height / swing_low_price < 0.03:   # less than 3% — noise
        return {}

    return {
        "fib_ext_127": round(swing_high_price + height * 0.272, 2),
        "fib_ext_162": round(swing_high_price + height * 0.618, 2),
        "fib_ext_262": round(swing_high_price + height * 1.618, 2),
        "fib_ret_382": round(swing_high_price - height * 0.382, 2),
        "fib_ret_500": round(swing_high_price - height * 0.500, 2),
        "fib_ret_618": round(swing_high_price - height * 0.618, 2),
        "fib_swing_low": round(swing_low_price, 2),
        "fib_swing_high": round(swing_high_price, 2),
    }


def _calc_hv_rank(close: pd.Series) -> float | None:
    """Historical volatility percentile rank (0–100).
    Uses 21-bar rolling HV (annualised) ranked against a 252-bar window.
    80+ = high vol regime → reduce position size.
    """
    import numpy as np
    if len(close) < 30:
        return None
    log_ret = np.log(close / close.shift(1)).dropna()
    hv_series = log_ret.rolling(21).std() * np.sqrt(252)
    hv_clean = hv_series.dropna().values
    if len(hv_clean) < 10:
        return None
    current_hv = float(hv_clean[-1])
    rank = float(np.sum(hv_clean <= current_hv)) / len(hv_clean) * 100
    return round(rank, 1)


def _calc_weekly_pivots(weekly_hist: pd.DataFrame) -> dict:
    """Floor-trader pivot points from the prior week's OHLCV.
    PP = (H+L+C)/3; R1 = 2×PP−L; R2 = PP+(H−L); S1 = 2×PP−H; S2 = PP−(H−L).
    Widely self-fulfilling at institutional level — natural targets and stops.
    """
    try:
        if weekly_hist is None or len(weekly_hist) < 2:
            return {}
        prev = weekly_hist.iloc[-2]
        h = float(prev["High"])
        l = float(prev["Low"])
        c = float(prev["Close"])
        pp = (h + l + c) / 3
        return {
            "weekly_pp": round(pp, 2),
            "weekly_r1": round(2 * pp - l, 2),
            "weekly_r2": round(pp + (h - l), 2),
            "weekly_s1": round(2 * pp - h, 2),
            "weekly_s2": round(pp - (h - l), 2),
        }
    except Exception:
        return {}


def _calc_bb_squeeze(close: pd.Series, high: pd.Series, low: pd.Series) -> dict:
    """Detect Bollinger Band squeeze: BBs contract inside Keltner Channel.
    Squeeze = compressed volatility preceding a breakout move.
    """
    # Bollinger Bands (20, 2)
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20

    # Keltner Channel — EMA(20) ± 2×Wilder's ATR(10)
    # Using Wilder's smoothed ATR (same as rest of system) and 2× multiplier
    # so the squeeze fires only when BBs are truly compressed, not just slightly inside.
    ema20 = close.ewm(span=20, adjust=False).mean()
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr10 = tr.ewm(alpha=1.0 / 10, adjust=False).mean()  # Wilder's smoothed
    kc_upper = ema20 + 2.0 * atr10
    kc_lower = ema20 - 2.0 * atr10

    squeeze = (bb_upper < kc_upper) & (bb_lower > kc_lower)
    is_squeeze = bool(squeeze.iloc[-1])

    squeeze_bars = 0
    for val in reversed(squeeze.values.tolist()):
        if val:
            squeeze_bars += 1
        else:
            break

    # Squeeze released in last 3 bars = momentum burst just started
    squeeze_released = (not is_squeeze) and bool(squeeze.iloc[-4:-1].any())

    return {
        "bb_squeeze": is_squeeze,
        "squeeze_bars": squeeze_bars,
        "squeeze_released": squeeze_released,
    }


def _check_volume_breakout(
    close: pd.Series, high: pd.Series, volume: pd.Series,
    rsi: float, swing_resistance: float | None
) -> dict:
    """3-checkpoint volume-confirmed breakout detection.
    Score 0–3: (1) price broke swing resistance, (2) volume ≥ 1.5x avg, (3) RSI > 50.
    """
    avg_vol_20 = float(volume.tail(20).mean()) if len(volume) >= 20 else float(volume.mean())
    last_vol = float(volume.iloc[-1])
    last_close = float(close.iloc[-1])
    vol_ratio = round(last_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 0.0

    score = 0
    details: list[str] = []

    if swing_resistance and last_close > swing_resistance:
        score += 1
        details.append("broke resistance")

    if avg_vol_20 > 0 and last_vol >= 1.5 * avg_vol_20:
        score += 1
        details.append(f"vol {vol_ratio:.1f}x avg")

    if rsi > 50:
        score += 1
        details.append(f"RSI={rsi:.0f}")

    return {
        "breakout_score": score,
        "breakout_details": "; ".join(details),
        "vol_ratio": vol_ratio,
    }


def _calc_anchored_vwap(
    close: pd.Series, high: pd.Series, low: pd.Series, volume: pd.Series
) -> dict:
    """VWAP anchored to the most recent significant swing low.

    Bullish structure is intact when price is above AVWAP.
    Stop: AVWAP × 0.998 (small buffer below).
    Priority in stop waterfall: between Fib retracement and Chandelier Exit.
    """
    try:
        lookback = min(len(close), 60)
        if lookback < 10:
            return {}
        seg_close = close.tail(lookback)
        seg_high  = high.tail(lookback)
        seg_low   = low.tail(lookback)
        seg_vol   = volume.tail(lookback)

        # Anchor = lowest close bar in the lookback window (significant swing low)
        swing_low_idx = int(seg_close.values.argmin())
        if swing_low_idx >= lookback - 1:
            return {}  # swing low is today — no meaningful VWAP segment

        tp_from_low  = ((seg_high + seg_low + seg_close) / 3).iloc[swing_low_idx:]
        vol_from_low = seg_vol.iloc[swing_low_idx:]
        cum_vol = float(vol_from_low.sum())
        if cum_vol <= 0:
            return {}

        avwap = float((tp_from_low * vol_from_low).sum() / cum_vol)
        if avwap <= 0:
            return {}

        return {
            "avwap": round(avwap, 2),
            "avwap_stop": round(avwap * 0.998, 2),
            "price_above_avwap": float(close.iloc[-1]) > avwap,
        }
    except Exception:
        return {}


def _calc_weekly_swing_lows(close: pd.Series, low: pd.Series) -> dict:
    """Resample daily bars to weekly and find the nearest weekly swing low below current price.

    Weekly swing low = a week whose low is strictly below both adjacent weeks.
    These are stronger structural stop levels than daily swing lows because
    they absorb more noise and represent institutional demand zones.
    """
    try:
        if not isinstance(close.index, pd.DatetimeIndex):
            return {}
        daily = pd.DataFrame({"close": close, "low": low})
        weekly_low = daily["low"].resample("W").min().dropna()
        if len(weekly_low) < 5:
            return {}

        lows_arr = weekly_low.values
        swing_lows: list[float] = []
        for i in range(1, len(lows_arr) - 1):
            if lows_arr[i] < lows_arr[i - 1] and lows_arr[i] < lows_arr[i + 1]:
                swing_lows.append(float(lows_arr[i]))

        current = float(close.iloc[-1])
        candidates = [sl for sl in swing_lows if sl < current]
        if not candidates:
            return {}
        return {"weekly_structural_stop": round(max(candidates), 2)}
    except Exception:
        return {}


def _calc_volume_profile(
    close: pd.Series, high: pd.Series, low: pd.Series, volume: pd.Series,
    lookback: int = 60, n_buckets: int = 20,
) -> dict:
    """OHLCV volume profile approximation: VPOC, Value Area High (VAH), Value Area Low (VAL).

    Algorithm:
    - Divide the price range of the last `lookback` bars into `n_buckets` equal bins.
    - Assign each bar's volume to the bucket containing its typical price.
    - VPOC = midpoint of highest-volume bucket.
    - Value Area = expand from VPOC until 70% of total volume is covered.
    - VAL = lower boundary, VAH = upper boundary.

    Uses:
    - VAL as stop for longs (closing below = trade structure invalidated)
    - VAH as first target if above current price and R:R ≥ min_rr
    - VPOC as a magnet / area of value
    """
    try:
        n = min(len(close), lookback)
        if n < 10:
            return {}
        seg_close = close.tail(n)
        seg_high  = high.tail(n)
        seg_low   = low.tail(n)
        seg_vol   = volume.tail(n)

        price_min = float(seg_low.min())
        price_max = float(seg_high.max())
        if price_max <= price_min:
            return {}

        bucket_size = (price_max - price_min) / n_buckets
        buckets = [0.0] * n_buckets

        typical = ((seg_high + seg_low + seg_close) / 3).values
        vols = seg_vol.values
        for tp, v in zip(typical, vols):
            idx = min(int((tp - price_min) / bucket_size), n_buckets - 1)
            buckets[idx] += float(v)

        # VPOC
        vpoc_idx = int(max(range(n_buckets), key=lambda i: buckets[i]))
        vpoc = round(price_min + (vpoc_idx + 0.5) * bucket_size, 2)

        # Value Area: expand from VPOC until 70% of total volume
        total_vol = sum(buckets)
        if total_vol <= 0:
            return {}
        target = total_vol * 0.70
        lo_idx = hi_idx = vpoc_idx
        accumulated = buckets[vpoc_idx]

        while accumulated < target:
            can_up   = hi_idx + 1 < n_buckets
            can_down = lo_idx - 1 >= 0
            if not can_up and not can_down:
                break
            up_vol   = buckets[hi_idx + 1] if can_up   else -1.0
            down_vol = buckets[lo_idx - 1] if can_down else -1.0
            if up_vol >= down_vol:
                hi_idx += 1
                accumulated += buckets[hi_idx]
            else:
                lo_idx -= 1
                accumulated += buckets[lo_idx]

        vah = round(price_min + (hi_idx + 1) * bucket_size, 2)
        val = round(price_min + lo_idx * bucket_size, 2)

        return {"vpoc": vpoc, "val": val, "vah": vah}
    except Exception:
        return {}


def _classify_gap(open_: pd.Series, close: pd.Series, volume: pd.Series,
                  ema150_pct: float | None, streak: int) -> dict:
    """Classify the morning gap relative to prior close.

    Types and their documented fill rates:
      none       — gap < 0.3%: no meaningful gap
      common     — 0.3-1.5%: fills ~90% of the time, low signal value
      breakaway  — > 1.5% out of a base with volume: continuation (35% fill)
      exhaustion — > 1.5% after extended trend with volume: fade risk (75% fill)
    """
    if len(close) < 2 or open_.empty:
        return {"gap_type": "none", "gap_pct": 0.0}

    prev_close = float(close.iloc[-2])
    today_open = float(open_.iloc[-1])
    if prev_close <= 0:
        return {"gap_type": "none", "gap_pct": 0.0}

    gap_pct = (today_open - prev_close) / prev_close * 100
    abs_gap = abs(gap_pct)

    avg_vol = float(volume.tail(20).mean()) if len(volume) >= 20 else float(volume.mean())
    vol_elevated = avg_vol > 0 and float(volume.iloc[-1]) >= 1.5 * avg_vol

    if abs_gap < 0.3:
        return {"gap_type": "none", "gap_pct": round(gap_pct, 2)}
    if abs_gap < 1.5:
        return {"gap_type": "common", "gap_pct": round(gap_pct, 2)}

    # Large gap — breakaway or exhaustion
    overextended = (
        (ema150_pct is not None and ema150_pct > 20) or   # far above 150-EMA
        (gap_pct > 0 and streak >= 5)                      # gap after 5+ up days
    )
    if overextended and vol_elevated:
        return {"gap_type": "exhaustion", "gap_pct": round(gap_pct, 2)}
    if vol_elevated:
        return {"gap_type": "breakaway", "gap_pct": round(gap_pct, 2)}
    return {"gap_type": "common", "gap_pct": round(gap_pct, 2)}


def _calc_indicators(hist: pd.DataFrame) -> dict:
    close = hist["Close"].squeeze()
    high = hist["High"].squeeze()
    low = hist["Low"].squeeze()
    volume = hist["Volume"].squeeze()
    open_ = hist["Open"].squeeze() if "Open" in hist.columns else pd.Series(dtype=float)
    current_price = float(close.iloc[-1])

    # RSI-14
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = float((100 - 100 / (1 + gain / loss)).iloc[-1])

    # MACD (12/26/9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_hist = float(((ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()).iloc[-1])

    # ATR-14
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = float(tr.tail(14).mean())

    # Bollinger Bands (20-day)
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = float((sma20 + 2 * std20).iloc[-1])
    bb_lower = float((sma20 - 2 * std20).iloc[-1])
    bb_mid = float(sma20.iloc[-1])

    # VWAP (20-day rolling)
    typical_price = (high + low + close) / 3
    vwap = float(
        (typical_price * volume).rolling(20).sum().iloc[-1]
        / volume.rolling(20).sum().iloc[-1]
    )

    # ADX(14) + regime
    adx_val, regime = _calc_adx(high, low, close, period=14)

    # Swing high/low S/R levels
    swing = _find_swing_levels(high, low, n=5)

    # BB Squeeze
    squeeze = _calc_bb_squeeze(close, high, low)

    # Volume-confirmed breakout
    breakout = _check_volume_breakout(close, high, volume, rsi, swing["swing_resistance"])

    # NR7: today's high-low range is the smallest of the last 7 days
    # Signals compressed volatility → imminent breakout (Crabel)
    daily_ranges = (high - low).tail(7)
    nr7 = len(daily_ranges) == 7 and float(daily_ranges.iloc[-1]) == float(daily_ranges.min())

    # EMA 150 — Weinstein Stage 2 filter + overextension signal
    # Needs ~150 bars; gracefully degrades to None if insufficient history
    ema150_pct: float | None = None
    if len(close) >= 60:  # minimum bars for a useful EMA150 estimate
        ema150_val = float(close.ewm(span=150, adjust=False).mean().iloc[-1])
        if ema150_val > 0:
            ema150_pct = round((current_price - ema150_val) / ema150_val * 100, 1)

    # Consecutive up/down day streak (Connors RSI component)
    streak = _calc_streak(close)

    # Fibonacci extension targets and retracement stop levels
    fib = _calc_fib_levels(close, high, low)

    # Historical volatility percentile rank (position size throttle)
    hv_rank = _calc_hv_rank(close)

    # Anchored VWAP (stop between Fib retracement and Chandelier)
    avwap = _calc_anchored_vwap(close, high, low, volume)

    # Weekly swing lows as structural stop levels
    weekly_stops = _calc_weekly_swing_lows(close, low)

    # Volume Profile: VPOC, VAL, VAH
    vol_profile = _calc_volume_profile(close, high, low, volume)

    # Gap type classification (uses data already computed above)
    gap = _classify_gap(open_, close, volume, ema150_pct, streak)

    return {
        "price": current_price,
        "rsi": rsi,
        "macd_hist": macd_hist,
        "atr": atr,
        "atr_pct": atr / current_price * 100,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_mid": bb_mid,
        "vwap": vwap,
        "price_vs_sma": (current_price - bb_mid) / bb_mid * 100,
        "adx": adx_val,
        "regime": regime,
        "nr7": nr7,
        "ema150_pct": ema150_pct,
        "streak": streak,
        "hv_rank": hv_rank,
        **swing,
        **squeeze,
        **breakout,
        **fib,
        **avwap,
        **weekly_stops,
        **vol_profile,
        **gap,
    }


def _get_weekly_mtf(tickers: list[str], all_weekly: Any) -> dict[str, bool]:
    """Return {ticker: mtf_aligned} where True = price above 20-week SMA."""
    result: dict[str, bool] = {}
    for ticker in tickers:
        try:
            try:
                hist = all_weekly[ticker] if ticker in all_weekly.columns.get_level_values(0) else pd.DataFrame()
            except Exception:
                hist = pd.DataFrame()
            if hist.empty or len(hist) < 20:
                result[ticker] = False
                continue
            close = hist["Close"].squeeze().dropna()
            sma20w = close.rolling(20).mean()
            result[ticker] = float(close.iloc[-1]) > float(sma20w.iloc[-1])
        except Exception:
            result[ticker] = False
    return result


def _load_precomputed_technicals(tickers: list[str]) -> dict[str, dict]:
    """
    Query precomputed_technicals for rows updated today.
    Returns {ticker: {sma20, sma50, vwap20, ema150}} for warm tickers only.
    Tickers absent from the result need a full 1y yfinance download.
    """
    result: dict[str, dict] = {}
    try:
        import psycopg2
        from datetime import date
        from app.config import get_settings
        db_url = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                placeholders = ",".join(["%s"] * len(tickers))
                cur.execute(
                    f"""
                    SELECT ticker, sma20, sma50, vwap20, ema150, last_close, last_volume
                    FROM precomputed_technicals
                    WHERE ticker IN ({placeholders})
                      AND last_date >= %s
                    """,
                    tickers + [date.today()],
                )
                for row in cur.fetchall():
                    ticker, sma20, sma50, vwap20, ema150, last_close, last_volume = row
                    if sma20 is not None and ema150 is not None:
                        result[ticker] = {
                            "sma20": sma20, "sma50": sma50,
                            "vwap20": vwap20, "ema150": ema150,
                            "last_close": last_close, "last_volume": last_volume,
                        }
        finally:
            conn.close()
    except Exception as e:
        logger.debug("precomputed_technicals query failed (non-fatal)", error=str(e))
    return result


def technical_node(state: dict[str, Any]) -> dict[str, Any]:
    tickers = state.get("candidate_tickers", [])
    if not tickers:
        return {"technical_scores": {}, "errors": []}

    try:
        from app.config import has_anthropic_key
        from app.services.data_resilience import fetch_ohlcv_with_fallback

        # Check which tickers have fresh pre-computed values in the DB.
        # For those we can download only 3 months of daily data (enough for ADX,
        # BB Squeeze, NR7, streak, swing levels) and use the DB-stored EMA150/SMA20.
        # For cold tickers (no DB row yet) we still download 1y to warm the EMA.
        precomputed = _load_precomputed_technicals(tickers)
        warm_tickers = [t for t in tickers if t in precomputed]
        cold_tickers = [t for t in tickers if t not in precomputed]

        if warm_tickers:
            logger.info("Technical node using DB pre-computed values",
                        warm=len(warm_tickers), cold=len(cold_tickers))

        # Download 1y for all tickers — patterns (cup_handle, double_bottom, etc.) need
        # enough history to detect multi-month bases. 3mo was insufficient for warm tickers.
        all_data_warm = None
        all_data_cold = None
        data_source = "yfinance"

        if warm_tickers:
            all_data_warm, data_source = fetch_ohlcv_with_fallback(warm_tickers, period="1y")
        if cold_tickers:
            all_data_cold, src = fetch_ohlcv_with_fallback(cold_tickers, period="1y")
            if data_source == "yfinance":
                data_source = src

        if all_data_warm is None and all_data_cold is None:
            return {"technical_scores": {}, "errors": ["technical: all data sources failed"]}
        if data_source != "yfinance":
            logger.info("Technical node using fallback data source", source=data_source)

        # Merge: prefer warm data for warm tickers; cold data for cold tickers
        if all_data_warm is not None and all_data_cold is not None:
            all_data = pd.concat([all_data_warm, all_data_cold], axis=1)
        elif all_data_warm is not None:
            all_data = all_data_warm
        else:
            all_data = all_data_cold

        # Weekly download: 1y for cold tickers only (MTF SMA20-week)
        weekly_period = "1y" if cold_tickers else "3mo"
        all_weekly = yf.download(
            tickers, period=weekly_period, interval="1wk",
            progress=False, auto_adjust=True, group_by="ticker"
        )

        indicators: dict[str, dict] = {}
        for ticker in tickers:
            try:
                hist = all_data[ticker] if ticker in all_data.columns.get_level_values(0) else pd.DataFrame()
                if hist.empty or len(hist) < 20:
                    continue
                ind = _calc_indicators(hist)

                # Chart pattern detection
                try:
                    from app.agents.patterns.detector import detect_all_patterns
                    pat = detect_all_patterns(hist)
                    bp = pat.get("best_bullish")
                    ind["pattern_name"]     = bp.name     if bp else None
                    ind["pattern_strength"] = bp.strength if bp else 0.0
                    ind["pattern_pivot"]    = bp.pivot     if bp else None
                    ind["pattern_stop"]     = bp.pattern_stop   if bp else None
                    ind["pattern_target"]   = bp.pattern_target if bp else None
                    ind["pattern_details"]  = bp.details   if bp else None
                    # Keep full result set for downstream nodes
                    ind["_pattern_results"] = pat
                except Exception:
                    ind["pattern_name"] = None
                    ind["pattern_strength"] = 0.0
                    ind["_pattern_results"] = {}

                # Overlay DB pre-computed values for warm tickers — overrides the
                # pandas-computed sma20/vwap/ema150 with the authoritative DB values.
                if ticker in precomputed:
                    pre = precomputed[ticker]
                    if pre.get("sma20") is not None:
                        ind["bb_mid"] = pre["sma20"]          # SMA20 = BB midline
                        ind["price_vs_sma"] = (ind["price"] - pre["sma20"]) / pre["sma20"] * 100
                    if pre.get("vwap20") is not None:
                        ind["vwap"] = pre["vwap20"]
                    if pre.get("ema150") is not None:
                        ema150_val = pre["ema150"]
                        if ema150_val > 0:
                            ind["ema150_pct"] = round(
                                (ind["price"] - ema150_val) / ema150_val * 100, 1
                            )

                indicators[ticker] = ind
            except Exception as e:
                logger.warning("Technical indicator calc failed", ticker=ticker, error=str(e))

        if not indicators:
            return {"technical_scores": {}, "errors": ["technical: no indicator data"]}

        # MTF alignment
        valid_tickers = list(indicators.keys())
        mtf_map = _get_weekly_mtf(valid_tickers, all_weekly)
        for ticker in valid_tickers:
            indicators[ticker]["mtf_aligned"] = mtf_map.get(ticker, False)

        # Weekly pivot points (R1/R2 as targets, S1 as stop proximity)
        for ticker in valid_tickers:
            try:
                w_hist = (
                    all_weekly[ticker]
                    if not all_weekly.empty and ticker in all_weekly.columns.get_level_values(0)
                    else pd.DataFrame()
                )
                indicators[ticker].update(_calc_weekly_pivots(w_hist))
            except Exception:
                pass

        # Short interest: fetch shortPercentOfFloat + shortRatio (days to cover) per ticker
        # Cached in Redis for 4h to avoid repeated yfinance info calls
        from app.agents.cache_utils import _sync_redis
        import json as _json
        _r = _sync_redis()
        for ticker in valid_tickers:
            short_pct = None
            short_dtc = None
            try:
                cache_key = f"short_interest:{ticker}"
                if _r:
                    cached = _r.get(cache_key)
                    if cached:
                        d = _json.loads(cached)
                        short_pct = d.get("short_pct")
                        short_dtc = d.get("short_dtc")
                if short_pct is None:
                    info = yf.Ticker(ticker).info
                    raw_pct = info.get("shortPercentOfFloat")
                    raw_dtc = info.get("shortRatio")
                    short_pct = round(float(raw_pct) * 100, 1) if raw_pct else None
                    short_dtc = round(float(raw_dtc), 1) if raw_dtc else None
                    if _r:
                        _r.setex(cache_key, 14_400, _json.dumps({"short_pct": short_pct, "short_dtc": short_dtc}))
            except Exception:
                pass
            indicators[ticker]["short_pct"] = short_pct
            indicators[ticker]["short_dtc"] = short_dtc

        mode = state.get("mode", "swing")

        # --- Redis cache: split tickers into cached vs uncached ---
        from app.agents.cache_utils import score_get, score_set
        cached_scores: dict[str, Any] = {}
        uncached_tickers: list[str] = []
        for t in valid_tickers:
            cached = score_get("technical", t, mode=mode)
            if cached:
                cached_scores[t] = cached
            else:
                uncached_tickers.append(t)

        if cached_scores:
            logger.info("Technical cache hits", count=len(cached_scores), uncached=len(uncached_tickers))

        scores: dict[str, Any] = dict(cached_scores)

        llm_ok = False
        if uncached_tickers and has_anthropic_key():
            try:
                from anthropic import Anthropic
                from app.config import get_settings
                client = Anthropic(api_key=get_settings().anthropic_api_key)

                lines = []
                for ticker in uncached_tickers:
                    ind = indicators[ticker]
                    bb_pos = (
                        "above_upper" if ind["price"] > ind["bb_upper"]
                        else ("below_lower" if ind["price"] < ind["bb_lower"] else "mid")
                    )
                    squeeze_str = f"yes({ind['squeeze_bars']}bars)" if ind["bb_squeeze"] else (
                        "released" if ind["squeeze_released"] else "no"
                    )
                    resist = f"${ind['swing_resistance']:.2f}" if ind["swing_resistance"] else "N/A"
                    support = f"${ind['swing_support']:.2f}" if ind["swing_support"] else "N/A"
                    short_str = (
                        f"{ind['short_pct']:.0f}%/{ind['short_dtc']:.1f}d"
                        if ind.get("short_pct") is not None else "n/a"
                    )
                    ema150 = ind.get("ema150_pct")
                    ema150_str = (
                        f"{ema150:+.1f}%"
                        if ema150 is not None else "n/a"
                    )
                    streak = ind.get("streak", 0)
                    streak_str = f"{streak:+d}d" if streak != 0 else "0d"
                    pat_name = ind.get("pattern_name")
                    pat_str = (
                        f"{pat_name}(str={ind['pattern_strength']:.2f}"
                        + (f",pivot=${ind['pattern_pivot']:.2f}" if ind.get("pattern_pivot") else "")
                        + ")"
                        if pat_name else "none"
                    )
                    lines.append(
                        f"{ticker}: RSI={ind['rsi']:.1f}, MACD={'bull' if ind['macd_hist'] > 0 else 'bear'}, "
                        f"ATR%={ind['atr_pct']:.1f}%, ADX={ind['adx']:.1f}({ind['regime']}), "
                        f"BB={bb_pos}, BB_Squeeze={squeeze_str}, "
                        f"Breakout={ind['breakout_score']}/3({ind['breakout_details'] or 'none'}), "
                        f"Vol={ind['vol_ratio']:.1f}x, Resist={resist}, Support={support}, "
                        f"VWAP={'above' if ind['price'] > ind['vwap'] else 'below'}, "
                        f"MTF={'yes' if ind['mtf_aligned'] else 'no'}, "
                        f"NR7={'yes' if ind.get('nr7') else 'no'}, "
                        f"Short%/DTC={short_str}, "
                        f"EMA150={ema150_str}, Streak={streak_str}, "
                        f"Pattern={pat_str}"
                    )

                if mode == "intraday":
                    prefix = (
                        "INTRADAY mode: Score 0.0–1.0 for same-day bullish setup quality.\n"
                        "Prioritise: VWAP position (above=bullish), high vol ratio (>1.5x), ATR% (higher=better for intraday), "
                        "Breakout 3/3 with volume confirmation, RSI 50–65 (momentum without being overbought).\n"
                        "MTF alignment is a bonus but NOT required for intraday.\n"
                        "Penalise: low vol ratio (<0.8x), VWAP below, choppy ADX with no breakout.\n\n"
                    )
                else:
                    prefix = (
                        "SWING mode: Score 0.0–1.0 for multi-day (2–5 day) bullish setup quality.\n"
                        "Prioritise: MTF_ALIGNED=yes (weekly uptrend), ADX trending(>25), Breakout 3/3, "
                        "BB_Squeeze released, price above SMA20.\n"
                        "Penalise: MTF misaligned (weekly downtrend), choppy ADX with no squeeze, low volume.\n\n"
                    )

                from app.agents.llm_utils import call_llm_batched
                raw_response = call_llm_batched(
                    client, lines, TECHNICAL_SYSTEM,
                    prompt_prefix=prefix,
                    tokens_per_line=80,
                )

                for line in raw_response.split("\n"):
                    parts = line.split("|")
                    if len(parts) < 3:
                        continue
                    t = parts[0].strip().upper()
                    if t not in indicators:
                        continue
                    try:
                        nums = re.findall(r"0\.\d+|1\.0\b", parts[1])
                        score = float(nums[0]) if nums else 0.5
                        entry = {"score": round(score, 4), "reasoning": parts[2].strip()[:300]}
                        scores[t] = entry
                        score_set("technical", t, entry, mode=mode)
                    except Exception:
                        pass
                llm_ok = True
            except Exception as e:
                logger.warning("Technical LLM call failed, falling back to rule-based", error=str(e))

        # Rule-based fallback for any ticker still not scored (parse failures or no LLM key)
        for ticker in [t for t in valid_tickers if t not in scores]:
            ind = indicators[ticker]
            score = 0.5
            regime = ind["regime"]

            if mode == "intraday":
                # Intraday: VWAP position + volume + short-term momentum
                if ind["price"] > ind["vwap"]:
                    score += 0.15
                if ind["vol_ratio"] >= 1.5:
                    score += 0.15
                elif ind["vol_ratio"] < 0.8:
                    score -= 0.10
                if 50 < ind["rsi"] < 70:
                    score += 0.10
                elif ind["rsi"] > 75:
                    score -= 0.10
                if ind["macd_hist"] > 0:
                    score += 0.08
                score += ind["breakout_score"] * 0.08
            else:
                # Swing: regime-aware, MTF critical
                if regime == "trending":
                    if ind["macd_hist"] > 0:
                        score += 0.15
                    if ind["price_vs_sma"] > 0:
                        score += 0.1
                    if ind["price"] > ind["vwap"]:
                        score += 0.05
                    if 40 < ind["rsi"] < 65:
                        score += 0.1
                elif regime == "choppy":
                    if ind["rsi"] < 35:
                        score += 0.2
                    elif ind["rsi"] > 70:
                        score -= 0.2
                    if ind["price"] < ind["bb_lower"]:
                        score += 0.15
                else:
                    if ind["rsi"] < 30:
                        score += 0.2
                    elif ind["rsi"] > 70:
                        score -= 0.2
                    if ind["macd_hist"] > 0:
                        score += 0.1

                score += ind["breakout_score"] * 0.07
                if ind["squeeze_released"]:
                    score += 0.10
                elif ind["bb_squeeze"]:
                    score += 0.05
                # MTF critical for swing
                if ind["mtf_aligned"]:
                    score += 0.12
                else:
                    score -= 0.08
                # EMA150 overextension penalty (rule-based only)
                ema150 = ind.get("ema150_pct")
                if ema150 is not None and ema150 > 25:
                    score -= 0.08  # stretched above 150 EMA
                elif ema150 is not None and ema150 < 0:
                    score -= 0.10  # below 150 EMA = Stage 3/4
                # Streak exhaustion: penalise only in non-trending regime
                streak = ind.get("streak", 0)
                if streak >= 5 and regime != "trending" and ind["rsi"] > 65:
                    score -= 0.08  # mean-reversion risk

            entry = {
                "score": round(max(0.0, min(1.0, score)), 4),
                "reasoning": (
                    f"Rule-based ({mode}/{regime}): RSI={ind['rsi']:.1f}, "
                    f"VWAP={'above' if ind['price'] > ind['vwap'] else 'below'}, "
                    f"Vol={ind['vol_ratio']:.1f}x, ADX={ind['adx']:.1f}, "
                    f"Breakout={ind['breakout_score']}/3, "
                    f"MTF={'aligned' if ind['mtf_aligned'] else 'mis'}"
                ),
            }
            scores[ticker] = entry
            score_set("technical", ticker, entry, mode=mode)

        # Merge metadata into scores
        for ticker, ind in indicators.items():
            if ticker not in scores:
                scores[ticker] = {"score": 0.5, "reasoning": "no LLM score"}
            scores[ticker].update({
                "rsi": round(ind["rsi"], 2),
                "atr": round(ind["atr"], 4),
                "adx": round(ind["adx"], 2),
                "regime": ind["regime"],
                "mtf_aligned": ind["mtf_aligned"],
                "bb_squeeze": ind["bb_squeeze"],
                "squeeze_released": ind["squeeze_released"],
                "breakout_score": ind["breakout_score"],
                "swing_resistance": ind["swing_resistance"],
                "swing_support": ind["swing_support"],
                "macd_signal": "bullish" if ind["macd_hist"] > 0 else "bearish",
                "bb_position": (
                    "above_upper" if ind["price"] > ind["bb_upper"]
                    else ("below_lower" if ind["price"] < ind["bb_lower"] else "middle")
                ),
                "vwap_relation": "above" if ind["price"] > ind["vwap"] else "below",
                "vol_ratio": ind["vol_ratio"],
                "short_pct": ind.get("short_pct"),
                "short_dtc": ind.get("short_dtc"),
                "breakout_details": ind.get("breakout_details", ""),
                "nr7": ind.get("nr7", False),
                "ema150_pct": ind.get("ema150_pct"),
                "streak": ind.get("streak", 0),
                "pattern_name": ind.get("pattern_name"),
                "pattern_strength": ind.get("pattern_strength", 0.0),
                "pattern_pivot": ind.get("pattern_pivot"),
                "pattern_stop": ind.get("pattern_stop"),
                "pattern_target": ind.get("pattern_target"),
                "pattern_details": ind.get("pattern_details"),
                "_pattern_results": ind.get("_pattern_results", {}),
                # Fibonacci levels
                "fib_ext_127": ind.get("fib_ext_127"),
                "fib_ext_162": ind.get("fib_ext_162"),
                "fib_ext_262": ind.get("fib_ext_262"),
                "fib_ret_382": ind.get("fib_ret_382"),
                "fib_ret_500": ind.get("fib_ret_500"),
                "fib_ret_618": ind.get("fib_ret_618"),
                # Clustered S/R
                "clustered_resistance": ind.get("clustered_resistance"),
                "clustered_support": ind.get("clustered_support"),
                # HV rank and weekly pivots
                "hv_rank": ind.get("hv_rank"),
                "weekly_pp": ind.get("weekly_pp"),
                "weekly_r1": ind.get("weekly_r1"),
                "weekly_r2": ind.get("weekly_r2"),
                "weekly_s1": ind.get("weekly_s1"),
                "weekly_s2": ind.get("weekly_s2"),
                # Phase 3: AVWAP, Volume Profile, Weekly Swing Lows, Gap
                "avwap": ind.get("avwap"),
                "avwap_stop": ind.get("avwap_stop"),
                "price_above_avwap": ind.get("price_above_avwap"),
                "vpoc": ind.get("vpoc"),
                "val": ind.get("val"),
                "vah": ind.get("vah"),
                "weekly_structural_stop": ind.get("weekly_structural_stop"),
                "gap_type": ind.get("gap_type"),
                "gap_pct": ind.get("gap_pct"),
            })

        logger.info("Technical node complete", tickers_analyzed=len(scores))
        return {"technical_scores": scores, "errors": []}

    except Exception as e:
        logger.error("Technical node failed", error=str(e))
        return {"technical_scores": {}, "errors": [f"technical: {e}"]}

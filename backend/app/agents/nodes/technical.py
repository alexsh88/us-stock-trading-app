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
Respond with one line per stock: TICKER|SCORE|REASONING (max 100 chars reasoning).

Examples (use the full 0.0-1.0 range):
NVDA|0.88|Trending ADX=34, MTF aligned, BB squeeze released, breakout 3/3, RSI=66, EMA150=+11% healthy
XOM|0.29|Choppy ADX=15, MTF misaligned (weekly downtrend), no squeeze, breakout 0/3
MSFT|0.63|Neutral ADX=22, MTF aligned, squeeze building 4 bars, breakout 1/3, EMA150=+8%
APA|0.44|Trending but Streak=+7d, EMA150=+29% overextended, RSI=74 overbought — wait for pullback
GME|0.19|Choppy ADX=12, MTF misaligned, vol declining, breakout 0/3, avoid"""


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


def _find_swing_levels(high: pd.Series, low: pd.Series, n: int = 5) -> dict:
    """Detect swing highs/lows using n-bar pivot logic.
    A swing high: candle whose high is greater than the n candles on each side.
    Returns the last 3 swing highs and lows as price level lists.
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
        "swing_highs": swing_highs[-3:],   # last 3 swing highs (resistance)
        "swing_lows": swing_lows[-3:],     # last 3 swing lows (support)
        "swing_resistance": swing_highs[-1] if swing_highs else None,
        "swing_support": swing_lows[-1] if swing_lows else None,
    }


def _calc_bb_squeeze(close: pd.Series, high: pd.Series, low: pd.Series) -> dict:
    """Detect Bollinger Band squeeze: BBs contract inside Keltner Channel.
    Squeeze = compressed volatility preceding a breakout move.
    """
    # Bollinger Bands (20, 2)
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20

    # Keltner Channel (EMA20, ATR10, 1.5x)
    ema20 = close.ewm(span=20, adjust=False).mean()
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr10 = tr.rolling(10).mean()
    kc_upper = ema20 + 1.5 * atr10
    kc_lower = ema20 - 1.5 * atr10

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


def _calc_indicators(hist: pd.DataFrame) -> dict:
    close = hist["Close"].squeeze()
    high = hist["High"].squeeze()
    low = hist["Low"].squeeze()
    volume = hist["Volume"].squeeze()
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
        **swing,
        **squeeze,
        **breakout,
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


def technical_node(state: dict[str, Any]) -> dict[str, Any]:
    tickers = state.get("candidate_tickers", [])
    if not tickers:
        return {"technical_scores": {}, "errors": []}

    try:
        from app.config import has_anthropic_key

        # Batch download daily (1y) for all indicators — 1y needed for 150 EMA warmup
        from app.services.data_resilience import fetch_ohlcv_with_fallback
        all_data, data_source = fetch_ohlcv_with_fallback(tickers, period="1y")
        if all_data is None:
            return {"technical_scores": {}, "errors": ["technical: all data sources failed"]}
        if data_source != "yfinance":
            logger.info("Technical node using fallback data source", source=data_source)

        # Batch download weekly (1y) for MTF 20-week SMA
        all_weekly = yf.download(
            tickers, period="1y", interval="1wk",
            progress=False, auto_adjust=True, group_by="ticker"
        )

        indicators: dict[str, dict] = {}
        for ticker in tickers:
            try:
                hist = all_data[ticker] if ticker in all_data.columns.get_level_values(0) else pd.DataFrame()
                if hist.empty or len(hist) < 20:
                    continue
                indicators[ticker] = _calc_indicators(hist)
            except Exception as e:
                logger.warning("Technical indicator calc failed", ticker=ticker, error=str(e))

        if not indicators:
            return {"technical_scores": {}, "errors": ["technical: no indicator data"]}

        # MTF alignment
        valid_tickers = list(indicators.keys())
        mtf_map = _get_weekly_mtf(valid_tickers, all_weekly)
        for ticker in valid_tickers:
            indicators[ticker]["mtf_aligned"] = mtf_map.get(ticker, False)

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
                        f"EMA150={ema150_str}, Streak={streak_str}"
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
            })

        logger.info("Technical node complete", tickers_analyzed=len(scores))
        return {"technical_scores": scores, "errors": []}

    except Exception as e:
        logger.error("Technical node failed", error=str(e))
        return {"technical_scores": {}, "errors": [f"technical: {e}"]}

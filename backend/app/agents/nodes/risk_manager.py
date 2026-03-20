import structlog
import yfinance as yf
import pandas as pd
from typing import Any

logger = structlog.get_logger()

# Minimum acceptable R:R per mode — signals below this are not worth taking
MIN_RR = {"swing": 2.0, "intraday": 1.5}


def calculate_atr(hist: pd.DataFrame, period: int = 14) -> float:
    try:
        high = hist["High"].squeeze()
        low = hist["Low"].squeeze()
        close = hist["Close"].squeeze()
        prev_close = close.shift(1)
        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        # Wilder's smoothed ATR (EMA with alpha=1/period) — more responsive to vol expansion
        return float(tr.ewm(alpha=1.0 / period, adjust=False).mean().iloc[-1])
    except Exception:
        return 0.0


def calculate_chandelier_stop(hist: pd.DataFrame, period: int = 10, multiplier: float = 2.5) -> float | None:
    """Chandelier Exit: highest_close(period) - multiplier × ATR(period).
    Ratchets up with price, never moves against the position.
    Returns the current stop price or None if insufficient data.
    """
    try:
        close = hist["Close"].squeeze()
        if len(close) < period + 1:
            return None
        atr = calculate_atr(hist, period=period)
        if atr == 0:
            return None
        highest_close = float(close.tail(period).max())
        return round(highest_close - multiplier * atr, 2)
    except Exception:
        return None


def kelly_position_size(win_rate: float, avg_win: float, avg_loss: float, max_pct: float = 5.0) -> float:
    if avg_loss == 0:
        return 0.0
    b = avg_win / avg_loss
    kelly = win_rate - (1 - win_rate) / b
    # Quarter-Kelly for safety, capped at max_pct
    return min(max(kelly * 0.25 * 100, 0.5), max_pct)


def risk_manager_node(state: dict[str, Any]) -> dict[str, Any]:
    tickers = state.get("candidate_tickers", [])
    mode = state.get("mode", "swing")

    if not tickers:
        return {"risk_metrics": {}, "errors": []}

    atr_multiplier = 2.0 if mode == "swing" else 1.5
    min_rr = MIN_RR.get(mode, 2.0)

    # Apply market regime sizing multiplier (set by screener via VIX + SPY MA200 analysis)
    regime = state.get("market_regime", {})
    regime_sizing = float(regime.get("sizing_multiplier", 1.0))
    if regime_sizing < 1.0:
        logger.info("Regime sizing reduction applied", multiplier=regime_sizing, reason=regime.get("reason", ""))

    try:
        # Batch download all tickers — with circuit breaker fallback chain
        from app.services.data_resilience import fetch_ohlcv_with_fallback
        all_hist, data_source = fetch_ohlcv_with_fallback(tickers, period="1mo")
        if all_hist is None:
            return {"risk_metrics": {}, "errors": ["risk_manager: all data sources failed"]}
        if data_source != "yfinance":
            logger.info("Risk manager using fallback data source", source=data_source)

        metrics: dict[str, Any] = {}

        for ticker in tickers:
            try:
                try:
                    hist = all_hist[ticker] if ticker in all_hist.columns.get_level_values(0) else pd.DataFrame()
                except Exception:
                    hist = pd.DataFrame()

                if hist.empty:
                    continue

                current_price = float(hist["Close"].iloc[-1].item())
                atr = calculate_atr(hist)

                if atr == 0 or current_price == 0:
                    continue

                # ── Stop loss priority ────────────────────────────────────────────
                # 1.  Pattern-specific stop (strength ≥ 0.65)
                # 1.5 Fibonacci retracement stop (price within 5% above 61.8/50/38.2%)
                # 2.  Chandelier Exit (swing mode)
                # 3.  ATR-based stop (fallback / intraday)
                tech = state.get("technical_scores", {}).get(ticker, {})
                pat_stop     = tech.get("pattern_stop")
                pat_target   = tech.get("pattern_target")
                pat_strength = tech.get("pattern_strength", 0.0)
                pat_name     = tech.get("pattern_name")

                # ── Stop priority waterfall ───────────────────────────────────────
                # Each priority only fires if the previous one did not assign a stop.
                stop_loss_price = None
                stop_method = None

                # 1. Pattern stop (strong pattern with defined invalidation level)
                if pat_stop and pat_strength >= 0.65 and pat_stop < current_price:
                    stop_loss_price = round(pat_stop, 2)
                    stop_method = f"{pat_name}-invalidation(str={pat_strength:.2f})"

                # 1.5. Fibonacci retracement stop
                # When price is within 5% above a Fib level, that level is a natural
                # support zone — the stop belongs just below it (0.5% buffer).
                if stop_loss_price is None:
                    for fib_key, fib_label in [
                        ("fib_ret_618", "Fib61.8"),
                        ("fib_ret_500", "Fib50.0"),
                        ("fib_ret_382", "Fib38.2"),
                    ]:
                        level = tech.get(fib_key)
                        if level and 0 < level < current_price:
                            if (current_price - level) / current_price * 100 <= 5.0:
                                stop_loss_price = round(level * 0.995, 2)
                                stop_method = f"{fib_label}(${level:.2f})"
                                break

                # 2. Chandelier Exit (swing mode — ratchets up with price)
                if stop_loss_price is None and mode == "swing":
                    chandelier = calculate_chandelier_stop(hist, period=10, multiplier=2.5)
                    atr_stop = round(current_price - atr * atr_multiplier, 2)
                    if chandelier and chandelier > atr_stop:
                        stop_loss_price = chandelier
                        stop_method = f"Chandelier-2.5x (ATR={atr:.3f})"
                    else:
                        stop_loss_price = atr_stop
                        stop_method = f"ATR-{atr_multiplier}x (ATR={atr:.3f})"

                # 3. ATR stop (intraday fallback)
                if stop_loss_price is None:
                    stop_loss_price = round(current_price - atr * atr_multiplier, 2)
                    stop_method = f"ATR-{atr_multiplier}x (ATR={atr:.3f})"

                stop_distance = current_price - stop_loss_price
                if stop_distance <= 0:
                    # Degenerate case — fall back to ATR stop
                    stop_loss_price = round(current_price - atr * atr_multiplier, 2)
                    stop_method = f"ATR-{atr_multiplier}x (ATR={atr:.3f})"
                    stop_distance = current_price - stop_loss_price

                # Minimum target = entry + (stop_distance × min_rr)
                min_target_price = round(current_price + stop_distance * min_rr, 2)

                stop_loss_pct = stop_distance / current_price
                avg_win = stop_distance * min_rr
                kelly_pct = kelly_position_size(0.50, avg_win, stop_distance)

                # ── HV percentile position size throttle ─────────────────────────
                # High-volatility regimes require smaller position sizes.
                # hv_rank=0 means quietest 10th percentile; 100=most volatile.
                hv_rank = tech.get("hv_rank")
                if hv_rank is not None:
                    if hv_rank >= 80:
                        kelly_pct *= 0.50   # extreme vol: half size
                    elif hv_rank >= 40:
                        kelly_pct *= 0.75   # elevated vol: 3/4 size

                swing_resistance = tech.get("swing_resistance")
                clustered_resistance = tech.get("clustered_resistance")

                # ── Target priority waterfall ─────────────────────────────────────
                # Each level only fires if the previous one did not set a target.
                target_price = min_target_price
                target_rr = min_rr
                target_method = "min_rr_floor"

                def _try_target(price: float, label: str) -> bool:
                    nonlocal target_price, target_rr, target_method
                    if price > current_price:
                        rr = (price - current_price) / stop_distance
                        if rr >= min_rr:
                            target_price = round(price, 2)
                            target_rr = round(rr, 2)
                            target_method = label
                            return True
                    return False

                # 1. Pattern measured-move target
                if pat_target and pat_strength >= 0.65:
                    _try_target(pat_target, f"pattern-{pat_name}")

                # 2. Fibonacci 1.272x extension (nearest viable extension above current price)
                if target_price == min_target_price:
                    for fib_key, fib_label in [("fib_ext_127", "Fib127"), ("fib_ext_162", "Fib162")]:
                        if _try_target(tech.get(fib_key) or 0, fib_label):
                            break

                # 3. Weekly pivot R1 then R2
                if target_price == min_target_price:
                    for piv_key, piv_label in [("weekly_r1", "WeeklyR1"), ("weekly_r2", "WeeklyR2")]:
                        if _try_target(tech.get(piv_key) or 0, piv_label):
                            break

                # 4. Clustered swing resistance (most-touched S/R level)
                if target_price == min_target_price and clustered_resistance:
                    _try_target(clustered_resistance, "ClusteredResist")

                # 5. Most-recent swing resistance (original fallback)
                if target_price == min_target_price and swing_resistance:
                    _try_target(swing_resistance, "SwingResist")

                # Apply regime multiplier to position size
                regime_adjusted_pct = round(kelly_pct * regime_sizing, 2)

                metrics[ticker] = {
                    "atr": round(atr, 4),
                    "stop_loss_price": stop_loss_price,
                    "stop_loss_pct": round(stop_loss_pct, 4),
                    "take_profit_price": target_price,
                    "risk_reward_ratio": target_rr,
                    "position_size_pct": regime_adjusted_pct,
                    "stop_loss_method": stop_method,
                    "target_method": target_method,
                    "min_rr": min_rr,
                    "regime_sizing": regime_sizing,
                    "hv_rank": hv_rank,
                    "pattern_name": pat_name,
                    "pattern_strength": pat_strength,
                }

            except Exception as e:
                logger.warning("Risk calculation failed", ticker=ticker, error=str(e))
                continue

        logger.info("Risk manager node complete", tickers_processed=len(metrics))
        return {"risk_metrics": metrics, "errors": []}

    except Exception as e:
        logger.error("Risk manager node failed", error=str(e))
        return {"risk_metrics": {}, "errors": [f"risk_manager: {e}"]}

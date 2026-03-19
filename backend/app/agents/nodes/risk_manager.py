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
        return float(tr.tail(period).mean())
    except Exception:
        return 0.0


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

                # ATR-based stop and minimum target
                stop_distance = atr * atr_multiplier
                stop_loss_price = round(current_price - stop_distance, 2)
                # Minimum target = entry + (stop_distance × min_rr)
                min_target_price = round(current_price + stop_distance * min_rr, 2)

                stop_loss_pct = stop_distance / current_price
                avg_win = stop_distance * min_rr
                kelly_pct = kelly_position_size(0.50, avg_win, stop_distance)

                # Pass swing_resistance from technical_scores as the preferred target anchor
                tech = state.get("technical_scores", {}).get(ticker, {})
                swing_resistance = tech.get("swing_resistance")

                # Use swing resistance as target if it gives better R:R than minimum
                if swing_resistance and swing_resistance > current_price:
                    resist_rr = (swing_resistance - current_price) / stop_distance
                    if resist_rr >= min_rr:
                        target_price = round(swing_resistance, 2)
                        target_rr = round(resist_rr, 2)
                    else:
                        # Resistance too close — use minimum R:R target
                        target_price = min_target_price
                        target_rr = min_rr
                else:
                    target_price = min_target_price
                    target_rr = min_rr

                # Apply regime multiplier to position size
                regime_adjusted_pct = round(kelly_pct * regime_sizing, 2)

                metrics[ticker] = {
                    "atr": round(atr, 4),
                    "stop_loss_price": stop_loss_price,
                    "stop_loss_pct": round(stop_loss_pct, 4),
                    "take_profit_price": target_price,
                    "risk_reward_ratio": target_rr,
                    "position_size_pct": regime_adjusted_pct,
                    "stop_loss_method": f"ATR-{atr_multiplier}x (ATR={atr:.3f})",
                    "min_rr": min_rr,
                    "regime_sizing": regime_sizing,
                }

            except Exception as e:
                logger.warning("Risk calculation failed", ticker=ticker, error=str(e))
                continue

        logger.info("Risk manager node complete", tickers_processed=len(metrics))
        return {"risk_metrics": metrics, "errors": []}

    except Exception as e:
        logger.error("Risk manager node failed", error=str(e))
        return {"risk_metrics": {}, "errors": [f"risk_manager: {e}"]}

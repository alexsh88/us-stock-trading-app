import time
import structlog
import yfinance as yf
import pandas as pd
from typing import Any
from datetime import date, timedelta

logger = structlog.get_logger()

# ~100 liquid US stocks across all major sectors + SPY benchmark
CANDIDATE_UNIVERSE = [
    # Technology (mega-cap + mid-cap)
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD",
    "AVGO", "ORCL", "CRM", "ADBE", "QCOM", "TXN", "INTC", "MU",
    "AMAT", "LRCX", "KLAC", "MRVL", "PANW", "SNPS", "CDNS", "NOW",
    "SNOW", "PLTR", "COIN", "RBLX", "UBER", "LYFT",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "AXP",
    "V", "MA", "PYPL", "SQ", "SPGI", "MCO",
    # Healthcare / Biotech
    "UNH", "LLY", "JNJ", "ABBV", "MRK", "PFE", "TMO", "ABT",
    "AMGN", "GILD", "BIIB", "MRNA", "DXCM", "ISRG", "IDXX",
    # Consumer Discretionary
    "HD", "LOW", "COST", "WMT", "TGT", "AMZN", "MCD", "SBUX",
    "NKE", "LULU", "DECK", "BURL", "TJX", "ROST",
    # Communication / Media
    "NFLX", "DIS", "CMCSA", "CHTR", "SPOT", "TTD", "ROKU",
    # Energy
    "XOM", "CVX", "COP", "EOG", "SLB", "MPC", "VLO", "PSX",
    # Industrials / Defense
    "CAT", "DE", "BA", "GE", "HON", "RTX", "LMT", "NOC", "GD",
    "UPS", "FDX", "CSX", "NSC",
    # Materials / Commodities
    "FCX", "NEM", "ALB", "MP",
    # Real Estate / REITs
    "AMT", "PLD", "EQIX",
    # SPY benchmark (must stay last)
    "SPY",
]


def _get_market_regime() -> dict:
    """Compute VIX level and SPY trend to determine overall market regime.
    Returns regime dict with sizing_multiplier, entry_allowed, and details.
    """
    try:
        vix_data = yf.download("^VIX", period="5d", interval="1d", progress=False, auto_adjust=True)
        spy_data = yf.download("SPY", period="1y", interval="1d", progress=False, auto_adjust=True)

        vix_series = vix_data["Close"].dropna().squeeze()
        vix_level = float(vix_series.iloc[-1]) if not vix_data.empty else 20.0

        spy_close = spy_data["Close"].dropna().squeeze()
        spy_last = float(spy_close.iloc[-1]) if not spy_close.empty else 0
        spy_ma200 = float(spy_close.tail(200).mean()) if len(spy_close) >= 200 else spy_last
        spy_ma50 = float(spy_close.tail(50).mean()) if len(spy_close) >= 50 else spy_last
        spy_daily_change = float((spy_close.iloc[-1] - spy_close.iloc[-2]) / spy_close.iloc[-2]) if len(spy_close) >= 2 else 0.0

        # Determine regime and sizing multiplier
        if spy_last < spy_ma200 * 0.97 or vix_level > 35:
            regime = "bear"
            sizing_multiplier = 0.0
            entry_allowed = False
            reason = f"Bear market (SPY {spy_last:.0f} vs MA200 {spy_ma200:.0f}) or extreme VIX={vix_level:.1f}"
        else:
            regime = "bull"
            sizing_multiplier = 1.0
            entry_allowed = True
            reason = "Normal regime"

            if spy_last < spy_ma50:
                sizing_multiplier *= 0.75
                reason = f"SPY below 50-day MA ({spy_last:.0f} < {spy_ma50:.0f})"
            if vix_level > 30:
                sizing_multiplier *= 0.5
                reason += f"; high VIX={vix_level:.1f}"
            elif vix_level > 25:
                sizing_multiplier *= 0.75
                reason += f"; elevated VIX={vix_level:.1f}"
            if spy_daily_change < -0.02:
                sizing_multiplier *= 0.5
                reason += f"; SPY down {spy_daily_change*100:.1f}% today"

        logger.info("Market regime", regime=regime, vix=round(vix_level, 1),
                    spy_vs_ma200=round((spy_last / spy_ma200 - 1) * 100, 2),
                    sizing_multiplier=round(sizing_multiplier, 2))
        return {
            "regime": regime,
            "sizing_multiplier": round(sizing_multiplier, 3),
            "entry_allowed": entry_allowed,
            "vix": round(vix_level, 2),
            "spy_vs_ma200_pct": round((spy_last / spy_ma200 - 1) * 100, 2),
            "reason": reason,
        }
    except Exception as e:
        logger.warning("Regime detection failed, assuming normal", error=str(e))
        return {"regime": "unknown", "sizing_multiplier": 1.0, "entry_allowed": True, "vix": 20.0, "reason": "detection failed"}


def _get_earnings_dates(tickers: list[str]) -> dict[str, date | None]:
    """Fetch next earnings date for each ticker. Returns {ticker: date or None}."""
    earnings_dates: dict[str, date | None] = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            cal = t.calendar
            if cal is not None and "Earnings Date" in cal:
                ed = cal["Earnings Date"]
                if hasattr(ed, "__iter__") and not isinstance(ed, str):
                    ed = list(ed)[0] if ed else None
                if ed is not None:
                    earnings_dates[ticker] = pd.Timestamp(ed).date()
                    continue
        except Exception:
            pass
        earnings_dates[ticker] = None
    return earnings_dates


def screener_node(state: dict[str, Any]) -> dict[str, Any]:
    # If tickers already set (custom watchlist), skip screening entirely
    if state.get("candidate_tickers"):
        tickers = state["candidate_tickers"]
        logger.info("Screener skipped — using custom watchlist", tickers=len(tickers))
        # Still run regime detection so downstream nodes have sizing guidance
        regime = _get_market_regime()
        return {"candidate_tickers": tickers, "market_regime": regime, "errors": []}

    mode = state.get("mode", "swing")
    logger.info("Screener node running", mode=mode)

    # Mode-specific filter thresholds
    # Intraday needs higher volatility and liquidity — want fast-moving, heavily traded stocks
    min_atr_pct   = 0.03 if mode == "intraday" else 0.02   # 3% vs 2%
    min_avg_vol   = 1_000_000 if mode == "intraday" else 500_000  # 1M vs 500k

    # ── Market regime detection ──────────────────────────────────────────────────
    regime = _get_market_regime()
    if not regime["entry_allowed"]:
        logger.warning("Market regime blocks entries", reason=regime["reason"])
        # Still return candidates but with regime info — synthesizer will use sizing_multiplier=0
        fallback = [t for t in CANDIDATE_UNIVERSE if t != "SPY"]
        return {"candidate_tickers": fallback[:20], "market_regime": regime,
                "errors": [f"regime_blocked: {regime['reason']}"]}

    try:
        all_tickers = CANDIDATE_UNIVERSE  # includes SPY
        # Batch download all tickers in one request — much faster, fewer rate-limit hits
        all_data = yf.download(
            all_tickers,
            period="1mo",
            interval="1d",
            progress=False,
            auto_adjust=True,
            group_by="ticker",
        )

        # Extract SPY for RS benchmark
        try:
            spy_close = all_data["SPY"]["Close"] if "SPY" in all_data.columns.get_level_values(0) else pd.Series()
        except Exception:
            spy_close = pd.Series()

        spy_return = float((spy_close.iloc[-1] / spy_close.iloc[0]) - 1) if not spy_close.empty and len(spy_close) > 1 else None

        candidates = [t for t in CANDIDATE_UNIVERSE if t != "SPY"]

        # --- First pass: collect data for all tickers passing price/volume/ATR filters ---
        ticker_data: dict[str, dict] = {}

        for ticker in candidates:
            try:
                try:
                    hist = all_data[ticker] if ticker in all_data.columns.get_level_values(0) else pd.DataFrame()
                except Exception:
                    hist = pd.DataFrame()

                if hist.empty or len(hist) < 10:
                    logger.debug("Skipping — no data", ticker=ticker)
                    continue

                close = hist["Close"].dropna()
                volume = hist["Volume"].dropna()
                high = hist["High"].dropna()
                low = hist["Low"].dropna()

                if close.empty:
                    continue

                current_price = float(close.iloc[-1])
                avg_volume = float(volume.mean())

                # Filter: price $5–$2000
                if not (5 <= current_price <= 2000):
                    continue

                # Filter: avg volume (mode-dependent)
                if avg_volume < min_avg_vol:
                    continue

                # Filter: ATR% (mode-dependent)
                prev_close = close.shift(1)
                tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
                atr = float(tr.tail(14).mean())
                atr_pct = atr / current_price
                if atr_pct < min_atr_pct:
                    continue

                # Compute RS vs SPY for this ticker
                ticker_return = float((close.iloc[-1] / close.iloc[0]) - 1) if len(close) > 1 else 0.0
                rs_vs_spy = (ticker_return - spy_return) if spy_return is not None else ticker_return

                # Filter: 52-week high proximity — only stocks within 15% of 52-week high
                # (George & Hwang 2004: stocks near 52-week high have stronger momentum continuation)
                try:
                    hist_52w = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
                    high_52w = float(hist_52w["High"].max()) if not hist_52w.empty else current_price
                except Exception:
                    high_52w = current_price
                price_vs_52wk = current_price / high_52w
                if price_vs_52wk < 0.82:  # more than 18% below 52-week high
                    logger.debug("Skipping — too far from 52-week high", ticker=ticker,
                                 price_vs_52wk=round(price_vs_52wk, 3))
                    continue

                ticker_data[ticker] = {
                    "price": current_price,
                    "atr_pct": atr_pct,
                    "rs_vs_spy": rs_vs_spy,
                    "price_vs_52wk": price_vs_52wk,
                }

            except Exception as e:
                logger.warning("Screener error", ticker=ticker, error=str(e))
                continue

        if not ticker_data:
            logger.warning("Screener got no data from yfinance (rate-limited?) — passing full universe as fallback")
            fallback = [t for t in CANDIDATE_UNIVERSE if t != "SPY"]
            return {"candidate_tickers": fallback, "market_regime": regime,
                    "errors": ["screener: yfinance rate-limited, using fallback universe"]}

        # ── Earnings blackout filter (swing mode only) ──────────────────────────
        # Block entries within 3 trading days before earnings (binary event risk)
        # Research: Chan, Jegadeesh & Lakonishok (1996); momentum strategies degrade near earnings
        if mode == "swing":
            earnings_map = _get_earnings_dates(list(ticker_data.keys()))
            today = date.today()
            blackout_days = 3
            for ticker in list(ticker_data.keys()):
                ed = earnings_map.get(ticker)
                if ed is not None:
                    days_to_earnings = (ed - today).days
                    if 0 < days_to_earnings <= blackout_days:
                        logger.info("Earnings blackout — removing from candidates",
                                    ticker=ticker, earnings_date=str(ed), days_away=days_to_earnings)
                        del ticker_data[ticker]

        # --- Second pass: RS Rank filter — keep top 80th percentile ---
        # This implements the Jegadeesh-Titman momentum factor: only analyse stocks
        # with RS rank >= 80th percentile within the passing universe.
        rs_series = pd.Series({t: d["rs_vs_spy"] for t, d in ticker_data.items()})
        rs_threshold = rs_series.quantile(0.80)

        passed = []
        for ticker, data in ticker_data.items():
            if data["rs_vs_spy"] >= rs_threshold:
                passed.append(ticker)
                logger.info(
                    "Ticker passed",
                    ticker=ticker,
                    price=data["price"],
                    atr_pct=round(data["atr_pct"], 3),
                    rs_vs_spy=round(data["rs_vs_spy"], 4),
                )
            else:
                logger.debug(
                    "Ticker failed RS rank filter",
                    ticker=ticker,
                    rs_vs_spy=round(data["rs_vs_spy"], 4),
                    threshold=round(rs_threshold, 4),
                )

        if passed:
            logger.info("Screener complete", candidates=len(passed), rs_threshold=round(rs_threshold, 4),
                        regime=regime["regime"], sizing_multiplier=regime["sizing_multiplier"])
            return {"candidate_tickers": passed[:50], "market_regime": regime, "errors": []}

        # RS threshold too strict — fall back to all tickers that passed price/volume/ATR
        logger.warning("RS rank filter removed all candidates — falling back to all price/volume/ATR passers")
        fallback = list(ticker_data.keys())
        return {"candidate_tickers": fallback[:50], "market_regime": regime,
                "errors": ["screener: RS rank fallback — threshold too strict"]}

    except Exception as e:
        logger.error("Screener node failed", error=str(e))
        fallback = [t for t in CANDIDATE_UNIVERSE if t != "SPY"]
        return {"candidate_tickers": fallback, "market_regime": regime if "regime" in dir() else {"sizing_multiplier": 1.0},
                "errors": [f"screener: {e} — using fallback universe"]}

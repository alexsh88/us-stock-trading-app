import structlog
from typing import Any

from app.agents.cache_utils import get_factor_weights

logger = structlog.get_logger()


def _fetch_historical_context(ticker: str, state: dict[str, Any]) -> str:
    """
    Retrieve top-5 semantically similar past headlines with their T+5 outcomes.
    Returns a formatted string to append to the ticker block, or "" if unavailable.
    """
    try:
        headlines = state.get("news_headlines", {}).get(ticker, [])
        if not headlines:
            return ""
        from app.tasks.embedding_tasks import fetch_similar_headlines
        past = fetch_similar_headlines(ticker, headlines, limit=5)
        if not past:
            return ""
        lines = ["Past similar headlines (T+5 outcomes):"]
        for p in past:
            ret = f"{p['return_5d']:+.1f}%" if p["return_5d"] is not None else "N/A"
            hit = "TP✓" if p.get("tp_hit") else ("SL✗" if p.get("sl_hit") else "—")
            lines.append(f"  [{p['date']} {p['ticker']}] {p['headline'][:80]} → {ret} {hit}")
        return "\n" + "\n".join(lines)
    except Exception as e:
        logger.debug("Historical context fetch failed", ticker=ticker, error=str(e))
        return ""

SYNTHESIZER_SYSTEM = """You are an expert stock trading analyst. Analyze multiple stocks and return concise trading decisions.
Be rigorous, risk-aware, and focus on high-probability setups only.
ADX regime context: TRENDING(>25) = favour momentum/breakout setups; CHOPPY(<20) = favour mean-reversion, be more selective.
MTF_aligned=YES (price above 20-week SMA) is a strong additional confirmation — prefer these setups, especially in trending regimes.

Confidence score meaning (use the FULL range):
0.90-1.00: All 4 factor scores ≥ 0.75, strong technical setup (ADX trending, MTF aligned, breakout confirmed), no near-term risks.
0.75-0.89: At least 3/4 factor scores ≥ 0.70, clear setup with only minor risks.
0.60-0.74: Mixed signals or marginal setup — only BUY if R:R is compelling.
Below 0.60: SKIP regardless of setup.

For any stock you would rate BUY with confidence 0.60-0.80, explicitly state the strongest argument AGAINST taking this trade before finalizing confidence. If the bear case is strong, reduce confidence or switch to SKIP.
Gap context: breakaway gap (>1.5% from base, high volume) = continuation signal, only 35% fill → boost confidence. exhaustion gap (>1.5% after extended trend, high volume) = 75% fill risk → penalise -0.10 confidence. common gap = neutral. none = no gap."""

SYNTHESIZER_PROMPT = """Analyze these {count} stocks for {mode} trading and decide which to trade.

{mode_guidance}


{ticker_blocks}

For each stock, respond with one line per stock:
TICKER|DECISION|CONFIDENCE|ENTRY|STOP|TARGET|RISKS|REASONING

Rules:
- DECISION: BUY, SELL, or SKIP
- CONFIDENCE: 0.00-1.00
- ENTRY: current price (use the price shown)
- STOP: use the Stop price provided in Risk section
- TARGET: use Resistance level if it gives R:R >= min required, otherwise use MinTarget. NEVER set a target that gives R:R < min required — SKIP instead.
- RISKS: max 2 risks separated by semicolons
- REASONING: max 1 sentence
- Only BUY/SELL if confidence >= 0.60 AND R:R >= min required
- SKIP if R:R would be below minimum or setup is weak

Example line:
AAPL|BUY|0.75|185.50|179.25|198.75|earnings risk; sector rotation|Strong momentum with improving fundamentals"""


def _build_ticker_block(ticker: str, state: dict[str, Any], current_price: float) -> str:
    tech = state.get("technical_scores", {}).get(ticker, {})
    fund = state.get("fundamental_scores", {}).get(ticker, {})
    sent = state.get("sentiment_scores", {}).get(ticker, {})
    cat = state.get("catalyst_scores", {}).get(ticker, {})
    risk = state.get("risk_metrics", {}).get(ticker, {})

    regime = tech.get("regime", "unknown")
    mtf = "YES" if tech.get("mtf_aligned") else "NO"
    adx = tech.get("adx", 0.0)

    stop  = risk.get("stop_loss_price")
    target = risk.get("take_profit_price")
    rr     = risk.get("risk_reward_ratio")
    min_rr = risk.get("min_rr", 2.0)
    resist = tech.get("swing_resistance")
    support = tech.get("swing_support")

    stop_str    = f"${stop:.2f}"    if stop    else "calc"
    target_str  = f"${target:.2f}" if target  else "calc"
    rr_str      = f"{rr:.1f}x"    if rr      else "?"
    resist_str  = f"${resist:.2f}" if resist  else "none"
    support_str = f"${support:.2f}" if support else "none"

    # Extended targets: Fibonacci extensions and weekly pivots
    fib127    = tech.get("fib_ext_127")
    fib162    = tech.get("fib_ext_162")
    weekly_r1 = tech.get("weekly_r1")
    weekly_r2 = tech.get("weekly_r2")
    hv_rank   = tech.get("hv_rank")
    target_method = risk.get("target_method", "")
    ext_parts = []
    if fib127:   ext_parts.append(f"Fib127=${fib127:.2f}")
    if fib162:   ext_parts.append(f"Fib162=${fib162:.2f}")
    if weekly_r1: ext_parts.append(f"WklyR1=${weekly_r1:.2f}")
    if weekly_r2: ext_parts.append(f"WklyR2=${weekly_r2:.2f}")
    ext_str = " | ".join(ext_parts) if ext_parts else "none"
    hv_str  = f"{hv_rank:.0f}th-pct" if hv_rank is not None else "n/a"

    # Pattern line
    pat_name     = tech.get("pattern_name")
    pat_strength = tech.get("pattern_strength", 0.0)
    pat_pivot    = tech.get("pattern_pivot")
    pat_details  = tech.get("pattern_details", "")
    if pat_name:
        pivot_str = f", pivot=${pat_pivot:.2f}" if pat_pivot else ""
        pattern_line = f"\nPattern: {pat_name}(strength={pat_strength:.2f}{pivot_str}) | {pat_details[:120]}"
    else:
        pattern_line = "\nPattern: none"

    hist_context = _fetch_historical_context(ticker, state)

    gap_type = tech.get("gap_type", "none")
    gap_pct  = tech.get("gap_pct", 0.0)
    gap_str  = f"{gap_type}({gap_pct:+.1f}%)" if gap_type != "none" else "none"

    return (
        f"=== {ticker} @ ${current_price:.2f} ===\n"
        f"Technical: {tech.get('score', 0.5):.2f} | ADX={adx:.1f}({regime}) MTF={mtf} Gap={gap_str} | {tech.get('reasoning', 'N/A')[:120]}\n"
        f"Fundamental: {fund.get('score', 0.5):.2f} | {fund.get('reasoning', 'N/A')[:120]}\n"
        f"Sentiment: {sent.get('score', 0.5):.2f} | {sent.get('reasoning', 'N/A')[:80]}\n"
        f"Catalyst: {cat.get('score', 0.5):.2f} | {cat.get('reasoning', 'N/A')[:80]}\n"
        f"Risk: Stop={stop_str}({risk.get('stop_loss_method','ATR-2x')}) | Target={target_str}({target_method}) R:R={rr_str} | Size={risk.get('position_size_pct', 2.0):.1f}% | HV={hv_str}\n"
        f"Levels: Resist={resist_str} | Support={support_str} | ExtTargets={ext_str} | Min R:R={min_rr:.1f}x"
        f"{pattern_line}"
        f"{hist_context}"
    )


def _parse_batch_response(text: str, state: dict[str, Any], prices: dict[str, float]) -> list[dict[str, Any]]:
    import re

    signals = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        try:
            ticker = parts[0].strip().upper()
            decision = parts[1].strip().upper()
            if decision not in ("BUY", "SELL"):
                continue

            confidence = float(re.findall(r"\d+\.?\d*", parts[2])[0])
            if confidence < 0.60:
                continue

            current_price = prices.get(ticker, 100.0)

            def parse_price(s: str, default: float) -> float:
                nums = re.findall(r"\d+\.?\d*", s)
                return float(nums[0]) if nums else default

            risk_meta = state.get("risk_metrics", {}).get(ticker, {})
            entry  = parse_price(parts[3], current_price)
            stop   = parse_price(parts[4], risk_meta.get("stop_loss_price", current_price * 0.95))
            target = parse_price(parts[5], risk_meta.get("take_profit_price", current_price * 1.10))

            if entry <= stop:
                continue  # invalid stop

            rr = round((target - entry) / (entry - stop), 2)
            min_rr = risk_meta.get("min_rr", 2.0)

            # Hard floor: reject signals that don't meet minimum R:R
            if rr < min_rr:
                # Try using the pre-computed minimum target instead
                fallback_target = risk_meta.get("take_profit_price")
                if fallback_target:
                    target = fallback_target
                    rr = round((target - entry) / (entry - stop), 2)
                if rr < min_rr:
                    logger.debug("Signal rejected: R:R below minimum", ticker=ticker, rr=rr, min_rr=min_rr)
                    continue
            risks = [r.strip() for r in parts[6].split(";") if r.strip()][:2]
            reasoning = parts[7].strip()[:400]

            tech = state.get("technical_scores", {}).get(ticker, {})
            fund = state.get("fundamental_scores", {}).get(ticker, {})
            sent = state.get("sentiment_scores", {}).get(ticker, {})
            cat = state.get("catalyst_scores", {}).get(ticker, {})
            risk = state.get("risk_metrics", {}).get(ticker, {})

            # Serialise all detected patterns for DB storage
            from app.agents.patterns.detector import pattern_to_dict
            pat_results = tech.get("_pattern_results", {})
            detected_patterns = {
                "best_bullish": pattern_to_dict(pat_results["best_bullish"]) if pat_results.get("best_bullish") else None,
                "best_bearish": pattern_to_dict(pat_results["best_bearish"]) if pat_results.get("best_bearish") else None,
                "all_bullish": [pattern_to_dict(r) for r in pat_results.get("all_bullish", [])],
                "all_bearish": [pattern_to_dict(r) for r in pat_results.get("all_bearish", [])],
            }

            signals.append({
                "ticker": ticker,
                "decision": decision,
                "confidence_score": round(min(max(confidence, 0.0), 1.0), 4),
                "trading_mode": state.get("mode", "swing"),
                "entry_price": round(entry, 2),
                "stop_loss_price": round(stop, 2),
                "stop_loss_method": risk.get("stop_loss_method", "ATR-2x"),
                "target_method": risk.get("target_method", "min_rr_floor"),
                "take_profit_price": round(target, 2),
                "take_profit_price_2": risk.get("take_profit_price_2"),
                "risk_reward_ratio": round(rr, 2),
                "position_size_pct": risk.get("position_size_pct", 2.0),
                "technical_score": tech.get("score", 0.5),
                "fundamental_score": fund.get("score", 0.5),
                "sentiment_score": sent.get("score", 0.5),
                "catalyst_score": cat.get("score", 0.5),
                "key_risks": risks,
                "reasoning": reasoning,
                "detected_patterns": detected_patterns,
            })
        except Exception:
            continue

    return signals


def synthesizer_node(state: dict[str, Any]) -> dict[str, Any]:
    tickers = state.get("candidate_tickers", [])
    top_n = state.get("top_n", 5)
    mode = state.get("mode", "swing")

    if not tickers:
        return {"trade_signals": [], "errors": []}

    # Short-circuit when market regime blocks all entries (bear market gate)
    regime = state.get("market_regime", {})
    if not regime.get("entry_allowed", True):
        reason = regime.get("reason", "regime gate")
        logger.info("Synthesizer skipped — regime blocks entries", reason=reason)
        return {"trade_signals": [], "errors": [f"regime_blocked: {reason}"]}

    try:
        import yfinance as yf
        from app.config import get_settings, has_anthropic_key

        # IC-weighted composite score for ranking
        # Weights are updated nightly by the backtest task based on Spearman IC.
        # Falls back to static defaults (35/25/20/20) when no history exists.
        weights = get_factor_weights(mode)
        w_tech = weights.get("technical", 0.35)
        w_fund = weights.get("fundamental", 0.25)
        w_sent = weights.get("sentiment", 0.20)
        w_cat  = weights.get("catalyst",   0.20)
        logger.info("Synthesizer using factor weights", weights=weights)

        def composite_score(t: str) -> float:
            tech = state.get("technical_scores", {}).get(t, {}).get("score", 0.0)
            fund = state.get("fundamental_scores", {}).get(t, {}).get("score", 0.0)
            sent = state.get("sentiment_scores", {}).get(t, {}).get("score", 0.0)
            cat = state.get("catalyst_scores", {}).get(t, {}).get("score", 0.0)
            return tech * w_tech + fund * w_fund + sent * w_sent + cat * w_cat

        # Pre-filter: rank by composite score and send the best candidates to the LLM.
        # For custom watchlists the user hand-picked every ticker, so raise the ceiling
        # significantly (up to 40) to avoid silently discarding most of their list.
        # For screener mode keep the tighter cap (top_n * 2, max 15) to control cost.
        if state.get("watchlist_active"):
            pre_filter_cap = min(len(tickers), 40)
        else:
            pre_filter_cap = min(top_n * 2, 15)
        top_candidates = sorted(tickers, key=composite_score, reverse=True)[:pre_filter_cap]

        # Batch-fetch prices for all candidates in one call — with fallback
        prices: dict[str, float] = {}
        try:
            from app.services.data_resilience import fetch_ohlcv_with_fallback
            hist_all, _ = fetch_ohlcv_with_fallback(top_candidates, period="5d")
            if hist_all is not None:
                for t in top_candidates:
                    try:
                        close = hist_all[t]["Close"].dropna()
                        prices[t] = float(close.iloc[-1].item()) if not close.empty else 100.0
                    except Exception:
                        prices[t] = 100.0
        except Exception:
            prices = {t: 100.0 for t in top_candidates}

        llm_ok = False
        signals = []
        if has_anthropic_key():
            try:
                from anthropic import Anthropic
                settings = get_settings()
                client = Anthropic(api_key=settings.anthropic_api_key)

                ticker_blocks = "\n\n".join(
                    _build_ticker_block(t, state, prices.get(t, 100.0))
                    for t in top_candidates
                )
                if mode == "intraday":
                    mode_guidance = (
                        "INTRADAY rules: favour stocks above VWAP, high relative volume (>1.5x), "
                        "RSI 50-70, breakout score 2-3/3. Stop = ATR-1.5x. "
                        "MTF alignment is a bonus, NOT required. Avoid stocks with low volume or below VWAP."
                    )
                else:
                    mode_guidance = (
                        "SWING rules: favour MTF_aligned=YES (weekly uptrend), ADX trending(>25), "
                        "BB squeeze released, breakout with volume. Stop = ATR-2x. "
                        "Penalise MTF misaligned stocks unless other factors are overwhelmingly strong."
                    )
                prompt = SYNTHESIZER_PROMPT.format(
                    count=len(top_candidates),
                    mode=mode,
                    mode_guidance=mode_guidance,
                    ticker_blocks=ticker_blocks,
                )

                # Dynamic max_tokens: ~120 tokens per candidate output line + buffer
                max_tokens = min(len(top_candidates) * 120 + 256, 8192)
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=max_tokens,
                    system=[{"type": "text", "text": SYNTHESIZER_SYSTEM,
                              "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": prompt}],
                )
                signals = _parse_batch_response(response.content[0].text, state, prices)
                llm_ok = True
            except Exception as e:
                logger.warning("Synthesizer LLM call failed, falling back to rule-based", error=str(e))

        if not llm_ok:
            # Rule-based fallback
            signals = []
            for ticker in top_candidates:
                comp = composite_score(ticker)
                if comp < 0.6:
                    continue
                current_price = prices.get(ticker, 100.0)
                risk = state.get("risk_metrics", {}).get(ticker, {})
                tech = state.get("technical_scores", {}).get(ticker, {})
                fund = state.get("fundamental_scores", {}).get(ticker, {})
                sent = state.get("sentiment_scores", {}).get(ticker, {})
                cat = state.get("catalyst_scores", {}).get(ticker, {})
                # Use pre-computed stop/target from risk manager
                stop_price  = risk.get("stop_loss_price",  round(current_price * 0.95, 2))
                target_price = risk.get("take_profit_price", round(current_price * 1.10, 2))
                rr = risk.get("risk_reward_ratio", 2.0)
                from app.agents.patterns.detector import pattern_to_dict
                pat_results = tech.get("_pattern_results", {})
                detected_patterns = {
                    "best_bullish": pattern_to_dict(pat_results["best_bullish"]) if pat_results.get("best_bullish") else None,
                    "best_bearish": pattern_to_dict(pat_results["best_bearish"]) if pat_results.get("best_bearish") else None,
                    "all_bullish": [pattern_to_dict(r) for r in pat_results.get("all_bullish", [])],
                    "all_bearish": [pattern_to_dict(r) for r in pat_results.get("all_bearish", [])],
                }
                signals.append({
                    "ticker": ticker,
                    "decision": "BUY",
                    "confidence_score": round(comp, 4),
                    "trading_mode": mode,
                    "entry_price": round(current_price, 2),
                    "stop_loss_price": stop_price,
                    "stop_loss_method": risk.get("stop_loss_method", "ATR-2x"),
                    "target_method": risk.get("target_method", "min_rr_floor"),
                    "take_profit_price": target_price,
                    "take_profit_price_2": risk.get("take_profit_price_2"),
                    "risk_reward_ratio": rr,
                    "position_size_pct": risk.get("position_size_pct", 2.0),
                    "technical_score": tech.get("score", 0.5),
                    "fundamental_score": fund.get("score", 0.5),
                    "sentiment_score": sent.get("score", 0.5),
                    "catalyst_score": cat.get("score", 0.5),
                    "key_risks": ["Rule-based fallback — no LLM configured"],
                    "reasoning": f"Composite score: {comp:.2f}. Configure ANTHROPIC_API_KEY for full analysis.",
                    "detected_patterns": detected_patterns,
                })

        # ── Portfolio heat cap: max 15% total risk across all new signals ─────────
        # Risk per signal = (entry - stop) / entry * position_size_pct
        # This prevents taking 5 full-size correlated positions simultaneously
        signals.sort(key=lambda s: s["confidence_score"], reverse=True)
        MAX_HEAT = 0.15  # 15% total portfolio heat
        heat_used = 0.0
        capped_signals = []
        for sig in signals:
            entry = sig.get("entry_price", 0)
            stop = sig.get("stop_loss_price", 0)
            size = sig.get("position_size_pct", 2.0) / 100.0
            if entry > 0 and stop > 0 and entry > stop:
                heat = ((entry - stop) / entry) * size
                if heat_used + heat <= MAX_HEAT:
                    capped_signals.append(sig)
                    heat_used += heat
                else:
                    logger.info("Portfolio heat cap reached — dropping signal",
                                ticker=sig["ticker"], heat_used=round(heat_used, 4), new_heat=round(heat, 4))
            else:
                capped_signals.append(sig)  # can't compute heat, include it

        # ── Sector concentration cap: max 2 signals per sector ETF ──────────────
        # Prevents correlated drawdowns when 3+ stocks from the same sector all move
        # together on a sector-wide shock (e.g. oil inventory surprise, Fed sector rotation).
        from app.agents.nodes.screener import ETF_SECTOR_STOCKS
        ticker_to_sector: dict[str, str] = {
            stock: etf
            for etf, stocks in ETF_SECTOR_STOCKS.items()
            for stock in stocks
        }
        sector_counts: dict[str, int] = {}
        sector_capped: list[dict] = []
        for sig in capped_signals:
            sector = ticker_to_sector.get(sig["ticker"])
            count = sector_counts.get(sector, 0) if sector else 0
            if sector and count >= 2:
                logger.info("Sector concentration cap — dropping signal",
                            ticker=sig["ticker"], sector=sector, sector_count=count)
                continue
            sector_capped.append(sig)
            if sector:
                sector_counts[sector] = count + 1

        top_signals = sector_capped[:top_n]

        logger.info("Synthesizer complete", signals_generated=len(top_signals),
                    heat_used=round(heat_used, 4))
        return {"trade_signals": top_signals, "errors": []}

    except Exception as e:
        logger.error("Synthesizer node failed", error=str(e))
        return {"trade_signals": [], "errors": [f"synthesizer: {e}"]}

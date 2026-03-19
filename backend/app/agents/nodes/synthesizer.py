import structlog
from typing import Any

from app.agents.cache_utils import get_factor_weights

logger = structlog.get_logger()

SYNTHESIZER_SYSTEM = """You are an expert stock trading analyst. Analyze multiple stocks and return concise trading decisions.
Be rigorous, risk-aware, and focus on high-probability setups only.
ADX regime context: TRENDING(>25) = favour momentum/breakout setups; CHOPPY(<20) = favour mean-reversion, be more selective.
MTF_aligned=YES (price above 20-week SMA) is a strong additional confirmation — prefer these setups, especially in trending regimes.

Confidence score meaning (use the FULL range):
0.90-1.00: All 4 factor scores ≥ 0.75, strong technical setup (ADX trending, MTF aligned, breakout confirmed), no near-term risks.
0.75-0.89: At least 3/4 factor scores ≥ 0.70, clear setup with only minor risks.
0.60-0.74: Mixed signals or marginal setup — only BUY if R:R is compelling.
Below 0.60: SKIP regardless of setup.

For any stock you would rate BUY with confidence 0.60-0.80, explicitly state the strongest argument AGAINST taking this trade before finalizing confidence. If the bear case is strong, reduce confidence or switch to SKIP."""

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

    stop_str   = f"${stop:.2f}"   if stop   else "calc"
    target_str = f"${target:.2f}" if target else "calc"
    rr_str     = f"{rr:.1f}x"    if rr     else "?"
    resist_str = f"${resist:.2f}" if resist else "none"
    support_str = f"${support:.2f}" if support else "none"

    return (
        f"=== {ticker} @ ${current_price:.2f} ===\n"
        f"Technical: {tech.get('score', 0.5):.2f} | ADX={adx:.1f}({regime}) MTF={mtf} | {tech.get('reasoning', 'N/A')[:120]}\n"
        f"Fundamental: {fund.get('score', 0.5):.2f} | {fund.get('reasoning', 'N/A')[:120]}\n"
        f"Sentiment: {sent.get('score', 0.5):.2f} | {sent.get('reasoning', 'N/A')[:80]}\n"
        f"Catalyst: {cat.get('score', 0.5):.2f} | {cat.get('reasoning', 'N/A')[:80]}\n"
        f"Risk: Stop={stop_str} | MinTarget={target_str} (R:R={rr_str}) | Size={risk.get('position_size_pct', 2.0):.1f}% | {risk.get('stop_loss_method', 'ATR-2x')}\n"
        f"Levels: Resistance={resist_str} | Support={support_str} | Min R:R required={min_rr:.1f}x"
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

            signals.append({
                "ticker": ticker,
                "decision": decision,
                "confidence_score": round(min(max(confidence, 0.0), 1.0), 4),
                "trading_mode": state.get("mode", "swing"),
                "entry_price": round(entry, 2),
                "stop_loss_price": round(stop, 2),
                "stop_loss_method": risk.get("stop_loss_method", "ATR-2x"),
                "take_profit_price": round(target, 2),
                "risk_reward_ratio": round(rr, 2),
                "position_size_pct": risk.get("position_size_pct", 2.0),
                "technical_score": tech.get("score", 0.5),
                "fundamental_score": fund.get("score", 0.5),
                "sentiment_score": sent.get("score", 0.5),
                "catalyst_score": cat.get("score", 0.5),
                "key_risks": risks,
                "reasoning": reasoning,
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

        # Pre-filter: only send top candidates to the LLM (top_n * 2, max 15)
        top_candidates = sorted(tickers, key=composite_score, reverse=True)[:min(top_n * 2, 15)]

        # Batch-fetch prices for all candidates in one call
        prices: dict[str, float] = {}
        try:
            hist_all = yf.download(
                top_candidates, period="5d", interval="1d",
                progress=False, auto_adjust=True, group_by="ticker"
            )
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
                    system=SYNTHESIZER_SYSTEM,
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
                signals.append({
                    "ticker": ticker,
                    "decision": "BUY",
                    "confidence_score": round(comp, 4),
                    "trading_mode": mode,
                    "entry_price": round(current_price, 2),
                    "stop_loss_price": stop_price,
                    "stop_loss_method": risk.get("stop_loss_method", "ATR-2x"),
                    "take_profit_price": target_price,
                    "risk_reward_ratio": rr,
                    "position_size_pct": risk.get("position_size_pct", 2.0),
                    "technical_score": tech.get("score", 0.5),
                    "fundamental_score": fund.get("score", 0.5),
                    "sentiment_score": sent.get("score", 0.5),
                    "catalyst_score": cat.get("score", 0.5),
                    "key_risks": ["Rule-based fallback — no LLM configured"],
                    "reasoning": f"Composite score: {comp:.2f}. Configure ANTHROPIC_API_KEY for full analysis.",
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

        top_signals = capped_signals[:top_n]

        logger.info("Synthesizer complete", signals_generated=len(top_signals),
                    heat_used=round(heat_used, 4))
        return {"trade_signals": top_signals, "errors": []}

    except Exception as e:
        logger.error("Synthesizer node failed", error=str(e))
        return {"trade_signals": [], "errors": [f"synthesizer: {e}"]}

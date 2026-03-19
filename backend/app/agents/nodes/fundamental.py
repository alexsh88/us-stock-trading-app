import re
import structlog
import yfinance as yf
from typing import Any

logger = structlog.get_logger()

FUNDAMENTAL_SYSTEM = """You are a fundamental analysis expert. Score each stock 0.0-1.0 for investment attractiveness.
EPS_Revision: analyst consensus EPS change over 4 weeks. >+3% = strong buy signal (earnings revision momentum).
<-3% = red flag — analysts cutting estimates ahead of results.
Respond with one line per stock: TICKER|SCORE|REASONING (max 100 chars reasoning).

Examples (use the full 0.0-1.0 range):
NVDA|0.85|High rev growth +120%, expanding margins, strong FCF, low debt, EPS revision +8%
KSS|0.22|Declining revenue -8%, negative FCF, high debt, shrinking margins, EPS revision -12%
MSFT|0.74|Solid rev growth +16%, excellent margins, strong FCF, quality compounder
LLY|0.80|Accelerating rev growth, expanding margins driven by GLP-1, strong pipeline catalysts
HOOD|0.41|Revenue cyclical, improving but dependent on market activity, limited moat"""


def fundamental_node(state: dict[str, Any]) -> dict[str, Any]:
    tickers = state.get("candidate_tickers", [])
    if not tickers:
        return {"fundamental_scores": {}, "errors": []}

    try:
        from app.config import has_anthropic_key

        # Fetch earnings revision data from Finnhub (4-week consensus EPS change)
        from app.config import has_finnhub_key, get_settings
        eps_revisions: dict[str, float | None] = {}
        if has_finnhub_key():
            try:
                import finnhub
                fh = finnhub.Client(api_key=get_settings().finnhub_api_key)
                for ticker in tickers:
                    try:
                        # Get current and 4-week-ago EPS estimates
                        estimates = fh.earnings_estimates(ticker, freq="quarterly")
                        if estimates and estimates.get("data"):
                            rows = estimates["data"]
                            if rows:
                                current = rows[0].get("epsAvg")
                                # Finnhub estimate history — compare revsUp vs revsDown as proxy
                                trend = fh.recommendation_trends(ticker)
                                if trend and current:
                                    # Use epsAvg change as revision proxy when history is available
                                    eps_revisions[ticker] = None  # placeholder
                    except Exception:
                        eps_revisions[ticker] = None
            except Exception:
                pass

        # Collect fundamentals for all tickers
        raw: dict[str, dict] = {}
        for ticker in tickers:
            try:
                info = yf.Ticker(ticker).info or {}
                pe = info.get("trailingPE")
                fpe = info.get("forwardPE")
                rev_growth = info.get("revenueGrowth")
                margin = info.get("profitMargins")
                de = info.get("debtToEquity")
                cr = info.get("currentRatio")
                fcf = info.get("freeCashflow")
                mcap = info.get("marketCap")
                fcf_yield = (fcf / mcap) if (fcf and mcap) else None
                # epsForward change = earnings revision proxy from yfinance
                eps_fwd = info.get("forwardEps")
                eps_trail = info.get("trailingEps")
                eps_revision = eps_revisions.get(ticker)
                raw[ticker] = {
                    "pe": pe, "fpe": fpe, "rev_growth": rev_growth,
                    "margin": margin, "de": de, "cr": cr, "fcf_yield": fcf_yield,
                    "eps_fwd": eps_fwd, "eps_trail": eps_trail,
                    "eps_revision": eps_revision,
                }
            except Exception as e:
                logger.warning("Fundamental data fetch failed", ticker=ticker, error=str(e))

        if not raw:
            return {"fundamental_scores": {}, "errors": ["fundamental: no data"]}

        # --- Redis cache: split tickers into cached vs uncached ---
        from app.agents.cache_utils import score_get, score_set
        cached_scores: dict[str, Any] = {}
        uncached_tickers: list[str] = []
        for t in list(raw.keys()):
            cached = score_get("fundamental", t)
            if cached:
                cached_scores[t] = cached
            else:
                uncached_tickers.append(t)

        if cached_scores:
            logger.info("Fundamental cache hits", count=len(cached_scores), uncached=len(uncached_tickers))

        scores: dict[str, Any] = dict(cached_scores)

        llm_ok = False
        if uncached_tickers and has_anthropic_key():
            try:
                from anthropic import Anthropic
                from app.config import get_settings
                client = Anthropic(api_key=get_settings().anthropic_api_key)

                lines = []
                for ticker in uncached_tickers:
                    d = raw[ticker]
                    rev = f"{d['rev_growth']:.1%}" if d['rev_growth'] else 'N/A'
                    margin = f"{d['margin']:.1%}" if d['margin'] else 'N/A'
                    fcfy = f"{d['fcf_yield']:.1%}" if d['fcf_yield'] else 'N/A'
                    eps_rev_str = (f"{d['eps_revision']:+.1%}" if d.get('eps_revision') is not None
                                   else "N/A")
                    lines.append(
                        f"{ticker}: PE={d['pe']}, FwdPE={d['fpe']}, "
                        f"RevGrowth={rev}, Margin={margin}, "
                        f"D/E={d['de']}, CR={d['cr']}, FCF_Yield={fcfy}, "
                        f"EPS_Revision={eps_rev_str}"
                    )

                from app.agents.llm_utils import call_llm_batched
                raw_response = call_llm_batched(
                    client, lines, FUNDAMENTAL_SYSTEM,
                    prompt_prefix="Score these stocks for fundamental investment attractiveness (0.0=poor, 1.0=excellent):\n\n",
                    tokens_per_line=80,
                )

                for line in raw_response.split("\n"):
                    parts = line.split("|")
                    if len(parts) < 3:
                        continue
                    t = parts[0].strip().upper()
                    if t not in raw:
                        continue
                    try:
                        nums = re.findall(r"0\.\d+|1\.0\b", parts[1])
                        score = float(nums[0]) if nums else 0.5
                        entry = {"score": round(score, 4), "reasoning": parts[2].strip()[:300]}
                        scores[t] = entry
                        score_set("fundamental", t, entry)
                    except Exception:
                        pass
                llm_ok = True
            except Exception as e:
                logger.warning("Fundamental LLM call failed, falling back to rule-based", error=str(e))

        # Rule-based fallback for any ticker still not scored
        for ticker in [t for t in raw if t not in scores]:
            d = raw[ticker]
            score = 0.5
            if d["pe"] and d["pe"] < 25:
                score += 0.1
            if d["rev_growth"] and d["rev_growth"] > 0.1:
                score += 0.1
            if d["margin"] and d["margin"] > 0.1:
                score += 0.1
            entry = {
                "score": round(max(0.0, min(1.0, score)), 4),
                "reasoning": f"Rule-based: PE={d['pe']}, RevGrowth={d['rev_growth']}",
            }
            scores[ticker] = entry
            score_set("fundamental", ticker, entry)

        # Merge raw data into scores
        for ticker, d in raw.items():
            if ticker not in scores:
                scores[ticker] = {"score": 0.5, "reasoning": "no LLM score"}
            scores[ticker].update({
                "pe_ratio": d["pe"],
                "revenue_growth": d["rev_growth"],
                "profit_margin": d["margin"],
                "fcf_yield": d["fcf_yield"],
            })

        logger.info("Fundamental node complete", tickers_analyzed=len(scores))
        return {"fundamental_scores": scores, "errors": []}

    except Exception as e:
        logger.error("Fundamental node failed", error=str(e))
        return {"fundamental_scores": {}, "errors": [f"fundamental: {e}"]}

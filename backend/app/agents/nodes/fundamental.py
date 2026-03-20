import re
import structlog
import yfinance as yf
from typing import Any

logger = structlog.get_logger()

FUNDAMENTAL_SYSTEM = """You are a fundamental analysis expert. Score each stock 0.0-1.0 for investment attractiveness.
SUE (Standardized Unexpected Earnings): (actual_EPS - consensus) / std_dev_of_last_4_surprises.
SUE > +2.0 = strong Post-Earnings Announcement Drift (PEAD) buy signal; < -2.0 = avoid.
EPS_Revision: % of analysts raising vs cutting estimates. +50% = strong consensus upgrade; -50% = widespread cuts.
Respond with one line per stock: TICKER|SCORE|REASONING (max 100 chars reasoning).

Examples (use the full 0.0-1.0 range):
NVDA|0.88|Rev growth +120%, expanding margins, strong FCF, SUE=+3.2 (blowout beat), revisions all up
KSS|0.19|Revenue -8%, negative FCF, high debt, SUE=-2.8 (miss), EPS revisions -60% (wide cuts)
MSFT|0.74|Solid rev growth +16%, excellent margins, strong FCF, SUE=+1.1, slight upward revisions
LLY|0.82|Accelerating rev on GLP-1, expanding margins, SUE=+2.4, pipeline catalysts unpriced
HOOD|0.41|Cyclical revenue, improving but SUE=N/A, no clear revision trend"""


def fundamental_node(state: dict[str, Any]) -> dict[str, Any]:
    tickers = state.get("candidate_tickers", [])
    if not tickers:
        return {"fundamental_scores": {}, "errors": []}

    try:
        from app.config import has_anthropic_key

        # Fetch SUE (Standardized Unexpected Earnings) + revision direction from Finnhub
        from app.config import has_finnhub_key, get_settings
        sue_data: dict[str, dict] = {}  # {ticker: {sue, eps_revision_pct}}
        if has_finnhub_key():
            try:
                import finnhub
                import statistics
                fh = finnhub.Client(api_key=get_settings().finnhub_api_key)
                for ticker in tickers:
                    result: dict = {"sue": None, "eps_revision_pct": None}
                    try:
                        # SUE = (actual - estimate) / std_dev_of_last_4_surprises
                        earnings = fh.company_earnings(ticker, limit=5)
                        if earnings and len(earnings) >= 1:
                            latest = earnings[0]
                            actual = latest.get("actual")
                            estimate = latest.get("estimate")
                            if actual is not None and estimate is not None:
                                surprises = [
                                    e["actual"] - e["estimate"]
                                    for e in earnings[:4]
                                    if e.get("actual") is not None and e.get("estimate") is not None
                                ]
                                if len(surprises) >= 2:
                                    std = statistics.stdev(surprises)
                                    result["sue"] = round((actual - estimate) / std, 2) if std > 0 else None
                                elif surprises:
                                    # fallback: raw surprise % / 10 as proxy
                                    sp = latest.get("surprisePercent")
                                    result["sue"] = round(sp / 10.0, 2) if sp is not None else None

                        # EPS revision direction: revsUp vs revsDown from consensus estimates
                        estimates = fh.earnings_estimates(ticker, freq="quarterly")
                        if estimates and estimates.get("data"):
                            row = estimates["data"][0]
                            revs_up = row.get("revsUp", 0) or 0
                            revs_down = row.get("revsDown", 0) or 0
                            total = revs_up + revs_down
                            if total > 0:
                                result["eps_revision_pct"] = round((revs_up - revs_down) / total * 100, 1)
                    except Exception:
                        pass
                    sue_data[ticker] = result
            except Exception:
                pass

        # Collect fundamentals — try IBKR first, fill gaps with yfinance
        from app.services.ibkr_fundamentals_service import fetch_ibkr_fundamentals
        ibkr_data = fetch_ibkr_fundamentals(tickers)
        using_ibkr = bool(ibkr_data)
        if using_ibkr:
            logger.info("Fundamental node using IBKR data",
                        tickers=len(ibkr_data), total=len(tickers))

        raw: dict[str, dict] = {}
        for ticker in tickers:
            try:
                ibkr = ibkr_data.get(ticker)

                if ibkr is not None:
                    # IBKR provided base metrics; fill fpe + fcf_yield from yfinance
                    pe         = ibkr["pe"]
                    rev_growth = ibkr["rev_growth"]
                    margin     = ibkr["margin"]
                    de         = ibkr["de"]
                    cr         = ibkr["cr"]
                    # fpe and fcf_yield not in ReportSnapshot — fetch from yfinance
                    try:
                        info = yf.Ticker(ticker).info or {}
                        fpe  = info.get("forwardPE")
                        fcf  = info.get("freeCashflow")
                        mcap = ibkr["mcap"] or info.get("marketCap")
                        fcf_yield = (fcf / mcap) if (fcf and mcap) else None
                    except Exception:
                        fpe, fcf_yield = None, None
                else:
                    # IBKR unavailable — full yfinance fallback
                    info = yf.Ticker(ticker).info or {}
                    pe         = info.get("trailingPE")
                    fpe        = info.get("forwardPE")
                    rev_growth = info.get("revenueGrowth")
                    margin     = info.get("profitMargins")
                    de         = info.get("debtToEquity")
                    cr         = info.get("currentRatio")
                    fcf        = info.get("freeCashflow")
                    mcap       = info.get("marketCap")
                    fcf_yield  = (fcf / mcap) if (fcf and mcap) else None

                sue = sue_data.get(ticker, {})
                raw[ticker] = {
                    "pe": pe, "fpe": fpe, "rev_growth": rev_growth,
                    "margin": margin, "de": de, "cr": cr, "fcf_yield": fcf_yield,
                    "sue": sue.get("sue"),
                    "eps_revision_pct": sue.get("eps_revision_pct"),
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
                    sue_str = f"{d['sue']:+.1f}" if d.get("sue") is not None else "N/A"
                    rev_pct = f"{d['eps_revision_pct']:+.0f}%" if d.get("eps_revision_pct") is not None else "N/A"
                    lines.append(
                        f"{ticker}: PE={d['pe']}, FwdPE={d['fpe']}, "
                        f"RevGrowth={rev}, Margin={margin}, "
                        f"D/E={d['de']}, CR={d['cr']}, FCF_Yield={fcfy}, "
                        f"SUE={sue_str}, EPS_Revision={rev_pct}"
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
            if d.get("sue") is not None and d["sue"] > 2.0:
                score += 0.1
            entry = {
                "score": round(max(0.0, min(1.0, score)), 4),
                "reasoning": f"Rule-based: PE={d['pe']}, RevGrowth={d['rev_growth']}, SUE={d.get('sue')}",
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
                "sue": d.get("sue"),
                "eps_revision_pct": d.get("eps_revision_pct"),
            })

        logger.info("Fundamental node complete", tickers_analyzed=len(scores))
        return {"fundamental_scores": scores, "errors": []}

    except Exception as e:
        logger.error("Fundamental node failed", error=str(e))
        return {"fundamental_scores": {}, "errors": [f"fundamental: {e}"]}

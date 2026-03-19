import re
import time
import structlog
import httpx
import yfinance as yf
from datetime import datetime, timedelta
from typing import Any

logger = structlog.get_logger()

CATALYST_SYSTEM = """You are a catalyst analyst. Score each stock 0.0-1.0 for near-term catalyst strength.
8-K filings = material events (earnings beats, product launches, M&A). Form 4 = insider buying/selling.
Note: Only insider PURCHASES (not options exercises) are bullish. Director selling = ignore; CEO buying = strong signal.
NegativeEvent8K=YES means an auditor change (item 4.01) or goodwill impairment (item 2.06) was filed — score < 0.25.
Activist13D=YES means a >5% activist stake was disclosed — strongly bullish (price target pressure, strategic review).
PutCallRatio: >1.5 = bearish options sentiment (reduce score); <0.7 = bullish options positioning (add to score).
Respond with one line per stock: TICKER|SCORE|REASONING (max 100 chars reasoning).

Examples (use the full 0.0-1.0 range):
NVDA|0.87|3 recent 8-K filings (partnerships), CEO bought $2M shares, no negative events
KSS|0.18|0 positive 8-K, CFO sold $500K shares, negative news cycle; no upcoming catalyst
META|0.65|1 8-K (product announcement), no insider activity, upcoming earnings = binary risk
AAPL|0.55|No recent 8-K filings, routine Form 4 exercises only, quiet catalyst environment
SMCI|0.22|NegativeEvent8K=auditor dismissed; accounting risk overrides all other signals
DLTR|0.78|Activist13D filed (Starboard Value), high bullish options positioning (PC=0.55)"""

# SEC EDGAR requires a descriptive User-Agent with contact info
_EDGAR_UA = "TradingAnalysisApp contact@tradingapp.example.com"


def _get_cik_map() -> dict[str, int]:
    """Fetch and cache the SEC EDGAR ticker→CIK mapping (24h Redis TTL)."""
    import json
    try:
        from app.agents.cache_utils import _sync_redis
        r = _sync_redis()
        if r:
            cached = r.get("edgar:cik_map:v1")
            if cached:
                return json.loads(cached)
        resp = httpx.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": _EDGAR_UA},
            timeout=15,
        )
        if resp.status_code == 200:
            cik_map = {item["ticker"].upper(): item["cik_str"] for item in resp.json().values()}
            if r:
                r.setex("edgar:cik_map:v1", 86_400, json.dumps(cik_map))
            return cik_map
    except Exception as e:
        logger.warning("EDGAR CIK map fetch failed", error=str(e))
    return {}


def _fetch_edgar_filings(ticker: str, cik: int, days: int = 7) -> dict:
    """Return 8-K and Form 4 filing counts for the past `days` days."""
    cutoff = (datetime.now() - timedelta(days=days)).date()
    try:
        resp = httpx.get(
            f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
            headers={"User-Agent": _EDGAR_UA},
            timeout=10,
        )
        if resp.status_code != 200:
            return {"edgar_8k_count": 0, "edgar_form4_count": 0}
        recent = resp.json().get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        k8 = f4 = activist = 0
        negative_8k = False  # item 4.01 (auditor change) or 2.06 (goodwill impairment)
        accession_numbers: list[str] = recent.get("accessionNumber", [])

        for i, (form, ds) in enumerate(zip(forms, dates)):
            try:
                if datetime.strptime(ds, "%Y-%m-%d").date() < cutoff:
                    continue
            except Exception:
                continue
            if form == "8-K":
                k8 += 1
                # Check item type via EDGAR filing index for the most recent 8-K
                if not negative_8k and i < len(accession_numbers):
                    try:
                        acc = accession_numbers[i].replace("-", "")
                        idx_url = f"https://data.sec.gov/Archives/edgar/full-index/{ds[:4]}/{acc}.json"
                        # Simpler: check items from the submission JSON items list if available
                        items_list = recent.get("items", [])
                        if i < len(items_list):
                            items_str = str(items_list[i])
                            if "4.01" in items_str or "2.06" in items_str:
                                negative_8k = True
                    except Exception:
                        pass
            elif form in ("4", "4/A"):
                f4 += 1
            elif form in ("SC 13D", "SC 13D/A"):
                activist += 1  # Activist investor took/increased >5% stake
        return {
            "edgar_8k_count": k8,
            "edgar_form4_count": f4,
            "activist_13d": activist,
            "negative_8k": negative_8k,  # True = auditor change or impairment
        }
    except Exception as e:
        logger.debug("EDGAR filings fetch failed", ticker=ticker, error=str(e))
        return {"edgar_8k_count": 0, "edgar_form4_count": 0}


def catalyst_node(state: dict[str, Any]) -> dict[str, Any]:
    tickers = state.get("candidate_tickers", [])
    if not tickers:
        return {"catalyst_scores": {}, "errors": []}

    try:
        from app.config import get_settings, has_anthropic_key, has_finnhub_key
        settings = get_settings()

        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

        # Fetch EDGAR CIK map once (cached in Redis)
        cik_map = _get_cik_map()

        # Collect catalyst data for all tickers
        raw: dict[str, dict] = {}
        for ticker in tickers:
            has_earnings = False
            earnings_days = None
            news_count = 0

            # Upcoming earnings
            try:
                cal = yf.Ticker(ticker).calendar
                if cal is not None and "Earnings Date" in cal:
                    ed = cal["Earnings Date"]
                    if hasattr(ed, "__iter__"):
                        ed = list(ed)[0] if ed else None
                    if ed:
                        import pandas as pd
                        if isinstance(ed, pd.Timestamp):
                            days = (ed.to_pydatetime().date() - datetime.now().date()).days
                            if 0 <= days <= 30:
                                has_earnings = True
                                earnings_days = days
            except Exception:
                pass

            # Finnhub news count
            if has_finnhub_key():
                try:
                    url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={week_ago}&to={today}&token={settings.finnhub_api_key}"
                    resp = httpx.get(url, timeout=10)
                    if resp.status_code == 200:
                        news_count = len(resp.json())
                except Exception:
                    pass

            # SEC EDGAR recent filings (8-K, Form 4, SC 13D activist)
            edgar = {"edgar_8k_count": 0, "edgar_form4_count": 0, "activist_13d": 0}
            if ticker in cik_map:
                edgar = _fetch_edgar_filings(ticker, cik_map[ticker])
                time.sleep(0.12)  # Stay within SEC's 10 req/sec limit

            # Put/Call ratio from nearest-expiry options chain
            put_call_ratio = None
            try:
                t_obj = yf.Ticker(ticker)
                expiries = t_obj.options
                if expiries:
                    chain = t_obj.option_chain(expiries[0])
                    call_vol = float(chain.calls["volume"].fillna(0).sum())
                    put_vol = float(chain.puts["volume"].fillna(0).sum())
                    if call_vol > 0:
                        put_call_ratio = round(put_vol / call_vol, 2)
            except Exception:
                pass

            raw[ticker] = {
                "has_earnings": has_earnings,
                "earnings_days": earnings_days,
                "news_count": news_count,
                "edgar_8k_count": edgar["edgar_8k_count"],
                "edgar_form4_count": edgar["edgar_form4_count"],
                "activist_13d": edgar["activist_13d"],
                "negative_8k": edgar.get("negative_8k", False),
                "put_call_ratio": put_call_ratio,
            }

        # --- Redis cache: split tickers into cached vs uncached ---
        from app.agents.cache_utils import score_get, score_set
        cached_scores: dict[str, Any] = {}
        uncached_tickers: list[str] = []
        for t in list(raw.keys()):
            cached = score_get("catalyst", t)
            if cached:
                cached_scores[t] = cached
            else:
                uncached_tickers.append(t)

        if cached_scores:
            logger.info("Catalyst cache hits", count=len(cached_scores), uncached=len(uncached_tickers))

        scores: dict[str, Any] = dict(cached_scores)

        llm_ok = False
        if uncached_tickers and has_anthropic_key():
            try:
                from anthropic import Anthropic
                client = Anthropic(api_key=settings.anthropic_api_key)

                lines = []
                for ticker in uncached_tickers:
                    d = raw[ticker]
                    earnings_str = f"in {d['earnings_days']} days" if d["has_earnings"] else ">30 days"
                    pc_str = f"{d['put_call_ratio']:.2f}" if d["put_call_ratio"] is not None else "n/a"
                    activist_str = f"YES({d['activist_13d']})" if d["activist_13d"] else "no"
                    neg8k_str = "YES(auditor/impairment)" if d.get("negative_8k") else "no"
                    lines.append(
                        f"{ticker}: Earnings={earnings_str}, News_7d={d['news_count']}, "
                        f"SEC_8K={d['edgar_8k_count']}, NegativeEvent8K={neg8k_str}, "
                        f"InsiderActivity={d['edgar_form4_count']}, "
                        f"Activist13D={activist_str}, PutCallRatio={pc_str}"
                    )

                from app.agents.llm_utils import call_llm_batched
                raw_response = call_llm_batched(
                    client, lines, CATALYST_SYSTEM,
                    prompt_prefix="Score catalyst strength for each stock (0.5=no catalyst, 1.0=strong near-term catalyst):\n\n",
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
                        score_set("catalyst", t, entry)
                    except Exception:
                        pass
                llm_ok = True
            except Exception as e:
                logger.warning("Catalyst LLM call failed, falling back to rule-based", error=str(e))

        # Rule-based fallback for any ticker still not scored
        for ticker in [t for t in raw if t not in scores]:
            d = raw[ticker]
            score = 0.5
            if d["news_count"] > 5:
                score += 0.1
            if d["has_earnings"] and d["earnings_days"] and 5 <= d["earnings_days"] <= 14:
                score += 0.1
            entry = {
                "score": round(max(0.0, min(1.0, score)), 4),
                "reasoning": f"Rule-based: news={d['news_count']}, earnings={d['earnings_days']}",
            }
            scores[ticker] = entry
            score_set("catalyst", ticker, entry)

        # Merge raw data
        for ticker, d in raw.items():
            if ticker not in scores:
                scores[ticker] = {"score": 0.5, "reasoning": "no data"}
            scores[ticker].update({
                "has_earnings": d["has_earnings"],
                "earnings_days": d["earnings_days"],
                "recent_news_count": d["news_count"],
                "edgar_8k_count": d["edgar_8k_count"],
                "edgar_form4_count": d["edgar_form4_count"],
                "activist_13d": d["activist_13d"],
                "put_call_ratio": d["put_call_ratio"],
                "sec_filings": [],
            })

        logger.info("Catalyst node complete", tickers_analyzed=len(scores))
        return {"catalyst_scores": scores, "errors": []}

    except Exception as e:
        logger.error("Catalyst node failed", error=str(e))
        return {"catalyst_scores": {}, "errors": [f"catalyst: {e}"]}

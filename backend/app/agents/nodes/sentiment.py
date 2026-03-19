import re
import structlog
import httpx
from typing import Any

logger = structlog.get_logger()

SENTIMENT_SYSTEM = """You are a market sentiment analyst. Score each stock 0.0-1.0 for bullish sentiment.
Analyze the provided news headlines carefully — distinguish between genuine bullish catalysts (guidance raises, partnerships, earnings beats) and bearish events (lawsuits, guidance cuts, CEO departure).
Reddit mentions and institutional news sentiment give context but headlines tell you the specific story.
Respond with one line per stock: TICKER|SCORE|REASONING (max 100 chars reasoning).

Examples (use the full 0.0-1.0 range):
NVDA|0.85|Headlines: raised guidance +40%, new data center deals; Reddit very bullish, high mentions
KSS|0.21|Headlines: CEO resigned, store closures announced, guidance cut; Reddit bearish
META|0.71|Headlines: new AI product launch, positive analyst upgrades; neutral Reddit
GME|0.38|Headlines: no new catalysts, meme noise only; retail buzz without fundamental basis
LLY|0.80|Headlines: FDA approval for new indication, strong earnings beat; institutional buying"""


def sentiment_node(state: dict[str, Any]) -> dict[str, Any]:
    tickers = state.get("candidate_tickers", [])
    if not tickers:
        return {"sentiment_scores": {}, "errors": []}

    try:
        from app.config import get_settings, has_anthropic_key, has_finnhub_key
        settings = get_settings()

        # Fetch ApeWisdom Reddit data once (single API call for all tickers)
        reddit_data: dict[str, dict] = {}
        try:
            resp = httpx.get("https://apewisdom.io/api/v1.0/filter/all-stocks/page/1", timeout=10)
            if resp.status_code == 200:
                for item in resp.json().get("results", []):
                    t = item.get("ticker", "")
                    if t in tickers:
                        mentions = item.get("mentions", 0)
                        upvotes = item.get("upvotes", 0)
                        reddit_data[t] = {
                            "mentions": mentions,
                            "sentiment": min(upvotes / max(mentions, 1) / 10, 1.0) - 0.5,
                        }
        except Exception as e:
            logger.warning("ApeWisdom fetch failed", error=str(e))

        # Fetch IBKR news headlines (free providers: Briefing.com + Dow Jones)
        ibkr_headlines: dict[str, list[str]] = {}
        try:
            from app.services.ibkr_news_service import fetch_ibkr_news
            ibkr_headlines = fetch_ibkr_news(tickers)
        except Exception as e:
            logger.debug("IBKR news fetch skipped", error=str(e))

        # Fetch Finnhub company-news headlines (last 5 days) — actual headlines beat aggregate scores
        from datetime import date, timedelta
        news_data: dict[str, dict] = {}
        if has_finnhub_key():
            date_to = date.today().isoformat()
            date_from = (date.today() - timedelta(days=5)).isoformat()
            for ticker in tickers:
                try:
                    # company-news gives actual headlines; news-sentiment gives aggregate bullishPercent
                    url_news = (
                        f"https://finnhub.io/api/v1/company-news?symbol={ticker}"
                        f"&from={date_from}&to={date_to}&token={settings.finnhub_api_key}"
                    )
                    resp_news = httpx.get(url_news, timeout=10)
                    headlines: list[str] = []
                    if resp_news.status_code == 200:
                        articles = resp_news.json()[:5]  # top 5 most recent
                        headlines = [a.get("headline", "") for a in articles if a.get("headline")]

                    # Also get aggregate sentiment as a secondary signal
                    url_sent = f"https://finnhub.io/api/v1/news-sentiment?symbol={ticker}&token={settings.finnhub_api_key}"
                    resp_sent = httpx.get(url_sent, timeout=10)
                    bullish_pct = 0.5
                    if resp_sent.status_code == 200:
                        bullish_pct = resp_sent.json().get("sentiment", {}).get("bullishPercent", 0.5)

                    news_data[ticker] = {
                        "headlines": headlines,
                        "bullish_pct": bullish_pct,
                        "sentiment_delta": bullish_pct - 0.5,
                    }
                except Exception:
                    pass

        # --- Redis cache: split tickers into cached vs uncached ---
        from app.agents.cache_utils import score_get, score_set
        cached_scores: dict[str, Any] = {}
        uncached_tickers: list[str] = []
        for t in tickers:
            cached = score_get("sentiment", t)
            if cached:
                cached_scores[t] = cached
            else:
                uncached_tickers.append(t)

        if cached_scores:
            logger.info("Sentiment cache hits", count=len(cached_scores), uncached=len(uncached_tickers))

        scores: dict[str, Any] = dict(cached_scores)

        llm_ok = False
        if uncached_tickers and has_anthropic_key():
            try:
                from anthropic import Anthropic
                client = Anthropic(api_key=settings.anthropic_api_key)

                lines = []
                for ticker in uncached_tickers:
                    rd = reddit_data.get(ticker, {})
                    nd = news_data.get(ticker, {})
                    ns = nd.get("sentiment_delta", 0.0)
                    # Merge Finnhub + IBKR headlines, deduplicate by first 40 chars
                    finnhub_h = nd.get("headlines", [])
                    ibkr_h = ibkr_headlines.get(ticker, [])
                    seen: set[str] = set()
                    merged: list[str] = []
                    for h in ibkr_h + finnhub_h:
                        key = h[:40].lower()
                        if key not in seen:
                            seen.add(key)
                            merged.append(h)
                    headline_str = " | ".join(merged[:4]) if merged else "no recent news"
                    lines.append(
                        f"{ticker}: News_sentiment={ns:+.2f}, Headlines: {headline_str} | "
                        f"Reddit_mentions={rd.get('mentions', 0)}, Reddit_sentiment={rd.get('sentiment', 0.0):+.2f}"
                    )

                from app.agents.llm_utils import call_llm_batched
                raw_response = call_llm_batched(
                    client, lines, SENTIMENT_SYSTEM,
                    prompt_prefix="Score market sentiment for each stock (-0.5=bearish, 0=neutral, +0.5=bullish raw data → 0.0-1.0 score):\n\n",
                    tokens_per_line=80,
                )

                for line in raw_response.split("\n"):
                    parts = line.split("|")
                    if len(parts) < 3:
                        continue
                    t = parts[0].strip().upper()
                    if t not in tickers:
                        continue
                    try:
                        nums = re.findall(r"0\.\d+|1\.0\b", parts[1])
                        score = float(nums[0]) if nums else 0.5
                        entry = {"score": round(score, 4), "reasoning": parts[2].strip()[:300]}
                        scores[t] = entry
                        score_set("sentiment", t, entry)
                    except Exception:
                        pass
                llm_ok = True
            except Exception as e:
                logger.warning("Sentiment LLM call failed, falling back to rule-based", error=str(e))

        # Rule-based fallback for any ticker still not scored
        for ticker in [t for t in tickers if t not in scores]:
            rd = reddit_data.get(ticker, {})
            nd = news_data.get(ticker, {})
            ns = nd.get("sentiment_delta", 0.0)
            score = max(0.0, min(1.0, 0.5 + ns + rd.get("sentiment", 0.0) * 0.5))
            entry = {
                "score": round(score, 4),
                "reasoning": f"Rule-based: news_delta={ns:.2f}, reddit_mentions={rd.get('mentions', 0)}",
            }
            scores[ticker] = entry
            score_set("sentiment", ticker, entry)

        # Merge raw data
        for ticker in tickers:
            if ticker not in scores:
                scores[ticker] = {"score": 0.5, "reasoning": "no data"}
            rd = reddit_data.get(ticker, {})
            nd = news_data.get(ticker, {})
            scores[ticker].update({
                "news_sentiment": round(nd.get("sentiment_delta", 0.0), 4),
                "reddit_mentions": rd.get("mentions", 0),
                "reddit_sentiment": round(rd.get("sentiment", 0.0), 4),
            })

        logger.info("Sentiment node complete", tickers_analyzed=len(scores))
        return {"sentiment_scores": scores, "errors": []}

    except Exception as e:
        logger.error("Sentiment node failed", error=str(e))
        return {"sentiment_scores": {}, "errors": [f"sentiment: {e}"]}

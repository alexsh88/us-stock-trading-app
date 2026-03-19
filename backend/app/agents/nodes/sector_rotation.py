"""
Sector rotation filter with news-enhanced ranking.

Pipeline:
  1. Compute 1-month RS vs SPY for 11 sector ETFs → momentum ranking.
  2. Fetch Finnhub news headlines for top RS sectors → news signal.
  3. Claude Haiku ranks sectors combining momentum + news context.
     Rule-based fallback: pure RS ranking.
  4. Keep only candidate tickers whose sector is in the top N favored list.
  5. Cache result (4h TTL) — sector rankings are stable through the trading day.

Sector ETFs (Select Sector SPDR, GICS):
  XLK  Technology           XLF  Financials
  XLE  Energy               XLV  Health Care
  XLI  Industrials          XLY  Consumer Discretionary
  XLP  Consumer Staples     XLU  Utilities
  XLRE Real Estate          XLB  Materials
  XLC  Communication Services
"""

import structlog
import yfinance as yf
import httpx
from typing import Any

logger = structlog.get_logger()

SECTOR_ETFS: dict[str, str] = {
    "XLK":  "Technology",
    "XLF":  "Financials",
    "XLE":  "Energy",
    "XLV":  "Health Care",
    "XLI":  "Industrials",
    "XLY":  "Consumer Discretionary",
    "XLP":  "Consumer Staples",
    "XLU":  "Utilities",
    "XLRE": "Real Estate",
    "XLB":  "Materials",
    "XLC":  "Communication Services",
}

# Reverse mapping: sector name → ETF
SECTOR_ETF_REVERSE = {v: k for k, v in SECTOR_ETFS.items()}

# GICS sector classification for every ticker in CANDIDATE_UNIVERSE
TICKER_SECTOR: dict[str, str] = {
    # Technology
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "AMD":  "Technology", "AVGO": "Technology", "ORCL": "Technology",
    "CRM":  "Technology", "ADBE": "Technology", "QCOM": "Technology",
    "TXN":  "Technology", "INTC": "Technology", "MU":   "Technology",
    "AMAT": "Technology", "LRCX": "Technology", "KLAC": "Technology",
    "MRVL": "Technology", "PANW": "Technology", "SNPS": "Technology",
    "CDNS": "Technology", "NOW":  "Technology", "SNOW": "Technology",
    "PLTR": "Technology",
    # Communication Services
    "GOOGL": "Communication Services", "META":  "Communication Services",
    "NFLX":  "Communication Services", "DIS":   "Communication Services",
    "CMCSA": "Communication Services", "CHTR":  "Communication Services",
    "SPOT":  "Communication Services", "TTD":   "Communication Services",
    "ROKU":  "Communication Services", "RBLX":  "Communication Services",
    # Consumer Discretionary
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "UBER": "Consumer Discretionary", "LYFT": "Consumer Discretionary",
    "HD":   "Consumer Discretionary", "LOW":  "Consumer Discretionary",
    "MCD":  "Consumer Discretionary", "SBUX": "Consumer Discretionary",
    "NKE":  "Consumer Discretionary", "LULU": "Consumer Discretionary",
    "DECK": "Consumer Discretionary", "BURL": "Consumer Discretionary",
    "TJX":  "Consumer Discretionary", "ROST": "Consumer Discretionary",
    "TGT":  "Consumer Discretionary",
    # Consumer Staples
    "COST": "Consumer Staples", "WMT": "Consumer Staples",
    # Financials
    "JPM":  "Financials", "BAC":  "Financials", "WFC":  "Financials",
    "GS":   "Financials", "MS":   "Financials", "C":    "Financials",
    "BLK":  "Financials", "AXP":  "Financials", "V":    "Financials",
    "MA":   "Financials", "PYPL": "Financials", "SQ":   "Financials",
    "SPGI": "Financials", "MCO":  "Financials", "COIN": "Financials",
    # Health Care
    "UNH":  "Health Care", "LLY":  "Health Care", "JNJ":  "Health Care",
    "ABBV": "Health Care", "MRK":  "Health Care", "PFE":  "Health Care",
    "TMO":  "Health Care", "ABT":  "Health Care", "AMGN": "Health Care",
    "GILD": "Health Care", "BIIB": "Health Care", "MRNA": "Health Care",
    "DXCM": "Health Care", "ISRG": "Health Care", "IDXX": "Health Care",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "EOG": "Energy",
    "SLB": "Energy", "MPC": "Energy", "VLO": "Energy", "PSX": "Energy",
    "OXY": "Energy", "HAL": "Energy", "DVN": "Energy", "FANG": "Energy",
    "BKR": "Energy", "MRO": "Energy", "HES": "Energy", "APA": "Energy",
    "AR":  "Energy", "RRC": "Energy",
    # Industrials
    "CAT": "Industrials", "DE":  "Industrials", "BA":  "Industrials",
    "GE":  "Industrials", "HON": "Industrials", "RTX": "Industrials",
    "LMT": "Industrials", "NOC": "Industrials", "GD":  "Industrials",
    "UPS": "Industrials", "FDX": "Industrials", "CSX": "Industrials",
    "NSC": "Industrials", "EMR": "Industrials", "ETN": "Industrials",
    "PH":  "Industrials", "ROK": "Industrials", "CMI": "Industrials",
    "CARR": "Industrials", "OTIS": "Industrials",
    # Materials / Process Industries
    "FCX": "Materials", "NEM": "Materials", "ALB": "Materials", "MP": "Materials",
    "LIN": "Materials", "APD": "Materials", "DOW": "Materials", "DD":  "Materials",
    "CF":  "Materials", "MOS": "Materials",
    "SHW": "Materials", "PPG": "Materials", "ECL": "Materials", "IFF": "Materials",
    "CE":  "Materials", "NUE": "Materials", "STLD": "Materials", "RS": "Materials",
    # Precious metals / gold miners (map to Materials as closest GICS)
    "AEM": "Materials", "GOLD": "Materials", "KGC": "Materials",
    "WPM": "Materials", "FNV": "Materials", "RGLD": "Materials",
    # Real Estate
    "AMT":  "Real Estate", "PLD":  "Real Estate", "EQIX": "Real Estate",
    "CCI":  "Real Estate", "PSA":  "Real Estate", "EQR":  "Real Estate",
    "AVB":  "Real Estate", "O":    "Real Estate", "WELL": "Real Estate",
    "SPG":  "Real Estate", "VICI": "Real Estate", "DLR":  "Real Estate",
    "IRM":  "Real Estate", "SBAC": "Real Estate", "EXR":  "Real Estate",
    # Utilities
    "NEE": "Utilities", "DUK": "Utilities", "SO":  "Utilities", "D":   "Utilities",
    "AEP": "Utilities", "EXC": "Utilities", "XEL": "Utilities", "ED":  "Utilities",
    "WEC": "Utilities", "ES":  "Utilities", "AWK": "Utilities", "PPL": "Utilities",
    "ETR": "Utilities", "AES": "Utilities", "CNP": "Utilities",
    # Consumer Staples
    "PG":   "Consumer Staples", "KO":  "Consumer Staples", "PEP":  "Consumer Staples",
    "PM":   "Consumer Staples", "MO":  "Consumer Staples", "MDLZ": "Consumer Staples",
    "CL":   "Consumer Staples", "KHC": "Consumer Staples", "GIS":  "Consumer Staples",
    "K":    "Consumer Staples", "HSY": "Consumer Staples", "EL":   "Consumer Staples",
    "CHD":  "Consumer Staples",
    # Financials additions
    "COF": "Financials", "USB": "Financials", "PNC": "Financials",
    "TFC": "Financials", "SCHW": "Financials", "ICE": "Financials", "CME": "Financials",
    # Healthcare additions
    "BSX": "Health Care", "MDT": "Health Care", "EW":   "Health Care",
    "REGN": "Health Care", "VRTX": "Health Care",
    # Communication Services additions
    "T": "Communication Services", "VZ": "Communication Services",
    "EA": "Communication Services", "WBD": "Communication Services",
    # Consumer Discretionary additions
    "ABNB": "Consumer Discretionary", "ETSY": "Consumer Discretionary",
    "DPZ":  "Consumer Discretionary", "CMG":  "Consumer Discretionary",
}

SECTOR_SYSTEM = (
    "You are a sector rotation analyst. Given sector ETF momentum (RS vs SPY, 1-month) "
    "and recent news headlines, identify which sectors are most favorable to trade right now.\n"
    "Strong positive RS = sector leading the market. Positive news = near-term tailwind.\n"
    "Respond with ALL sectors ranked, one per line:\n"
    "SECTOR_NAME|SCORE|NEWS_SIGNAL|REASONING\n"
    "SCORE: 0.0–1.0 (higher = more favorable). "
    "NEWS_SIGNAL: positive, neutral, or negative. REASONING: max 80 chars."
)

TOP_N_SECTORS = 5  # Keep tickers from this many sectors


def _compute_sector_rs() -> dict[str, float]:
    """Compute 1-month RS vs SPY for each sector ETF. Returns {etf: rs_float}."""
    etfs = list(SECTOR_ETFS.keys()) + ["SPY"]
    try:
        data = yf.download(
            etfs, period="1mo", interval="1d",
            progress=False, auto_adjust=True, group_by="ticker"
        )
        spy_close = None
        if "SPY" in data.columns.get_level_values(0):
            spy_close = data["SPY"]["Close"].dropna()
        spy_ret = float(spy_close.iloc[-1] / spy_close.iloc[0] - 1) if spy_close is not None and len(spy_close) > 1 else 0.0

        rs_map: dict[str, float] = {}
        for etf in SECTOR_ETFS:
            try:
                close = data[etf]["Close"].dropna() if etf in data.columns.get_level_values(0) else None
                if close is not None and len(close) > 1:
                    rs_map[etf] = round(float(close.iloc[-1] / close.iloc[0] - 1) - spy_ret, 4)
                else:
                    rs_map[etf] = 0.0
            except Exception:
                rs_map[etf] = 0.0
        return rs_map
    except Exception as e:
        logger.warning("Sector RS calculation failed", error=str(e))
        return {etf: 0.0 for etf in SECTOR_ETFS}


def _fetch_sector_news(finnhub_key: str, etfs: list[str]) -> dict[str, list[str]]:
    """Fetch recent news headlines for sector ETFs from Finnhub."""
    from datetime import datetime, timedelta
    news: dict[str, list[str]] = {}
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    for etf in etfs:
        try:
            url = (
                f"https://finnhub.io/api/v1/company-news"
                f"?symbol={etf}&from={week_ago}&to={today}&token={finnhub_key}"
            )
            resp = httpx.get(url, timeout=8)
            if resp.status_code == 200:
                headlines = [item.get("headline", "")[:120] for item in resp.json()[:5] if item.get("headline")]
                if headlines:
                    news[etf] = headlines
        except Exception:
            pass
    return news


def _rank_sectors_llm(client: Any, rs_map: dict[str, float], news_map: dict[str, list[str]]) -> list[str]:
    """Use Claude Haiku to rank sectors by momentum + news. Returns ranked sector name list."""
    import re
    lines = []
    for etf, sector in SECTOR_ETFS.items():
        rs = rs_map.get(etf, 0.0)
        headlines = "; ".join(news_map.get(etf, []))[:200] or "No recent headlines"
        lines.append(f"{sector}: RS_vs_SPY={rs:+.2%} | Headlines: {headlines}")

    prompt = (
        "Today's sector momentum and news:\n\n"
        + "\n".join(lines)
        + "\n\nRank ALL sectors from most to least favorable to trade today. "
          "Consider both RS momentum and news sentiment.\n\n"
          "Format: SECTOR_NAME|SCORE|NEWS_SIGNAL|REASONING"
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=SECTOR_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    ranked: list[tuple[str, float]] = []
    sector_names = set(SECTOR_ETFS.values())
    for line in response.content[0].text.strip().split("\n"):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        # Fuzzy-match the sector name
        matched = next(
            (s for s in sector_names if s.lower() in name.lower() or name.lower() in s.lower()),
            None,
        )
        if matched:
            try:
                nums = re.findall(r"\d+\.?\d*", parts[1])
                score = float(nums[0]) if nums else 0.5
                ranked.append((matched, score))
            except Exception:
                pass

    # De-duplicate and return top N
    seen: set[str] = set()
    result: list[str] = []
    for name, _ in sorted(ranked, key=lambda x: x[1], reverse=True):
        if name not in seen:
            seen.add(name)
            result.append(name)

    return result[:TOP_N_SECTORS] if result else []


def _rank_sectors_rule_based(rs_map: dict[str, float]) -> list[str]:
    """Fallback: return top N sectors by trailing RS vs SPY."""
    ranked = sorted(SECTOR_ETFS.items(), key=lambda kv: rs_map.get(kv[0], 0.0), reverse=True)
    return [sector for _, sector in ranked[:TOP_N_SECTORS]]


def _filter_by_sectors(tickers: list[str], favored: list[str]) -> list[str]:
    """Keep tickers whose sector is in the favored list. Unknown tickers pass through."""
    favored_set = set(favored)
    in_sector = [t for t in tickers if TICKER_SECTOR.get(t, "") in favored_set]
    unknown = [t for t in tickers if t not in TICKER_SECTOR]
    return in_sector + unknown


def sector_rotation_node(state: dict[str, Any]) -> dict[str, Any]:
    tickers = state.get("candidate_tickers", [])
    mode = state.get("mode", "swing")

    if not tickers:
        return {"candidate_tickers": [], "favored_sectors": [], "sector_scores": {}, "errors": []}

    try:
        from app.agents.cache_utils import sector_get, sector_set
        from app.config import get_settings, has_anthropic_key, has_finnhub_key

        # 1. Check cache
        cached = sector_get(mode)
        if cached:
            favored = cached["favored_sectors"]
            sector_scores = cached["sector_scores"]
            filtered = _filter_by_sectors(tickers, favored)
            result = filtered if filtered else tickers
            logger.info(
                "Sector rotation (cached)",
                favored_sectors=favored,
                before=len(tickers),
                after=len(result),
            )
            return {
                "candidate_tickers": result,
                "favored_sectors": favored,
                "sector_scores": sector_scores,
                "errors": [],
            }

        settings = get_settings()

        # 2. Compute sector ETF RS
        rs_map = _compute_sector_rs()

        # Build sector_scores dict keyed by sector name
        sector_scores: dict[str, Any] = {
            sector: {"etf": etf, "rs_vs_spy": rs_map.get(etf, 0.0), "rank": None, "favored": False}
            for etf, sector in SECTOR_ETFS.items()
        }

        # 3. Fetch news only for top 6 sectors by RS (stay within Finnhub rate limits)
        top_etfs_by_rs = sorted(SECTOR_ETFS.keys(), key=lambda e: rs_map.get(e, 0.0), reverse=True)[:6]
        news_map: dict[str, list[str]] = {}
        if has_finnhub_key():
            news_map = _fetch_sector_news(settings.finnhub_api_key, top_etfs_by_rs)

        # 4. Rank sectors
        favored: list[str] = []
        if has_anthropic_key():
            try:
                from anthropic import Anthropic
                client = Anthropic(api_key=settings.anthropic_api_key)
                favored = _rank_sectors_llm(client, rs_map, news_map)
            except Exception as e:
                logger.warning("Sector LLM ranking failed, using RS fallback", error=str(e))

        if not favored:
            favored = _rank_sectors_rule_based(rs_map)

        # Annotate sector_scores with rank
        for i, s in enumerate(favored):
            if s in sector_scores:
                sector_scores[s]["rank"] = i + 1
                sector_scores[s]["favored"] = True

        # 5. Cache
        sector_set(mode, {"favored_sectors": favored, "sector_scores": sector_scores})

        # 6. Filter candidates
        filtered = _filter_by_sectors(tickers, favored)
        result = filtered if filtered else tickers  # never return empty

        logger.info(
            "Sector rotation complete",
            favored_sectors=favored,
            before=len(tickers),
            after=len(result),
        )
        return {
            "candidate_tickers": result,
            "favored_sectors": favored,
            "sector_scores": sector_scores,
            "errors": [],
        }

    except Exception as e:
        logger.error("Sector rotation node failed", error=str(e))
        return {
            "candidate_tickers": tickers,  # pass through unchanged
            "favored_sectors": [],
            "sector_scores": {},
            "errors": [f"sector_rotation: {e}"],
        }

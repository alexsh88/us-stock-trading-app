"""
IBKR news fetching via ib_async (active fork of dead ib_insync).

Free news providers included with every IBKR account:
  BRFG  = Briefing.com General Columns
  BRFUPDN = Briefing.com Analyst Actions
  DJNL  = Dow Jones Newsletters

Requires IB Gateway to be running (port 4002 for paper, 4001 for live).
Gracefully returns empty dict if gateway is unavailable.
"""
import structlog
from typing import Any

logger = structlog.get_logger()

_FREE_PROVIDERS = "BRFG+DJNL"
_MAX_HEADLINES = 5


def fetch_ibkr_news(tickers: list[str]) -> dict[str, list[str]]:
    """
    Fetch recent news headlines for each ticker via IBKR TWS API.
    Returns {ticker: [headline1, headline2, ...]} — empty list if unavailable.
    Gracefully no-ops if ib_async is not installed or gateway is unreachable.
    """
    try:
        from ib_async import IB, Stock
        from app.config import get_settings
        settings = get_settings()
    except ImportError:
        logger.debug("ib_async not installed — skipping IBKR news")
        return {}

    results: dict[str, list[str]] = {t: [] for t in tickers}

    try:
        ib = IB()
        ib.connect(settings.ibkr_gateway_host, settings.ibkr_gateway_port,
                   clientId=99, timeout=5, readonly=True)

        for ticker in tickers:
            try:
                contract = Stock(ticker, "SMART", "USD")
                ib.qualifyContracts(contract)
                if not contract.conId:
                    continue

                headlines = ib.reqHistoricalNews(
                    conId=contract.conId,
                    providerCodes=_FREE_PROVIDERS,
                    startDateTime="",
                    endDateTime="",
                    totalResults=_MAX_HEADLINES,
                )
                results[ticker] = [h.headline for h in headlines if h.headline]
            except Exception as e:
                logger.debug("IBKR news fetch failed for ticker", ticker=ticker, error=str(e))

        ib.disconnect()
        fetched = sum(1 for v in results.values() if v)
        if fetched:
            logger.info("IBKR news fetched", tickers_with_news=fetched)

    except Exception as e:
        logger.debug("IBKR gateway unavailable for news", error=str(e))

    return results

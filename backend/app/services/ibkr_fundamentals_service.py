"""
IBKR fundamental data via ib_async reqFundamentalData('ReportSnapshot').

Free with every IBKR account — no data subscription required.
Returns P/E, revenue growth, net margin, D/E ratio, current ratio, market cap.

Fields not in ReportSnapshot (fpe, fcf_yield) are returned as None;
the caller falls back to yfinance for those specific fields.

Gracefully returns empty dict if gateway is unavailable.
"""
import xml.etree.ElementTree as ET
import structlog

logger = structlog.get_logger()

_CLIENT_ID  = 96          # distinct from scanner (97) and news (99)
_CONNECT_TO = 5           # gateway connection timeout (seconds)


def _parse_ratio(root: ET.Element, field_name: str) -> float | None:
    """Return the first Ratio element matching FieldName, parsed as float."""
    for elem in root.iter("Ratio"):
        if elem.get("FieldName") == field_name and elem.text:
            try:
                return float(elem.text)
            except (TypeError, ValueError):
                pass
    return None


def fetch_ibkr_fundamentals(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch ReportSnapshot fundamentals for each ticker via IBKR TWS API.

    Returns {ticker: {pe, fpe, rev_growth, margin, de, cr, fcf_yield, mcap}}
    where fpe and fcf_yield are always None (not in ReportSnapshot — caller
    fills them from yfinance if needed).

    Returns {} if gateway is unreachable or ib_async is not installed.
    """
    try:
        from ib_async import IB, Stock
        from app.config import get_settings
        settings = get_settings()
    except ImportError:
        logger.debug("ib_async not installed — IBKR fundamentals unavailable")
        return {}

    ib = IB()
    try:
        ib.connect(
            settings.ibkr_gateway_host,
            settings.ibkr_gateway_port,
            clientId=_CLIENT_ID,
            timeout=_CONNECT_TO,
            readonly=True,
        )
    except Exception as e:
        logger.debug("IBKR gateway unavailable — fundamentals skipped", error=str(e))
        return {}

    results: dict[str, dict] = {}
    try:
        for ticker in tickers:
            try:
                contract = Stock(ticker, "SMART", "USD")
                ib.qualifyContracts(contract)
                if not contract.conId:
                    continue

                xml_str = ib.reqFundamentalData(contract, "ReportSnapshot")
                if not xml_str:
                    continue

                root = ET.fromstring(xml_str)

                # P/E trailing (ex-extraordinary items)
                pe = _parse_ratio(root, "PEEXCLXOR")

                # Revenue growth YoY — reported as %, convert to decimal
                rev_raw = _parse_ratio(root, "TTMREVCHG")
                rev_growth = rev_raw / 100.0 if rev_raw is not None else None

                # Net profit margin TTM — reported as %, convert to decimal
                margin_raw = _parse_ratio(root, "TTMNETMGN")
                margin = margin_raw / 100.0 if margin_raw is not None else None

                # Total debt/equity ratio (quarterly)
                de = _parse_ratio(root, "QTOTD2EQ")

                # Current ratio (quarterly)
                cr = _parse_ratio(root, "QCURRATIO")

                # Market cap — IBKR reports in millions USD
                mcap_m = _parse_ratio(root, "MKTCAP")
                mcap = mcap_m * 1_000_000 if mcap_m is not None else None

                results[ticker] = {
                    "pe": pe,
                    "fpe": None,        # not in ReportSnapshot
                    "rev_growth": rev_growth,
                    "margin": margin,
                    "de": de,
                    "cr": cr,
                    "fcf_yield": None,  # not in ReportSnapshot
                    "mcap": mcap,
                }

            except Exception as e:
                logger.debug("IBKR fundamentals failed for ticker",
                             ticker=ticker, error=str(e))

    finally:
        try:
            ib.disconnect()
        except Exception:
            pass

    if results:
        logger.info("IBKR fundamentals fetched", tickers=len(results))
    else:
        logger.debug("IBKR fundamentals returned no results")

    return results

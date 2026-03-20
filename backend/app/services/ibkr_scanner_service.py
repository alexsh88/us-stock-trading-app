"""
IBKR real-time scanner via ib_async.

Uses reqScannerData to pull pre-filtered US equity candidates directly from
Interactive Brokers' servers instead of downloading 40-65 tickers from yfinance.

Scan codes used:
  Swing:    TOP_PERC_GAIN_TODAY  — fresh momentum breakouts
            HIGH_VS_52_WK_HL    — stocks near 52-week high (momentum continuation)
  Intraday: MOST_ACTIVE_TODAY   — highest dollar volume (liquidity + movement)
            HIGH_VS_52_WK_HL    — momentum context

Returns None if gateway is unreachable — caller falls back to ETF-first logic.
Requires IB Gateway running on port 4002 (paper) or 4001 (live).
"""
import structlog

logger = structlog.get_logger()

_CLIENT_ID   = 97          # distinct from news service (99) and default (1)
_CONNECT_TO  = 5           # seconds to wait for gateway connection
_SCAN_WAIT   = 3           # seconds to let scanner results arrive
_MAX_ROWS    = 50          # results per scan code
_MIN_PRICE   = 5.0
_MAX_PRICE   = 2000.0

# mode → list of IBKR scan codes to run (results are unioned)
_SCAN_CODES: dict[str, list[str]] = {
    "swing":    ["TOP_PERC_GAIN_TODAY", "HIGH_VS_52_WK_HL"],
    "intraday": ["MOST_ACTIVE_TODAY",   "HIGH_VS_52_WK_HL"],
}


def scan_candidates(mode: str = "swing") -> list[str] | None:
    """
    Run IBKR scanner for the given trading mode.

    Returns a deduplicated list of US equity tickers, or None if the gateway
    is unreachable (caller should fall back to ETF-first logic).

    Volume filter is mode-aware:
      swing    → 500 k avg daily volume (same as screener)
      intraday → 1 M  avg daily volume
    """
    try:
        from ib_async import IB, ScannerSubscription
    except ImportError:
        logger.debug("ib_async not installed — IBKR scanner unavailable")
        return None

    try:
        from app.config import get_settings
        settings = get_settings()
    except Exception:
        return None

    min_volume = 1_000_000 if mode == "intraday" else 500_000
    scan_codes = _SCAN_CODES.get(mode, _SCAN_CODES["swing"])

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
        logger.debug("IBKR gateway unavailable — scanner skipped", error=str(e))
        return None

    tickers: list[str] = []
    try:
        seen: set[str] = set()

        for scan_code in scan_codes:
            try:
                sub = ScannerSubscription(
                    instrument="STK",
                    locationCode="STK.US.MAJOR",
                    scanCode=scan_code,
                    abovePrice=_MIN_PRICE,
                    belowPrice=_MAX_PRICE,
                    aboveVolume=min_volume,
                    numberOfRows=_MAX_ROWS,
                )
                scan_data = ib.reqScannerData(sub)
                ib.sleep(_SCAN_WAIT)          # let results arrive via callbacks
                ib.cancelScannerSubscription(scan_data)

                for item in scan_data:
                    symbol = item.contractDetails.contract.symbol
                    if symbol and symbol not in seen:
                        seen.add(symbol)
                        tickers.append(symbol)

                logger.debug("IBKR scan complete", scan_code=scan_code, results=len(scan_data))

            except Exception as e:
                logger.warning("IBKR scan failed for code", scan_code=scan_code, error=str(e))

    finally:
        try:
            ib.disconnect()
        except Exception:
            pass

    if tickers:
        logger.info("IBKR scanner universe", mode=mode, tickers=len(tickers),
                    scan_codes=scan_codes)
    else:
        logger.debug("IBKR scanner returned no results", mode=mode)
        return None

    return tickers

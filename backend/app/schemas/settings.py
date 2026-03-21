from pydantic import BaseModel, Field
from typing import Optional


class AppSettings(BaseModel):
    top_n: int = Field(default=5, ge=1, le=50)
    trading_mode: str = Field(default="swing", pattern="^(swing|intraday)$")
    paper_trading: bool = True
    ibkr_enabled: bool = Field(default=False, description="Enable live IBKR TWS connection for bracket order submission")
    watchlist: Optional[str] = Field(default=None, description="Comma-separated tickers to analyse instead of screener")
    sector_top_n: int = Field(default=3, ge=1, le=14, description="Number of leading sector ETFs to build the universe from")
    pinned_sectors: list[str] = Field(default_factory=list, description="Specific sector ETFs to pin (e.g. ['XLK','XLE']). Empty = auto ETF ranking.")


class AppSettingsResponse(AppSettings):
    pass

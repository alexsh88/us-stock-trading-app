import operator
from typing import Annotated, TypedDict, Optional, Any


class TechnicalScore(TypedDict):
    score: float
    rsi: float
    macd_signal: str  # bullish/bearish/neutral
    atr: float
    bb_position: str  # above_upper/below_lower/middle
    vwap_relation: str  # above/below
    reasoning: str


class FundamentalScore(TypedDict):
    score: float
    pe_ratio: Optional[float]
    revenue_growth: Optional[float]
    profit_margin: Optional[float]
    fcf_yield: Optional[float]
    reasoning: str


class SentimentScore(TypedDict):
    score: float
    news_sentiment: float  # -1.0 to 1.0
    reddit_mentions: int
    reddit_sentiment: float  # -1.0 to 1.0
    reasoning: str


class CatalystScore(TypedDict):
    score: float
    has_earnings: bool
    earnings_days: Optional[int]
    recent_news_count: int
    sec_filings: list[str]
    reasoning: str


class RiskMetrics(TypedDict):
    atr: float
    stop_loss_pct: float
    kelly_fraction: float
    position_size_pct: float
    stop_loss_method: str


class TradeSignalData(TypedDict):
    ticker: str
    decision: str  # BUY/SELL/HOLD/SKIP
    confidence_score: float
    trading_mode: str
    entry_price: Optional[float]
    stop_loss_price: Optional[float]
    stop_loss_method: Optional[str]
    take_profit_price: Optional[float]
    risk_reward_ratio: Optional[float]
    position_size_pct: Optional[float]
    technical_score: float
    fundamental_score: float
    sentiment_score: float
    catalyst_score: float
    key_risks: list[str]
    reasoning: str


class AgentState(TypedDict):
    # Inputs
    mode: str  # swing / intraday
    top_n: int
    sector_top_n: int  # number of leading ETFs to build universe from (1-14, default 3)
    pinned_sectors: list[str]  # specific ETFs to force (e.g. ["XLK","XLE"]); empty = auto-rank
    watchlist_active: bool  # True when candidate_tickers came from a custom watchlist
    run_id: str

    # Screener output
    candidate_tickers: list[str]

    # Market regime (from screener): sizing_multiplier, vix, spy_vs_ma200_pct, etc.
    market_regime: dict[str, Any]

    # Sector rotation output (after screener, before parallel nodes)
    favored_sectors: list[str]          # e.g. ["Technology", "Financials", ...]
    sector_scores: dict[str, Any]       # sector name → {etf, rs_vs_spy, rank, favored}

    # Per-agent score maps (keyed by ticker — avoids parallel write conflicts)
    technical_scores: dict[str, TechnicalScore]
    fundamental_scores: dict[str, FundamentalScore]
    sentiment_scores: dict[str, SentimentScore]
    catalyst_scores: dict[str, CatalystScore]
    risk_metrics: dict[str, RiskMetrics]

    # Final output
    trade_signals: list[TradeSignalData]

    # News headlines per ticker — populated by sentiment node, stored in news_embeddings
    # Format: {ticker: ["headline 1", "headline 2", ...]}
    news_headlines: dict[str, list[str]]

    # Parallel-safe error accumulator (operator.add reducer appends from all parallel nodes)
    errors: Annotated[list[str], operator.add]

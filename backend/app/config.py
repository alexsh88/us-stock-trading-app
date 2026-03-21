from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "US Stock Trading Analysis API"
    environment: str = "development"
    log_level: str = "INFO"
    secret_key: str = "change-me-in-production"

    # Database
    database_url: str = "postgresql+asyncpg://trading:trading_secret@localhost:5432/trading_db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Anthropic
    anthropic_api_key: str = ""

    # Finnhub
    finnhub_api_key: str = ""

    # IBKR
    ibkr_username: str = ""
    ibkr_password: str = ""
    ibkr_gateway_host: str = "localhost"
    ibkr_gateway_port: int = 7497   # TWS paper=7497, TWS live=7496, Gateway paper=4002, Gateway live=4001
    ibkr_client_id_data: int = 99   # read-only data services (news, scanner, fundamentals)
    ibkr_client_id_orders: int = 1  # order placement — must differ from data client ID

    # Trading defaults
    default_top_n: int = 5
    default_trading_mode: str = "swing"
    paper_trading: bool = True

    # Rate limits
    finnhub_requests_per_minute: int = 60

    # FRED (macro data — free API key at fred.stlouisfed.org)
    fred_api_key: str = ""

    # Twelve Data (price data backup — free 800/day at twelvedata.com)
    twelve_data_api_key: str = ""

    # Tiingo (price data backup — free 1000/day at tiingo.com)
    tiingo_api_key: str = ""

    # Alpaca (free real-time data via paper account at alpaca.markets)
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""

    # LangSmith tracing (free 5000 traces/mo at smith.langchain.com)
    langchain_api_key: str = ""
    langchain_project: str = "us-stock-trading-app"
    langchain_tracing: bool = False

    # OpenAI (news embeddings — text-embedding-3-small, ~$0.000005/day)
    openai_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


def has_anthropic_key() -> bool:
    """Return True only if the key looks like a real key (not a placeholder)."""
    key = get_settings().anthropic_api_key
    return bool(key) and not key.startswith("your_") and len(key) > 20


def has_finnhub_key() -> bool:
    key = get_settings().finnhub_api_key
    return bool(key) and not key.startswith("your_") and len(key) > 8


def has_fred_key() -> bool:
    key = get_settings().fred_api_key
    return bool(key) and not key.startswith("your_") and len(key) > 8


def has_twelve_data_key() -> bool:
    key = get_settings().twelve_data_api_key
    return bool(key) and not key.startswith("your_") and len(key) > 8

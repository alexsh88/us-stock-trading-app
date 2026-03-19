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
    ibkr_gateway_port: int = 4002

    # Trading defaults
    default_top_n: int = 5
    default_trading_mode: str = "swing"
    paper_trading: bool = True

    # Rate limits
    finnhub_requests_per_minute: int = 60


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

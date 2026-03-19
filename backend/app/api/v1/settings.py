import structlog
from fastapi import APIRouter
from app.config import get_settings
from app.schemas.settings import AppSettings, AppSettingsResponse

logger = structlog.get_logger()
router = APIRouter()

# Initialise from env defaults, then mutated in-memory on PATCH
def _default_settings() -> AppSettings:
    cfg = get_settings()
    return AppSettings(
        top_n=cfg.default_top_n,
        trading_mode=cfg.default_trading_mode,
        paper_trading=cfg.paper_trading,
    )

_current_settings = _default_settings()


@router.get("/", response_model=AppSettingsResponse)
async def get_app_settings():
    return _current_settings


@router.patch("/", response_model=AppSettingsResponse)
async def update_app_settings(settings: AppSettings):
    global _current_settings
    _current_settings = settings
    return _current_settings

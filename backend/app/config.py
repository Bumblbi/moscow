from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Transport schedule change predictor"
    database_url: str = "sqlite+aiosqlite:///./transport.db"
    redis_url: str = ""
    ml_service_url: str = "http://localhost:8001"
    ml_timeout_seconds: float = 1.5
    prediction_horizon_min: int = Field(default=15, ge=10, le=15)
    delay_threshold_min: float = 3.0
    seed_demo_data: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()

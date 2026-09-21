"""Конфигурация backend из переменных окружения."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Хранит настройки, необходимые backend-приложению."""

    database_url: str

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Возвращает единый экземпляр настроек приложения."""
    return Settings()  # type: ignore[call-arg]

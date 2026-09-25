"""Конфигурация backend из переменных окружения."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Хранит настройки, необходимые backend-приложению."""

    database_url: str
    frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    ai_text_enabled: bool = False
    ai_text_provider: str = "openai"
    ai_text_base_url: str = ""
    ai_text_api_key: str = ""
    openai_api_key: str = ""
    ai_text_model: str = ""
    ai_text_timeout_seconds: float = 15
    ai_text_max_output_tokens: int = 300
    ai_text_fallback_enabled: bool = True

    @property
    def allowed_frontend_origins(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.frontend_origins.split(",")
            if origin.strip()
        ]

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Возвращает единый экземпляр настроек приложения."""
    return Settings()  # type: ignore[call-arg]

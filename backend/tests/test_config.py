"""Проверки конфигурации backend."""

from app.core.config import Settings


def test_database_url_can_be_read_from_environment(monkeypatch) -> None:
    """DATABASE_URL загружается из окружения без значения в коде."""
    database_url = "postgresql+asyncpg://user:password@localhost:5432/training"
    monkeypatch.setenv("DATABASE_URL", database_url)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.database_url == database_url

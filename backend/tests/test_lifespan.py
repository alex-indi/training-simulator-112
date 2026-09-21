"""Проверки жизненного цикла FastAPI-приложения."""

import asyncio
import logging
from unittest.mock import AsyncMock

from fastapi import FastAPI

import app.main as main_module


def test_lifespan_checks_database_and_logs_connection(monkeypatch, caplog) -> None:
    """Startup проверяет PostgreSQL, сообщает об успехе и освобождает engine."""
    application = FastAPI()
    engine = AsyncMock()
    check_connection = AsyncMock()

    monkeypatch.setattr(main_module, "get_settings", lambda: object())
    monkeypatch.setattr(main_module, "create_database_engine", lambda settings: engine)
    monkeypatch.setattr(main_module, "check_database_connection", check_connection)

    async def run_lifespan() -> None:
        async with main_module.lifespan(application):
            assert application.state.database_engine is engine

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        asyncio.run(run_lifespan())

    check_connection.assert_awaited_once_with(engine)
    engine.dispose.assert_awaited_once()
    assert "Подключение к PostgreSQL установлено" in caplog.messages

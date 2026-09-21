"""Точка входа FastAPI-приложения."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.db.session import check_database_connection, create_database_engine

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Проверяет PostgreSQL при старте и освобождает соединения при остановке."""
    engine = create_database_engine(get_settings())
    application.state.database_engine = engine

    try:
        try:
            await check_database_connection(engine)
        except Exception:
            logger.exception("Не удалось подключиться к PostgreSQL при запуске backend")
            raise

        logger.info("Подключение к PostgreSQL установлено")
        yield
    finally:
        await engine.dispose()


app = FastAPI(
    title="Учебный тренажёр 112",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Подтверждает, что backend запущен и принимает запросы."""
    return {"status": "ok", "service": "training-simulator-112"}

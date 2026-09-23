"""Точка входа FastAPI-приложения."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.db.session import (
    check_database_connection,
    create_database_engine,
    create_session_factory,
)
from app.modules.identity.router import router as identity_router
from app.modules.incidents.router import router as incidents_router
from app.modules.response.realtime import configure_realtime, sio
from app.modules.response.router import router as response_router
from app.modules.training.router import router as training_router

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Проверяет PostgreSQL при старте и освобождает соединения при остановке."""
    engine = create_database_engine(get_settings())
    application.state.database_engine = engine
    application.state.database_session_factory = create_session_factory(engine)
    configure_realtime(application.state.database_session_factory)

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(identity_router)
app.include_router(training_router)
app.include_router(incidents_router)
app.include_router(response_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Подтверждает, что backend запущен и принимает запросы."""
    return {"status": "ok", "service": "training-simulator-112"}


asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)

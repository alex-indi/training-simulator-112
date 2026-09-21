"""Точка входа FastAPI-приложения."""

from fastapi import FastAPI

app = FastAPI(
    title="Учебный тренажёр 112",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Подтверждает, что backend запущен и принимает запросы."""
    return {"status": "ok", "service": "training-simulator-112"}

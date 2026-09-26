"""Точка входа FastAPI-приложения."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import (
    check_database_connection,
    create_database_engine,
    create_session_factory,
)
from app.modules.admin.router import router as admin_router
from app.modules.identity.models import User, UserRole
from app.modules.identity.router import router as identity_router
from app.modules.incident_classifier.router import router as classifier_router
from app.modules.incidents.router import router as incidents_router
from app.modules.response.realtime import configure_realtime, sio
from app.modules.response.router import router as response_router
from app.modules.scenario_library.instances import (
    instance_router as scenario_instance_router,
)
from app.modules.scenario_library.instances import (
    session_router as session_instances_router,
)
from app.modules.scenario_library.instances import (
    template_router as scenario_generation_router,
)
from app.modules.scenario_library.router import router as scenario_library_router
from app.modules.scenario_library.saved_cards import router as incident_cards_router
from app.modules.training.assessment import router as assessment_router
from app.modules.training.control import router as control_router
from app.modules.training.delivery import router as delivery_router
from app.modules.training.delivery import scheduler_loop
from app.modules.training.models import TrainingSession, training_session_trainees
from app.modules.training.monitor import router as monitor_router
from app.modules.training.router import router as training_router
from app.modules.training.router import template_router
from app.modules.training.user_groups import router as trainee_groups_router
from app.realtime import publish_session_event

logger = logging.getLogger("uvicorn.error")
allowed_origins = get_settings().allowed_frontend_origins


async def notify_delivery(session_id: int, incident_id: int) -> None:
    await publish_session_event("incident.delivered", session_id, incident_id)


@sio.event
async def connect(sid: str, environ: dict, auth: dict | None) -> bool:
    username = auth.get("username") if isinstance(auth, dict) else None
    if not isinstance(username, str):
        return False
    async with app.state.database_session_factory() as database:
        user = (
            await database.scalars(
                select(User).where(
                    User.username == username.strip().lower(), User.is_active.is_(True)
                )
            )
        ).one_or_none()
    if user is None:
        return False
    await sio.save_session(sid, {"user_id": user.id, "role": user.role.value})
    await sio.enter_room(sid, f"user:{user.id}")
    return True


@sio.event
async def subscribe(sid: str, data: dict) -> None:
    session_id = data.get("session_id") if isinstance(data, dict) else None
    if not isinstance(session_id, int):
        return
    principal = await sio.get_session(sid)
    async with app.state.database_session_factory() as database:
        statement = select(TrainingSession.id).where(TrainingSession.id == session_id)
        if principal["role"] == UserRole.INSTRUCTOR.value:
            statement = statement.where(TrainingSession.instructor_id == principal["user_id"])
        elif principal["role"] == UserRole.TRAINEE.value:
            statement = statement.join(training_session_trainees).where(
                training_session_trainees.c.trainee_id == principal["user_id"]
            )
        elif principal["role"] != UserRole.ADMIN.value:
            return
        permitted = (await database.scalars(statement)).one_or_none()
    if permitted is not None:
        await sio.enter_room(sid, f"session:{session_id}")


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
        scheduler = asyncio.create_task(
            scheduler_loop(application.state.database_session_factory, notify_delivery)
        )
        try:
            yield
        finally:
            scheduler.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler
    finally:
        await engine.dispose()


app = FastAPI(
    title="Учебный тренажёр 112",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(identity_router)
app.include_router(classifier_router)
app.include_router(admin_router)
app.include_router(scenario_library_router)
app.include_router(incident_cards_router)
app.include_router(scenario_generation_router)
app.include_router(scenario_instance_router)
app.include_router(session_instances_router)
app.include_router(training_router)
app.include_router(trainee_groups_router)
app.include_router(control_router)
app.include_router(assessment_router)
app.include_router(monitor_router)
app.include_router(template_router)
app.include_router(delivery_router)
app.include_router(incidents_router)
app.include_router(response_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Подтверждает, что backend запущен и принимает запросы."""
    return {"status": "ok", "service": "training-simulator-112"}


socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
asgi_app = socket_app

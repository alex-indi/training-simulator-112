"""Socket.IO уведомления о новых сообщениях; история читается через REST."""

import socketio
from sqlalchemy import select

from app.modules.identity.models import User

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
)
_session_factory = None


def configure_realtime(session_factory) -> None:
    global _session_factory
    _session_factory = session_factory


@sio.event
async def connect(sid, environ, auth):
    if _session_factory is None:
        raise ConnectionRefusedError("База данных недоступна")
    username = ((auth or {}).get("username") or "").strip().lower()
    if not username:
        raise ConnectionRefusedError("Укажите пользователя")
    async with _session_factory() as database:
        user = await database.scalar(
            select(User).where(User.username == username, User.is_active.is_(True))
        )
    if user is None:
        raise ConnectionRefusedError("Пользователь не найден")
    await sio.enter_room(sid, f"user:{user.id}")


async def notify_message_created(message, trainee_id: int, session_id: int | None = None) -> None:
    """Передаёт только сигнал; полный список frontend перечитывает по REST."""
    await sio.emit(
        "response.message_created",
        {"assignment_id": message.response_assignment_id, "message_id": message.id},
        room=f"user:{trainee_id}",
    )
    if session_id is not None:
        await sio.emit(
            "response.message_created",
            {"assignment_id": message.response_assignment_id, "message_id": message.id},
            room=f"session:{session_id}",
        )

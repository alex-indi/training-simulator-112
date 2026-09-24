"""Small Socket.IO notification adapter; REST remains the canonical state."""


async def publish_session_event(event: str, session_id: int, incident_id: int | None) -> None:
    from app.main import sio

    await sio.emit(
        event,
        {"session_id": session_id, "incident_id": incident_id},
        room=f"session:{session_id}",
    )

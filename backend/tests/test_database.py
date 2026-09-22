"""Проверки базовой инфраструктуры PostgreSQL."""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import Settings
from app.db.base import Base
from app.db.session import create_database_engine, create_session_factory
from app.modules.identity.models import User
from app.modules.training.models import TrainingSession


def test_database_engine_uses_configured_url() -> None:
    """SQLAlchemy engine использует URL из backend-конфигурации."""
    database_url = "postgresql+asyncpg://user:password@localhost:5432/training"
    engine = create_database_engine(Settings(database_url=database_url, _env_file=None))

    assert isinstance(engine, AsyncEngine)
    assert engine.url.render_as_string(hide_password=False) == database_url
    assert Base.metadata.tables["users"] is User.__table__
    assert Base.metadata.tables["training_sessions"] is TrainingSession.__table__
    assert "training_session_trainees" in Base.metadata.tables

    session_factory = create_session_factory(engine)
    assert session_factory.class_ is AsyncSession
    assert session_factory.kw["expire_on_commit"] is False

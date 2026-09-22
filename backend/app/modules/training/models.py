"""SQLAlchemy-модели базовой учебной сессии."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Table, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.identity.models import User


class TrainingSessionState(StrEnum):
    """Состояния учебной сессии согласно доменной state machine."""

    DRAFT = "DRAFT"
    READY = "READY"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


training_session_trainees = Table(
    "training_session_trainees",
    Base.metadata,
    Column(
        "training_session_id",
        ForeignKey("training_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "trainee_id",
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column(
        "assigned_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
)


class TrainingSession(Base):
    """Занятие, которое преподаватель назначает одному или нескольким обучаемым."""

    __tablename__ = "training_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    instructor_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
    )
    state: Mapped[TrainingSessionState] = mapped_column(
        Enum(
            TrainingSessionState,
            name="training_session_state",
            validate_strings=True,
        ),
        default=TrainingSessionState.DRAFT,
        server_default=TrainingSessionState.DRAFT.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    instructor: Mapped[User] = relationship(foreign_keys=[instructor_id])
    trainees: Mapped[list[User]] = relationship(
        secondary=training_session_trainees,
        order_by=User.id,
    )

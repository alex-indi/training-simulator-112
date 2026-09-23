"""SQLAlchemy-модели базовой учебной сессии."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Table, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.identity.models import User

if TYPE_CHECKING:
    from app.modules.incidents.models import Incident


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
    incidents: Mapped[list[Incident]] = relationship(
        back_populates="training_session",
        cascade="all, delete-orphan",
    )
    runs: Mapped[list[TrainingRun]] = relationship(
        back_populates="training_session",
        cascade="all, delete-orphan",
    )


class TrainingRun(Base):
    """Участие одного обучаемого во всей учебной сессии."""

    __tablename__ = "training_runs"
    __table_args__ = (UniqueConstraint("training_session_id", "trainee_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    training_session_id: Mapped[int] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    trainee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    dds_profile: Mapped[str] = mapped_column(String(120), default="ДДС", server_default="ДДС")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    training_session: Mapped[TrainingSession] = relationship(back_populates="runs")
    trainee: Mapped[User] = relationship()
    incidents: Mapped[list[Incident]] = relationship(back_populates="training_run")

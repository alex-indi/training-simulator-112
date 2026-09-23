"""Справочник групп и состояние отдельных назначений."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.incidents.models import Incident
    from app.modules.training.models import TrainingRun


class ResponseAssignmentState(StrEnum):
    ASSIGNED = "ASSIGNED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    WORKING = "WORKING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ResponseMessageSender(StrEnum):
    DISPATCHER = "DISPATCHER"
    RESPONSE_UNIT = "RESPONSE_UNIT"
    SYSTEM = "SYSTEM"


message_sender_type = Enum(
    ResponseMessageSender, name="response_message_sender", validate_strings=True
)


assignment_state_type = Enum(
    ResponseAssignmentState,
    name="response_assignment_state",
    validate_strings=True,
)


class ResponseUnit(Base):
    """Повторно используемая виртуальная группа без runtime-состояния."""

    __tablename__ = "response_units"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    dds_profile: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    assignments: Mapped[list[ResponseAssignment]] = relationship(back_populates="response_unit")


class ResponseAssignment(Base):
    """Состояние одной группы в конкретном происшествии и TrainingRun."""

    __tablename__ = "response_assignments"
    __table_args__ = (UniqueConstraint("incident_id", "response_unit_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    response_unit_id: Mapped[int] = mapped_column(
        ForeignKey("response_units.id", ondelete="RESTRICT"), index=True
    )
    training_run_id: Mapped[int] = mapped_column(
        ForeignKey("training_runs.id", ondelete="RESTRICT"), index=True
    )
    state: Mapped[ResponseAssignmentState] = mapped_column(
        assignment_state_type,
        default=ResponseAssignmentState.ASSIGNED,
        server_default=ResponseAssignmentState.ASSIGNED.value,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    state_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    incident: Mapped[Incident] = relationship(back_populates="response_assignments")
    response_unit: Mapped[ResponseUnit] = relationship(back_populates="assignments")
    training_run: Mapped[TrainingRun] = relationship()
    events: Mapped[list[ResponseAssignmentEvent]] = relationship(
        back_populates="response_assignment",
        cascade="all, delete-orphan",
        order_by="ResponseAssignmentEvent.created_at, ResponseAssignmentEvent.id",
    )
    messages: Mapped[list[ResponseMessage]] = relationship(
        back_populates="response_assignment",
        cascade="all, delete-orphan",
        order_by="ResponseMessage.created_at, ResponseMessage.id",
    )


class ResponseAssignmentEvent(Base):
    """Неизменяемая история фактического состояния виртуальной группы."""

    __tablename__ = "response_assignment_events"
    __table_args__ = (UniqueConstraint("response_assignment_id", "event_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    response_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("response_assignments.id", ondelete="CASCADE"), index=True
    )
    from_state: Mapped[ResponseAssignmentState | None] = mapped_column(
        assignment_state_type, nullable=True
    )
    to_state: Mapped[ResponseAssignmentState] = mapped_column(assignment_state_type)
    event_key: Mapped[str] = mapped_column(String(120))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    response_assignment: Mapped[ResponseAssignment] = relationship(back_populates="events")


class ResponseMessage(Base):
    """Неизменяемое сообщение оперативного канала конкретного назначения."""

    __tablename__ = "response_messages"
    __table_args__ = (UniqueConstraint("response_assignment_id", "event_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    response_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("response_assignments.id", ondelete="CASCADE"), index=True
    )
    sender_type: Mapped[ResponseMessageSender] = mapped_column(message_sender_type)
    body: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    event_key: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    response_assignment: Mapped[ResponseAssignment] = relationship(back_populates="messages")

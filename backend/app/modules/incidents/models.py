"""SQLAlchemy-модель учебной карточки происшествия."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.identity.models import User
    from app.modules.training.models import TrainingSession


class IncidentLifecycleState(StrEnum):
    """Технический lifecycle учебной карточки, отдельный от статуса ДДС."""

    CREATED = "CREATED"
    DELIVERED = "DELIVERED"
    OPENED = "OPENED"
    FINISHED = "FINISHED"


class DDSResponseStatus(StrEnum):
    """Предметный статус реагирования ДДС по учебной карточке."""

    AWAITING_DECISION = "AWAITING_DECISION"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RESPONSE_STARTED = "RESPONSE_STARTED"
    ARRIVED = "ARRIVED"
    WORKING = "WORKING"
    COMPLETED = "COMPLETED"
    WORK_REFUSED = "WORK_REFUSED"


class IncidentActionType(StrEnum):
    """Команды, которыми обучаемый меняет предметный статус карточки."""

    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    START_RESPONSE = "START_RESPONSE"
    MARK_ARRIVAL = "MARK_ARRIVAL"
    START_WORK = "START_WORK"
    COMPLETE_WORK = "COMPLETE_WORK"
    REFUSE_WORK = "REFUSE_WORK"


class DdsServiceEventType(StrEnum):
    """Системные события истории оповещённой службы."""

    SERVICE_ADDED = "SERVICE_ADDED"
    SERVICE_RECEIVED = "SERVICE_RECEIVED"


json_type = JSON().with_variant(JSONB(), "postgresql")


class Incident(Base):
    """Готовая карточка, доставленная Virtual112 в учебную сессию."""

    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    training_session_id: Mapped[int] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    incident_number: Mapped[str] = mapped_column(String(64), index=True)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(120))
    applicant_name: Mapped[str | None] = mapped_column(String(200))
    applicant_phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text)
    incident_type: Mapped[str] = mapped_column(String(200))
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(json_type)
    lifecycle_state: Mapped[IncidentLifecycleState] = mapped_column(
        Enum(
            IncidentLifecycleState,
            name="incident_lifecycle_state",
            validate_strings=True,
        ),
        default=IncidentLifecycleState.CREATED,
        server_default=IncidentLifecycleState.CREATED.value,
        index=True,
    )
    dds_status: Mapped[DDSResponseStatus] = mapped_column(
        Enum(
            DDSResponseStatus,
            name="dds_response_status",
            validate_strings=True,
        ),
        default=DDSResponseStatus.AWAITING_DECISION,
        server_default=DDSResponseStatus.AWAITING_DECISION.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    primary_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    training_session: Mapped[TrainingSession] = relationship(back_populates="incidents")
    actions: Mapped[list[IncidentAction]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentAction.created_at, IncidentAction.id",
    )


class IncidentAction(Base):
    """Неизменяемая запись о значимом действии диспетчера ДДС."""

    __tablename__ = "incident_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        index=True,
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    actor_display_name: Mapped[str] = mapped_column(String(120))
    is_system: Mapped[bool] = mapped_column(default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(32))
    action: Mapped[IncidentActionType | None] = mapped_column(
        Enum(
            IncidentActionType,
            name="incident_action_type",
            validate_strings=True,
        ),
        nullable=True,
    )
    from_status: Mapped[DDSResponseStatus | None] = mapped_column(
        Enum(
            DDSResponseStatus,
            name="dds_response_status",
            validate_strings=True,
        ),
        nullable=True,
    )
    to_status: Mapped[DDSResponseStatus | None] = mapped_column(
        Enum(
            DDSResponseStatus,
            name="dds_response_status",
            validate_strings=True,
        ),
        nullable=True,
    )
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    incident: Mapped[Incident] = relationship(back_populates="actions")
    actor: Mapped[User | None] = relationship()

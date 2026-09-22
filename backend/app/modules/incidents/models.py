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
    from app.modules.training.models import TrainingSession


class IncidentLifecycleState(StrEnum):
    """Технический lifecycle учебной карточки, отдельный от статуса ДДС."""

    CREATED = "CREATED"
    DELIVERED = "DELIVERED"
    OPENED = "OPENED"
    FINISHED = "FINISHED"


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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    primary_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    training_session: Mapped[TrainingSession] = relationship(back_populates="incidents")

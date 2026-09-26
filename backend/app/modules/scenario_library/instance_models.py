"""Fixed scenario content prepared before a training session."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ScenarioInstance(Base):
    __tablename__ = "scenario_instances"
    __table_args__ = (CheckConstraint("difficulty BETWEEN 1 AND 5", name="ck_instance_difficulty"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_template_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_templates.id", ondelete="RESTRICT"), index=True
    )
    training_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="RESTRICT"), index=True
    )
    training_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_groups.id", ondelete="RESTRICT"), index=True
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(500))
    difficulty: Mapped[int] = mapped_column(Integer)
    generation_seed: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", server_default="DRAFT")
    classifier_snapshot: Mapped[dict] = mapped_column(JSON)
    object_snapshot: Mapped[dict] = mapped_column(JSON)
    service_snapshot: Mapped[list] = mapped_column(JSON)
    initial_state_snapshot: Mapped[dict] = mapped_column(JSON)
    expected_actions_snapshot: Mapped[list] = mapped_column(JSON)
    assessment_criteria_snapshot: Mapped[list] = mapped_column(JSON)
    template_snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    events: Mapped[list[ScenarioInstanceEvent]] = relationship(
        back_populates="instance",
        cascade="all, delete-orphan",
        order_by="ScenarioInstanceEvent.sequence_number",
    )


class SavedIncidentCard(Base):
    """Reusable copy of a prepared card, independent of its template and session."""

    __tablename__ = "saved_incident_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    source_template_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(500))
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScenarioInstanceEvent(Base):
    __tablename__ = "scenario_instance_events"
    __table_args__ = (CheckConstraint("offset_seconds >= 0", name="ck_instance_event_offset"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_instance_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_instances.id", ondelete="CASCADE"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer)
    offset_seconds: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(40))
    payload_snapshot: Mapped[dict] = mapped_column(JSON)

    instance: Mapped[ScenarioInstance] = relationship(back_populates="events")


class ScenarioRuntimeEvent(Base):
    """Prepared event; release facts stay separate from immutable instance content."""

    __tablename__ = "scenario_runtime_events"
    __table_args__ = (
        UniqueConstraint("incident_id", "scenario_instance_event_id"),
        CheckConstraint("offset_seconds >= 0", name="ck_runtime_event_offset"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    scenario_instance_event_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_instance_events.id", ondelete="RESTRICT")
    )
    event_type: Mapped[str] = mapped_column(String(40))
    offset_seconds: Mapped[int] = mapped_column(Integer)
    payload_snapshot: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", server_default="PENDING")
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incident = relationship("Incident")

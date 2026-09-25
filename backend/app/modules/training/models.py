"""SQLAlchemy-модели базовой учебной сессии."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
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


class TrainingMode(StrEnum):
    FLOW = "FLOW"
    FIXED_SET = "FIXED_SET"
    MANUAL = "MANUAL"


class DeliveryOrder(StrEnum):
    SEQUENTIAL = "SEQUENTIAL"
    RANDOM = "RANDOM"


class QueueMode(StrEnum):
    INDIVIDUAL_QUEUE = "INDIVIDUAL_QUEUE"
    SHARED_QUEUE = "SHARED_QUEUE"


class DeliveryState(StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"


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
    topic: Mapped[str] = mapped_column(String(200), default="", server_default="")
    mode: Mapped[TrainingMode] = mapped_column(
        Enum(TrainingMode, name="training_mode"),
        default=TrainingMode.MANUAL,
        server_default="MANUAL",
    )
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    delivery_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    delivery_order: Mapped[DeliveryOrder] = mapped_column(
        Enum(DeliveryOrder, name="delivery_order"),
        default=DeliveryOrder.SEQUENTIAL,
        server_default="SEQUENTIAL",
    )
    workstation_count: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
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
    delivery_elapsed_seconds: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    delivery_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_seconds: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    finish_mode: Mapped[str | None] = mapped_column(String(20))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
    groups: Mapped[list[TrainingGroup]] = relationship(
        back_populates="training_session", cascade="all, delete-orphan"
    )
    queue_items: Mapped[list[ScenarioQueueItem]] = relationship(
        back_populates="training_session", cascade="all, delete-orphan"
    )
    pauses: Mapped[list[SessionPause]] = relationship(order_by="SessionPause.started_at")


class TrainingRun(Base):
    """Участие одного обучаемого во всей учебной сессии."""

    __tablename__ = "training_runs"
    __table_args__ = (
        UniqueConstraint("training_session_id", "trainee_id"),
        UniqueConstraint("training_session_id", "workstation_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    training_session_id: Mapped[int] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    trainee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    dds_profile: Mapped[str] = mapped_column(String(120), default="ДДС", server_default="ДДС")
    workstation_number: Mapped[int | None] = mapped_column(Integer)
    difficulty: Mapped[str | None] = mapped_column(String(40))
    queue_mode: Mapped[QueueMode] = mapped_column(
        Enum(QueueMode, name="queue_mode"),
        default=QueueMode.INDIVIDUAL_QUEUE,
        server_default="INDIVIDUAL_QUEUE",
    )
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_groups.id", ondelete="SET NULL")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_seconds: Mapped[float] = mapped_column(Float, default=0, server_default="0")

    training_session: Mapped[TrainingSession] = relationship(back_populates="runs")
    trainee: Mapped[User] = relationship()
    incidents: Mapped[list[Incident]] = relationship(
        back_populates="training_run", foreign_keys="Incident.training_run_id"
    )
    group: Mapped[TrainingGroup | None] = relationship(back_populates="runs")
    pauses: Mapped[list[RunPause]] = relationship(order_by="RunPause.started_at")


class TrainingGroup(Base):
    """Группа учебной смены, редактируемая только до запуска."""

    __tablename__ = "training_groups"
    __table_args__ = (UniqueConstraint("training_session_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    training_session_id: Mapped[int] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    dds_profile: Mapped[str | None] = mapped_column(String(120))
    difficulty: Mapped[str | None] = mapped_column(String(40))
    queue_mode: Mapped[QueueMode] = mapped_column(
        Enum(QueueMode, name="queue_mode"),
        default=QueueMode.INDIVIDUAL_QUEUE,
        server_default="INDIVIDUAL_QUEUE",
    )

    training_session: Mapped[TrainingSession] = relationship(back_populates="groups")
    runs: Mapped[list[TrainingRun]] = relationship(back_populates="group")


class TrainingTemplate(Base):
    """Настройки занятия и групп без привязки к обучаемым."""

    __tablename__ = "training_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    instructor_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    settings: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainingScenario(Base):
    """Сценарий преподавателя; выданные карточки хранят собственный snapshot."""

    __tablename__ = "training_scenarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    instructor_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    snapshot: Mapped[dict] = mapped_column(JSON)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScenarioQueueItem(Base):
    """Утверждённая позиция занятия с сохранённым порядком выдачи."""

    __tablename__ = "scenario_queue_items"
    __table_args__ = (
        UniqueConstraint("training_session_id", "position"),
        CheckConstraint(
            "(training_run_id IS NULL) <> (training_group_id IS NULL)",
            name="ck_queue_target",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    training_session_id: Mapped[int] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    training_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_runs.id", ondelete="RESTRICT"), index=True
    )
    training_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_groups.id", ondelete="RESTRICT"), index=True
    )
    scenario_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_scenarios.id", ondelete="SET NULL")
    )
    scenario_instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("scenario_instances.id", ondelete="RESTRICT"), unique=True
    )
    title: Mapped[str] = mapped_column(String(200))
    snapshot: Mapped[dict] = mapped_column(JSON)
    position: Mapped[int] = mapped_column(Integer)
    delivery_position: Mapped[int | None] = mapped_column(Integer)
    approved: Mapped[bool] = mapped_column(default=False, server_default="false")
    delivery_state: Mapped[DeliveryState] = mapped_column(
        Enum(DeliveryState, name="delivery_state"),
        default=DeliveryState.PENDING,
        server_default="PENDING",
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incident_id: Mapped[int | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"), unique=True
    )
    training_session: Mapped[TrainingSession] = relationship(back_populates="queue_items")
    training_run: Mapped[TrainingRun] = relationship()
    scenario: Mapped[TrainingScenario | None] = relationship()


class InstructorAction(Base):
    """Неизменяемый журнал управления учебной сменой."""

    __tablename__ = "instructor_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    training_session_id: Mapped[int] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    instructor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionPause(Base):
    __tablename__ = "session_pauses"
    id: Mapped[int] = mapped_column(primary_key=True)
    training_session_id: Mapped[int] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    instructor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)


class RunPause(Base):
    __tablename__ = "run_pauses"
    id: Mapped[int] = mapped_column(primary_key=True)
    training_run_id: Mapped[int] = mapped_column(
        ForeignKey("training_runs.id", ondelete="CASCADE"), index=True
    )
    instructor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)


class InstructorNote(Base):
    __tablename__ = "instructor_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    training_run_id: Mapped[int] = mapped_column(
        ForeignKey("training_runs.id", ondelete="CASCADE"), index=True
    )
    instructor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssessmentResult(Base):
    """Зафиксированный автоматический расчёт и отдельно утверждённый итог."""

    __tablename__ = "assessment_results"
    __table_args__ = (UniqueConstraint("training_run_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    training_run_id: Mapped[int] = mapped_column(
        ForeignKey("training_runs.id", ondelete="CASCADE"), index=True
    )
    automatic_score: Mapped[int] = mapped_column(Integer)
    final_score: Mapped[int | None] = mapped_column(Integer)
    score_override: Mapped[int | None] = mapped_column(Integer)
    final_comment: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    metrics: Mapped[dict] = mapped_column(JSON)
    deviations: Mapped[list[AssessmentDeviation]] = relationship(
        back_populates="result", cascade="all, delete-orphan", order_by="AssessmentDeviation.id"
    )


class AssessmentDeviation(Base):
    __tablename__ = "assessment_deviations"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_result_id: Mapped[int] = mapped_column(
        ForeignKey("assessment_results.id", ondelete="CASCADE"), index=True
    )
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text)
    weight: Mapped[int] = mapped_column(Integer)
    critical: Mapped[bool] = mapped_column(default=False, server_default="false")
    decision: Mapped[str] = mapped_column(String(20), default="PENDING", server_default="PENDING")
    is_manual: Mapped[bool] = mapped_column(default=False, server_default="false")

    result: Mapped[AssessmentResult] = relationship(back_populates="deviations")


class AssessmentAudit(Base):
    __tablename__ = "assessment_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_result_id: Mapped[int] = mapped_column(
        ForeignKey("assessment_results.id", ondelete="CASCADE"), index=True
    )
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    action: Mapped[str] = mapped_column(String(40))
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)


class ScenarioEvent(Base):
    __tablename__ = "scenario_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    instructor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    origin: Mapped[str] = mapped_column(
        String(20), default="INSTRUCTOR", server_default="INSTRUCTOR"
    )
    scenario_instance_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("scenario_instance_events.id", ondelete="RESTRICT"), unique=True
    )
    kind: Mapped[str] = mapped_column(String(60))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

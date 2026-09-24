"""API-схемы подготовки учебной смены."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.incidents.schemas import IncidentSnapshot
from app.modules.training.models import (
    DeliveryOrder,
    DeliveryState,
    QueueMode,
    TrainingMode,
    TrainingSessionState,
)


class SessionSettings(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(default="", max_length=200)
    mode: TrainingMode = TrainingMode.MANUAL
    duration_minutes: int | None = Field(default=None, ge=1, le=480)
    delivery_interval_seconds: int | None = Field(default=None, ge=10, le=3600)
    delivery_order: DeliveryOrder = DeliveryOrder.SEQUENTIAL
    workstation_count: int = Field(default=30, ge=1, le=100)

    @field_validator("title", "topic")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_schedule(self) -> "SessionSettings":
        if not self.title:
            raise ValueError("Название занятия не может быть пустым")
        if self.mode == TrainingMode.FLOW and (
            not self.duration_minutes or not self.delivery_interval_seconds
        ):
            raise ValueError("Для FLOW нужны продолжительность и интервал выдачи")
        return self


class TrainingSessionCreate(SessionSettings):
    trainee_ids: list[int] = Field(default_factory=list)

    @field_validator("trainee_ids")
    @classmethod
    def reject_duplicate_trainees(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("Обучаемые в сессии не должны повторяться")
        return value


class TrainingSessionUpdate(SessionSettings):
    pass


class RunRead(BaseModel):
    id: int
    trainee_id: int
    trainee_name: str
    workstation_number: int | None
    dds_profile: str | None
    difficulty: str | None
    queue_mode: QueueMode
    group_id: int | None
    online: bool
    last_seen_at: datetime | None
    paused_at: datetime | None = None


class OwnRunSummary(BaseModel):
    id: int
    workstation_number: int | None
    dds_profile: str | None
    online: bool
    paused_at: datetime | None = None


class TrainingSessionSummary(BaseModel):
    id: int
    title: str
    state: TrainingSessionState
    workstation_count: int
    own_run: OwnRunSummary | None = None
    paused_at: datetime | None = None


class GroupWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    dds_profile: str | None = Field(default=None, max_length=120)
    difficulty: str | None = Field(default=None, max_length=40)
    queue_mode: QueueMode = QueueMode.INDIVIDUAL_QUEUE

    @field_validator("name", "dds_profile", "difficulty")
    @classmethod
    def normalize_group_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Поле группы не может быть пустым")
        return normalized


class GroupRead(GroupWrite):
    id: int
    run_ids: list[int]


class JoinRequest(BaseModel):
    workstation_number: int = Field(ge=1, le=100)


class BulkAssignment(BaseModel):
    run_ids: list[int] = Field(min_length=1)
    dds_profile: str | None = Field(default=None, max_length=120)
    difficulty: str | None = Field(default=None, max_length=40)
    queue_mode: QueueMode | None = None
    group_id: int | None = None


class ReadinessRead(BaseModel):
    participant_count: int
    workstation_count: int
    group_count: int
    profiles_assigned: int
    online_count: int
    offline_count: int
    warnings: list[str]
    can_start: bool
    prepared_count: int = 0
    approved_count: int = 0


class TrainingSessionRead(SessionSettings):
    id: int
    instructor_id: int
    trainee_ids: list[int]
    state: TrainingSessionState
    created_at: datetime
    started_at: datetime | None
    paused_at: datetime | None = None
    paused_seconds: float = 0
    finish_mode: str | None = None
    completed_at: datetime | None = None
    runs: list[RunRead] = Field(default_factory=list)
    groups: list[GroupRead] = Field(default_factory=list)
    readiness: ReadinessRead | None = None


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    training_session_id: int

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Название шаблона не может быть пустым")
        return normalized


class TemplateRead(BaseModel):
    id: int
    name: str
    settings: dict
    created_at: datetime


class QueueItemWrite(BaseModel):
    training_run_id: int | None = Field(default=None, gt=0)
    training_group_id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=200)
    snapshot: IncidentSnapshot

    @model_validator(mode="after")
    def one_target(self) -> "QueueItemWrite":
        if (self.training_run_id is None) == (self.training_group_id is None):
            raise ValueError("Укажите один АРМ или одну группу")
        return self


class QueueItemUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    snapshot: IncidentSnapshot


class QueueItemRead(BaseModel):
    id: int
    training_run_id: int | None
    training_group_id: int | None
    scenario_id: int | None
    scenario_instance_id: int | None = None
    title: str
    snapshot: IncidentSnapshot
    position: int
    delivery_position: int | None
    approved: bool
    delivery_state: DeliveryState
    delivered_at: datetime | None
    incident_id: int | None


class GenerateQueueRequest(BaseModel):
    count_per_run: int = Field(ge=1, le=100)

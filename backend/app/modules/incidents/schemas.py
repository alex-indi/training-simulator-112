"""API-схемы готовой карточки происшествия."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.incidents.models import (
    DDSResponseStatus,
    IncidentActionType,
    IncidentLifecycleState,
)


class IncidentSnapshot(BaseModel):
    """Исходные данные сценария, копируемые в карточку при доставке."""

    model_config = ConfigDict(extra="allow")

    incident_number: str = Field(min_length=1, max_length=64)
    reported_at: datetime
    source: str = Field(min_length=1, max_length=120)
    applicant_name: str | None = Field(default=None, max_length=200)
    applicant_phone: str | None = Field(default=None, max_length=50)
    address: str = Field(min_length=1, max_length=1000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    description: str = Field(min_length=1, max_length=5000)
    features: list[str] = Field(default_factory=list)
    incident_type: str = Field(min_length=1, max_length=200)
    notified_services: list[str] = Field(default_factory=list)

    @field_validator(
        "incident_number",
        "source",
        "applicant_name",
        "applicant_phone",
        "address",
        "description",
        "incident_type",
    )
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        """Нормализует текст, сохраняя допустимые необязательные поля."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Текстовое поле не может быть пустым")
        return normalized

    @field_validator("features", "notified_services")
    @classmethod
    def normalize_text_list(cls, value: list[str]) -> list[str]:
        """Убирает лишние пробелы и пустые элементы из списков карточки."""
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("Элементы списка не могут быть пустыми")
        return normalized

    @field_validator("reported_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Требует однозначное время исходного сообщения в API."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Время сообщения должно содержать часовой пояс")
        return value


class IncidentCreate(BaseModel):
    """Команда Virtual112 на создание и доставку готовой карточки."""

    training_session_id: int = Field(gt=0)
    trainee_id: int | None = Field(default=None, gt=0)
    training_group_id: int | None = Field(default=None, gt=0)
    source_snapshot: IncidentSnapshot


class IncidentActionCreate(BaseModel):
    """Команда обучаемого на изменение статуса реагирования ДДС."""

    action: IncidentActionType
    order_number: str | None = Field(default=None, max_length=80)
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("order_number", "comment")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class IncidentActionRead(BaseModel):
    """Запись неизменяемой истории действий по карточке."""

    id: int
    actor_user_id: int | None
    actor_display_name: str
    is_system: bool
    status: str
    action: IncidentActionType | None
    from_status: DDSResponseStatus | None
    to_status: DDSResponseStatus | None
    order_number: str | None
    comment: str | None
    created_at: datetime


class IncidentRead(BaseModel):
    """Каноническое состояние карточки из backend."""

    id: int
    training_session_id: int
    scenario_instance_id: int | None = None
    training_run_id: int | None
    training_group_id: int | None = None
    claimed_by_training_run_id: int | None = None
    claimed_at: datetime | None = None
    claimant_name: str | None = None
    claimant_workstation_number: int | None = None
    can_claim: bool = False
    can_edit: bool = False
    viewer_dds_profile: str | None = None
    viewer_workstation_number: int | None = None
    incident_number: str
    reported_at: datetime
    source: str
    applicant_name: str | None
    applicant_phone: str | None
    address: str
    latitude: float | None
    longitude: float | None
    description: str
    incident_type: str
    source_snapshot: IncidentSnapshot
    lifecycle_state: IncidentLifecycleState
    dds_status: DDSResponseStatus
    available_actions: list[IncidentActionType]
    actions: list[IncidentActionRead]
    scenario_events: list[dict] = Field(default_factory=list)
    activities: list[dict] = Field(default_factory=list)
    created_at: datetime
    delivered_at: datetime | None
    opened_at: datetime | None
    primary_status_at: datetime | None
    primary_response_duration_seconds: float | None
    finished_at: datetime | None

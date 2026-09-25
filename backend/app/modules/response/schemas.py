"""REST-схемы групп и назначений реагирования."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.response.models import ResponseAssignmentState, ResponseMessageSender


class ResponseUnitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    dds_profile: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)

    @field_validator("name", "dds_profile")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Обязательное поле не может быть пустым")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()


class ResponseUnitRead(BaseModel):
    id: int
    name: str
    dds_profile: str
    description: str
    is_active: bool


class ResponseAssignmentCreate(BaseModel):
    response_unit_id: int = Field(gt=0)
    dispatch_service_id: int | None = Field(default=None, gt=0)


class ResponseScenarioEventCreate(BaseModel):
    event_key: str = Field(min_length=1, max_length=120)
    target_state: ResponseAssignmentState

    @field_validator("event_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or normalized == "assigned":
            raise ValueError("Укажите уникальный ключ сценарного события")
        return normalized


class ResponseAssignmentEventRead(BaseModel):
    id: int
    from_state: ResponseAssignmentState | None
    to_state: ResponseAssignmentState
    event_key: str
    actor_user_id: int | None
    created_at: datetime


class ResponseAssignmentRead(BaseModel):
    id: int
    incident_id: int
    response_unit: ResponseUnitRead
    dispatch_service_id: int | None
    training_run_id: int
    state: ResponseAssignmentState
    assigned_at: datetime
    state_changed_at: datetime
    events: list[ResponseAssignmentEventRead]


class ResponseMessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Сообщение не может быть пустым")
        return value


class ResponseScenarioMessageCreate(ResponseMessageCreate):
    event_key: str = Field(min_length=1, max_length=120)

    @field_validator("event_key")
    @classmethod
    def normalize_message_key(cls, value: str) -> str:
        value = value.strip()
        if not value or value.startswith("state:"):
            raise ValueError("Укажите ключ сценарного сообщения без префикса state:")
        return value


class ResponseMessageRead(BaseModel):
    id: int
    response_assignment_id: int
    sender_type: ResponseMessageSender
    body: str
    actor_user_id: int | None
    created_at: datetime
    read_at: datetime | None

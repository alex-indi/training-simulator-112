"""API-схемы учебных сессий."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.training.models import TrainingSessionState


class TrainingSessionCreate(BaseModel):
    """Данные новой учебной сессии."""

    title: str = Field(min_length=1, max_length=200)
    trainee_ids: list[int] = Field(min_length=1)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        """Убирает случайные пробелы и запрещает пустое название."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Название сессии не может быть пустым")
        return normalized

    @field_validator("trainee_ids")
    @classmethod
    def reject_duplicate_trainees(cls, value: list[int]) -> list[int]:
        """Не позволяет дважды назначить одного обучаемого."""
        if len(value) != len(set(value)):
            raise ValueError("Обучаемые в сессии не должны повторяться")
        return value


class TrainingSessionRead(BaseModel):
    """Каноническое состояние учебной сессии из backend."""

    id: int
    title: str
    instructor_id: int
    trainee_ids: list[int]
    state: TrainingSessionState
    created_at: datetime
    started_at: datetime | None

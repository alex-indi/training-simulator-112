"""API-схемы пользователей тренажёра."""

from pydantic import BaseModel, ConfigDict

from app.modules.identity.models import UserRole


class UserRead(BaseModel):
    """Описывает публичные данные пользователя локального стенда."""

    id: int
    username: str
    full_name: str
    role: UserRole

    model_config = ConfigDict(from_attributes=True)

"""API-схемы пользователей тренажёра."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.models import UserRole


class UserRead(BaseModel):
    """Описывает публичные данные пользователя локального стенда."""

    id: int
    username: str
    full_name: str
    role: UserRole

    model_config = ConfigDict(from_attributes=True)


class UserLogin(BaseModel):
    """Credentials accepted by the local training login form."""

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class WorkstationClaim(BaseModel):
    workstation_number: int = Field(ge=1, le=100)


class WorkstationPresenceRead(BaseModel):
    user_id: int
    trainee_name: str
    workstation_number: int
    last_seen_at: datetime

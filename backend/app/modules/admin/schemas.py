"""Pydantic contracts for the administrative API."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.models import UserRole


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50, pattern=r"^[a-zA-Z0-9._-]+$")
    full_name: str = Field(min_length=2, max_length=120)
    role: UserRole
    password: str = Field(min_length=8, max_length=128)
    group_id: int | None = None


class UserUpdate(BaseModel):
    username: str | None = Field(
        default=None,
        min_length=2,
        max_length=50,
        pattern=r"^[a-zA-Z0-9._-]+$",
    )
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: UserRole | None = None
    is_active: bool | None = None
    group_id: int | None = None


class AdminUserRead(BaseModel):
    id: int
    username: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None
    group_id: int | None = None
    model_config = ConfigDict(from_attributes=True)


class UserGroupCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=1000)


class UserGroupRead(UserGroupCreate):
    id: int
    member_count: int


class UserGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=1000)


class ObjectTypeWrite(BaseModel):
    code: str = Field(min_length=2, max_length=120, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=2, max_length=250)
    description: str = Field(default="", max_length=2000)
    parent_id: int | None = None


class ObjectTypeUpdate(BaseModel):
    code: str | None = Field(
        default=None, min_length=2, max_length=120, pattern=r"^[A-Z0-9_]+$"
    )
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    parent_id: int | None = None
    is_active: bool | None = None


class ObjectTypeRead(ObjectTypeWrite):
    id: int
    description: str | None
    is_active: bool
    model_config = ConfigDict(from_attributes=True)


class ClassifierRead(BaseModel):
    id: int
    source_code: str | None
    incident_group: str
    feature_1: str | None
    feature_2: str | None
    feature_3: str | None
    incident_type: str
    related_services: list
    related_service_ids: list[int]
    source: str = "SRC-006"


class ClassifierUpdate(BaseModel):
    source_code: str | None = Field(default=None, max_length=160)
    incident_group: str | None = Field(default=None, min_length=1, max_length=1000)
    incident_type: str | None = Field(default=None, min_length=1, max_length=1000)
    feature_names: list[str] | None = Field(default=None, max_length=3)
    related_service_ids: list[int] | None = None


class ServiceRead(BaseModel):
    id: int
    official_name: str
    service_type: str
    level: str | None
    organization: str | None
    source: str
    data_status: str
    external_id: str


class ServiceUpdate(BaseModel):
    official_name: str | None = Field(default=None, min_length=1, max_length=2000)
    level: str | None = Field(default=None, max_length=120)
    organization: str | None = Field(default=None, max_length=2000)
    external_id: str | None = Field(default=None, min_length=1, max_length=500)


class RegistryObjectRead(BaseModel):
    id: int
    official_name: str
    object_type_id: int | None
    address: str
    district: str | None
    administrative_area: str | None
    latitude: float | None
    longitude: float | None
    tags: list
    attributes: dict
    source: str
    dataset_id: str
    external_id: str


class RegistryObjectUpdate(BaseModel):
    official_name: str | None = Field(default=None, min_length=1, max_length=500)
    object_type_id: int | None = None
    address: str | None = Field(default=None, max_length=4000)
    district: str | None = Field(default=None, max_length=250)
    administrative_area: str | None = Field(default=None, max_length=250)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    tags: list[str] | None = None
    attributes: dict[str, Any] | None = None
    source: str | None = Field(default=None, min_length=1, max_length=250)
    dataset_id: str | None = Field(default=None, max_length=250)
    external_id: str | None = Field(default=None, min_length=1, max_length=250)


class ImportRunRead(BaseModel):
    id: int
    source: str
    dataset_id: str | None
    status: str
    received: int
    created: int
    updated: int
    skipped: int
    review: int
    errors: int
    details: dict
    started_at: datetime
    finished_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class DataQualityRead(BaseModel):
    id: int
    kind: str
    reason: str
    entity_type: str
    entity_id: str | None
    status: str
    details: dict
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AIConfigBase(BaseModel):
    provider: str = Field(min_length=2, max_length=80)
    model: str = Field(max_length=160)
    base_url: str = Field(min_length=8, max_length=500)
    enabled: bool
    timeout_seconds: int = Field(ge=1, le=300)


class AIConfigUpdate(AIConfigBase):
    api_key: str | None = Field(default=None, min_length=1, max_length=1000, exclude=True)


class AIConfigRead(AIConfigBase):
    api_key_configured: bool
    updated_at: datetime | None


class AIModelCatalogRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=80)
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str | None = Field(default=None, min_length=1, max_length=1000, exclude=True)


class AIModelCatalogRead(BaseModel):
    models: list[str]


class AIUsageRead(BaseModel):
    day: date
    requests: int
    input_tokens: int
    output_tokens: int
    fallbacks: int
    errors: int
    model_config = ConfigDict(from_attributes=True)


class AuditRead(BaseModel):
    id: int
    admin_id: int
    action: str
    entity_type: str
    entity_id: str | None
    before: dict | None
    after: dict | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ScenarioAdminRead(BaseModel):
    id: int
    title: str
    author_id: int
    author: str
    status: str
    difficulty: int | None
    incident_type: str | None
    updated_at: datetime
    archived: bool


class Page(BaseModel):
    items: list[Any]
    total: int

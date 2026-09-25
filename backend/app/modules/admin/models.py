"""Persistent administrative catalogues, settings and audit records."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ImportRun(Base):
    __tablename__ = "import_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(120), index=True)
    dataset_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), index=True)
    received: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    review: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    errors: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(120), index=True)
    reason: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(
        String(40), default="OPEN", server_default="OPEN", index=True
    )
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIProviderConfig(Base):
    __tablename__ = "ai_provider_config"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(
        String(80), default="OPENAI_COMPATIBLE", server_default="OPENAI_COMPATIBLE"
    )
    model: Mapped[str] = mapped_column(String(160), default="", server_default="")
    base_url: Mapped[str] = mapped_column(
        String(500), default="https://api.openai.com/v1", server_default="https://api.openai.com/v1"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AIUsageDaily(Base):
    __tablename__ = "ai_usage_daily"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    fallbacks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    errors: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class AdminAudit(Base):
    __tablename__ = "admin_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(160))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class UserGroup(Base):
    """Named cohort used to organize trainee accounts in the admin panel."""

    __tablename__ = "user_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

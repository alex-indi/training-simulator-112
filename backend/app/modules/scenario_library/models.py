"""Повторно используемые методические шаблоны, независимые от очереди занятия."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.incident_classifier.models import IncidentClassifierRule
from app.modules.object_registry.models import CityObject


class ScenarioTemplate(Base):
    __tablename__ = "scenario_templates"
    __table_args__ = (CheckConstraint("difficulty BETWEEN 1 AND 5", name="ck_scenario_difficulty"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    seed_code: Mapped[str | None] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(20), default="DRAFT", server_default="DRAFT", index=True
    )
    difficulty: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    classifier_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("incident_classifier_rules.id", ondelete="RESTRICT"), index=True
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    initial_title: Mapped[str] = mapped_column(String(200), default="", server_default="")
    initial_description: Mapped[str] = mapped_column(Text, default="", server_default="")
    initial_caller_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    classifier_rule: Mapped[IncidentClassifierRule | None] = relationship()
    object_rule: Mapped[ScenarioTemplateObjectRule | None] = relationship(
        back_populates="template", cascade="all, delete-orphan", uselist=False
    )
    events: Mapped[list[ScenarioEventTemplate]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="ScenarioEventTemplate.sequence_number",
    )
    services: Mapped[list[ScenarioTemplateService]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )
    expected_actions: Mapped[list[ScenarioExpectedAction]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="ScenarioExpectedAction.id",
    )
    criteria: Mapped[list[ScenarioAssessmentCriterion]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="ScenarioAssessmentCriterion.id",
    )


class ScenarioTemplateObjectRule(Base):
    __tablename__ = "scenario_template_object_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_template_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_templates.id", ondelete="CASCADE"), unique=True
    )
    selection_mode: Mapped[str] = mapped_column(String(20))
    object_type_id: Mapped[int] = mapped_column(ForeignKey("object_types.id", ondelete="RESTRICT"))
    specific_object_id: Mapped[int | None] = mapped_column(
        ForeignKey("city_objects.id", ondelete="RESTRICT")
    )
    specific_object: Mapped[CityObject | None] = relationship()
    template: Mapped[ScenarioTemplate] = relationship(back_populates="object_rule")
    required_tags: Mapped[list[ScenarioTemplateRequiredObjectTag]] = relationship(
        cascade="all, delete-orphan", order_by="ScenarioTemplateRequiredObjectTag.tag"
    )


class ScenarioTemplateRequiredObjectTag(Base):
    __tablename__ = "scenario_template_required_object_tags"
    object_rule_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_template_object_rules.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(
        String(120),
        ForeignKey("object_tags_dictionary.code", ondelete="RESTRICT"),
        primary_key=True,
    )


class ScenarioEventTemplate(Base):
    __tablename__ = "scenario_event_templates"
    __table_args__ = (CheckConstraint("offset_seconds >= 0", name="ck_scenario_event_offset"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_template_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_templates.id", ondelete="CASCADE"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer)
    offset_seconds: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    source_type: Mapped[str] = mapped_column(String(40), default="SYSTEM", server_default="SYSTEM")
    template: Mapped[ScenarioTemplate] = relationship(back_populates="events")


class ScenarioTemplateService(Base):
    __tablename__ = "scenario_template_services"
    scenario_template_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_templates.id", ondelete="CASCADE"), primary_key=True
    )
    service_id: Mapped[int] = mapped_column(
        ForeignKey("dispatch_services.id", ondelete="RESTRICT"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(20))
    template: Mapped[ScenarioTemplate] = relationship(back_populates="services")


class ScenarioExpectedAction(Base):
    __tablename__ = "scenario_expected_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_template_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_templates.id", ondelete="CASCADE"), index=True
    )
    expected_action_type: Mapped[str] = mapped_column(String(80))
    target_status: Mapped[str | None] = mapped_column(String(80))
    expected_service_id: Mapped[int | None] = mapped_column(
        ForeignKey("dispatch_services.id", ondelete="RESTRICT")
    )
    deadline_seconds: Mapped[int | None] = mapped_column(Integer)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    template: Mapped[ScenarioTemplate] = relationship(back_populates="expected_actions")


class ScenarioAssessmentCriterion(Base):
    __tablename__ = "scenario_assessment_criteria"
    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_template_id: Mapped[int] = mapped_column(
        ForeignKey("scenario_templates.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    weight: Mapped[int | None] = mapped_column(Integer)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    template: Mapped[ScenarioTemplate] = relationship(back_populates="criteria")

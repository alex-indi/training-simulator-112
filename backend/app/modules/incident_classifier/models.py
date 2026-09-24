"""Классификатор SRC-006 и каталог служб без сценарной логики."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class IncidentClassifierRule(Base):
    """Одна строка исходного классификатора; source_reference содержит лист и строку."""

    __tablename__ = "incident_classifier_rules"
    __table_args__ = (UniqueConstraint("source_reference"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_code: Mapped[str | None] = mapped_column(String(160))
    incident_group: Mapped[str] = mapped_column(Text)
    final_incident_type: Mapped[str] = mapped_column(Text)
    ekp35_type: Mapped[str | None] = mapped_column(Text)
    source_reference: Mapped[str] = mapped_column(String(500))

    features: Mapped[list[IncidentRuleFeature]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )
    services: Mapped[list[IncidentRuleService]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class IncidentFeature(Base):
    """Значение признака из конкретной колонки SRC-006."""

    __tablename__ = "incident_features"
    __table_args__ = (UniqueConstraint("level", "source_column", "source_value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(80))
    source_column: Mapped[str] = mapped_column(String(160))
    source_value: Mapped[str] = mapped_column(Text)


class IncidentRuleFeature(Base):
    __tablename__ = "incident_rule_features"

    rule_id: Mapped[int] = mapped_column(
        ForeignKey("incident_classifier_rules.id", ondelete="CASCADE"), primary_key=True
    )
    feature_id: Mapped[int] = mapped_column(
        ForeignKey("incident_features.id", ondelete="RESTRICT"), primary_key=True
    )
    rule: Mapped[IncidentClassifierRule] = relationship(back_populates="features")
    feature: Mapped[IncidentFeature] = relationship()


class DispatchService(Base):
    """Запись из предоставленного каталога служб с неизменённым официальным именем."""

    __tablename__ = "dispatch_services"
    __table_args__ = (UniqueConstraint("source_reference"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    official_name: Mapped[str] = mapped_column(Text)
    organization: Mapped[str | None] = mapped_column(Text)
    service_level: Mapped[str | None] = mapped_column(String(120))
    source_reference: Mapped[str] = mapped_column(String(500))


class IncidentRuleService(Base):
    """Только подтверждённая источником рекомендация службы для правила."""

    __tablename__ = "incident_rule_services"

    rule_id: Mapped[int] = mapped_column(
        ForeignKey("incident_classifier_rules.id", ondelete="CASCADE"), primary_key=True
    )
    service_id: Mapped[int] = mapped_column(
        ForeignKey("dispatch_services.id", ondelete="RESTRICT"), primary_key=True
    )
    source_reference: Mapped[str] = mapped_column(String(500))
    rule: Mapped[IncidentClassifierRule] = relationship(back_populates="services")
    service: Mapped[DispatchService] = relationship()

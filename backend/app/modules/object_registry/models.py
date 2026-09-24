"""Типы, объекты, атрибуты и теги источников городских данных."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ObjectType(Base):
    """Тип из редактируемого справочника; parent задаёт произвольную иерархию."""

    __tablename__ = "object_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(250))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("object_types.id", ondelete="RESTRICT"), index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(250))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    parent: Mapped[ObjectType | None] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[ObjectType]] = relationship(back_populates="parent")


class CityObject(Base):
    """Объект с идентичностью и географией исходного набора данных."""

    __tablename__ = "city_objects"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_city_objects_source_external_id"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_city_objects_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_city_objects_longitude"),
        Index("ix_city_objects_external_id", "external_id"),
        Index("ix_city_objects_district", "district"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(250))
    name: Mapped[str] = mapped_column(String(500))
    object_type_id: Mapped[int] = mapped_column(
        ForeignKey("object_types.id", ondelete="RESTRICT"), index=True
    )
    address: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(String(250))
    administrative_area: Mapped[str | None] = mapped_column(String(250))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    source: Mapped[str] = mapped_column(String(250))
    source_dataset_id: Mapped[str | None] = mapped_column(String(250))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    object_type: Mapped[ObjectType] = relationship()
    attributes: Mapped[list[ObjectAttribute]] = relationship(
        back_populates="object", cascade="all, delete-orphan"
    )
    tags: Mapped[list[ObjectTag]] = relationship(
        back_populates="object", cascade="all, delete-orphan"
    )


class ObjectAttribute(Base):
    """Значение характеристики; value_type описывает интерпретацию текстового значения."""

    __tablename__ = "object_attributes"
    __table_args__ = (
        UniqueConstraint("object_id", "attribute_code", name="uq_object_attributes_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("city_objects.id", ondelete="CASCADE"))
    attribute_code: Mapped[str] = mapped_column(String(120))
    value: Mapped[str] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(40))

    object: Mapped[CityObject] = relationship(back_populates="attributes")


class ObjectTag(Base):
    """Поисковая метка для отбора контекста будущим генератором."""

    __tablename__ = "object_tags"
    __table_args__ = (
        UniqueConstraint("object_id", "tag", name="uq_object_tags_object_tag"),
        Index("ix_object_tags_tag", "tag"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("city_objects.id", ondelete="CASCADE"))
    tag: Mapped[str] = mapped_column(String(120))

    object: Mapped[CityObject] = relationship(back_populates="tags")

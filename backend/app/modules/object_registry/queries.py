"""Запросы для отбора объектов по дереву типов и тегам."""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.sql import Select

from app.modules.object_registry.models import (
    CityObject,
    ObjectTag,
    ObjectTagClassifierFeature,
    ObjectType,
)


def descendant_type_ids(parent_code: str) -> Select[tuple[int]]:
    """Тип с указанным кодом и все его потомки любой глубины."""

    tree = (
        select(ObjectType.id)
        .where(ObjectType.code == parent_code)
        .cte(name="object_type_tree", recursive=True)
    )
    children = ObjectType.__table__.alias("children")
    tree = tree.union(select(children.c.id).where(children.c.parent_id == tree.c.id))
    return select(tree.c.id)


def select_city_objects(
    *, type_code: str | None = None, tags: Iterable[str] = ()
) -> Select[tuple[CityObject]]:
    """Отбор для генератора: тип с потомками и хотя бы один из заданных тегов."""

    query = select(CityObject)
    if type_code is not None:
        query = query.where(CityObject.object_type_id.in_(descendant_type_ids(type_code)))
    tag_set = set(tags)
    if tag_set:
        query = query.where(
            CityObject.id.in_(select(ObjectTag.object_id).where(ObjectTag.tag.in_(tag_set)))
        )
    return query


def select_city_objects_for_classifier_features(
    feature_ids: Iterable[int], *, type_code: str | None = None
) -> Select[tuple[CityObject]]:
    """Find objects by explicitly linked SRC-006 features, with optional type tree."""
    tag_codes = select(ObjectTagClassifierFeature.tag_code).where(
        ObjectTagClassifierFeature.feature_id.in_(set(feature_ids))
    )
    query = select_city_objects(type_code=type_code)
    return query.where(
        CityObject.id.in_(select(ObjectTag.object_id).where(ObjectTag.tag.in_(tag_codes)))
    )

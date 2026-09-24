"""Read-only API для проверки классификатора и каталога служб."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User
from app.modules.incident_classifier.models import (
    DispatchService,
    IncidentClassifierRule,
    IncidentFeature,
    IncidentRuleFeature,
    IncidentRuleService,
)

router = APIRouter(prefix="/incident-classifier", tags=["incident-classifier"])


@router.get("/types")
async def list_types(
    _user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[dict]:
    rules = (
        await database.scalars(select(IncidentClassifierRule).order_by(IncidentClassifierRule.id))
    ).all()
    by_type: dict[str, dict] = {}
    for rule in rules:
        entry = by_type.setdefault(
            rule.final_incident_type,
            {"name": rule.final_incident_type, "groups": set(), "rule_ids": []},
        )
        entry["groups"].add(rule.incident_group)
        entry["rule_ids"].append(rule.id)
    return [
        {**entry, "groups": sorted(entry["groups"])}
        for entry in sorted(by_type.values(), key=lambda row: row["name"])
    ]


@router.get("/features")
async def list_features(
    _user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[dict]:
    rows = (await database.scalars(select(IncidentFeature).order_by(IncidentFeature.id))).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "level": row.level,
            "source_column": row.source_column,
            "source_value": row.source_value,
        }
        for row in rows
    ]


@router.get("/services")
async def list_services(
    _user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[dict]:
    rows = (await database.scalars(select(DispatchService).order_by(DispatchService.id))).all()
    return [
        {
            "id": row.id,
            "official_name": row.official_name,
            "organization": row.organization,
            "service_level": row.service_level,
            "source_reference": row.source_reference,
        }
        for row in rows
    ]


@router.get("/rules/{rule_id}")
async def read_rule(
    rule_id: int,
    _user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    rule = (
        await database.scalars(
            select(IncidentClassifierRule)
            .where(IncidentClassifierRule.id == rule_id)
            .options(
                selectinload(IncidentClassifierRule.features).selectinload(
                    IncidentRuleFeature.feature
                ),
                selectinload(IncidentClassifierRule.services).selectinload(
                    IncidentRuleService.service
                ),
            )
        )
    ).one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Правило не найдено")
    return {
        "id": rule.id,
        "source_code": rule.source_code,
        "incident_group": rule.incident_group,
        "final_incident_type": rule.final_incident_type,
        "ekp35_type": rule.ekp35_type,
        "source_reference": rule.source_reference,
        "features": [
            {
                "id": link.feature.id,
                "name": link.feature.name,
                "level": link.feature.level,
                "source_column": link.feature.source_column,
                "source_value": link.feature.source_value,
            }
            for link in rule.features
        ],
        "services": [
            {
                "id": link.service.id,
                "official_name": link.service.official_name,
                "organization": link.service.organization,
                "service_level": link.service.service_level,
                "source_reference": link.service.source_reference,
                "relation_source_reference": link.source_reference,
            }
            for link in rule.services
        ],
    }

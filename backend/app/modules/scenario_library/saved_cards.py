"""Reusable incident card snapshots for instructors."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.dependencies import get_database_session
from app.modules.identity.models import User, UserRole
from app.modules.scenario_library.instance_models import (
    SavedIncidentCard,
    ScenarioInstance,
    ScenarioInstanceEvent,
)
from app.modules.scenario_library.instances import _initial_request, read_instance
from app.modules.scenario_library.router import require_editor
from app.modules.training.models import TrainingGroup, TrainingSession, TrainingSessionState
from app.services.text_generation.renderer import renderer_for_database

router = APIRouter(prefix="/api/incident-cards", tags=["incident-cards"])


class CardTextInput(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class CardFactsInput(BaseModel):
    facts: dict[str, str | int]


class AddToGroupInput(BaseModel):
    session_id: int = Field(gt=0)
    group_id: int = Field(gt=0)


def serialize(card: SavedIncidentCard) -> dict:
    content = card.snapshot
    return {
        "id": card.id,
        "name": card.name,
        "source_template_id": card.source_template_id,
        "created_by_user_id": card.created_by_user_id,
        "classifier_snapshot": content["classifier_snapshot"],
        "object_snapshot": content["object_snapshot"],
        "service_snapshot": content["service_snapshot"],
        "initial_state_snapshot": content["initial_state_snapshot"],
        "template_snapshot": content["template_snapshot"],
        "created_at": card.created_at,
    }


async def get_card(database: AsyncSession, card_id: int) -> SavedIncidentCard:
    card = await database.get(SavedIncidentCard, card_id)
    if card is None or card.deleted_at is not None:
        raise HTTPException(404, "Карточка не найдена")
    return card


@router.get("")
async def list_cards(
    _user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[dict]:
    cards = (
        await database.scalars(
            select(SavedIncidentCard)
            .where(SavedIncidentCard.deleted_at.is_(None))
            .order_by(SavedIncidentCard.created_at.desc(), SavedIncidentCard.id.desc())
        )
    ).all()
    return [serialize(card) for card in cards]


@router.post("/from-instance/{instance_id}", status_code=201)
async def save_instance(
    instance_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    await read_instance(instance_id, user, database)
    row = (
        await database.scalars(
            select(ScenarioInstance)
            .where(ScenarioInstance.id == instance_id)
            .options(selectinload(ScenarioInstance.events))
        )
    ).one()
    content = {
        "difficulty": row.difficulty,
        "generation_seed": row.generation_seed,
        "classifier_snapshot": row.classifier_snapshot,
        "object_snapshot": row.object_snapshot,
        "service_snapshot": row.service_snapshot,
        "initial_state_snapshot": row.initial_state_snapshot,
        "expected_actions_snapshot": row.expected_actions_snapshot,
        "assessment_criteria_snapshot": row.assessment_criteria_snapshot,
        "template_snapshot": row.template_snapshot,
        "events": [
            {
                "sequence_number": event.sequence_number,
                "offset_seconds": event.offset_seconds,
                "event_type": event.event_type,
                "title": event.title,
                "description": event.description,
                "source_type": event.source_type,
                "payload_snapshot": event.payload_snapshot,
            }
            for event in row.events
        ],
    }
    card = SavedIncidentCard(
        created_by_user_id=user.id,
        source_template_id=row.scenario_template_id,
        name=row.name,
        snapshot=content,
    )
    database.add(card)
    await database.commit()
    return serialize(await get_card(database, card.id))


@router.get("/{card_id}")
async def read_card(
    card_id: int,
    _user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    return serialize(await get_card(database, card_id))


@router.patch("/{card_id}/text")
async def edit_card_text(
    card_id: int,
    data: CardTextInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    card = await get_card(database, card_id)
    if user.role != UserRole.ADMIN and card.created_by_user_id != user.id:
        raise HTTPException(403, "Редактировать карточку может только автор или администратор")
    snapshot = dict(card.snapshot)
    initial = dict(snapshot["initial_state_snapshot"])
    render = dict(initial.get("render") or {})
    render.update(rendered_text=data.text.strip(), render_origin="MANUAL")
    initial["render"] = render
    snapshot["initial_state_snapshot"] = initial
    card.snapshot = snapshot
    await database.commit()
    return serialize(card)


@router.patch("/{card_id}/facts")
async def edit_card_facts(
    card_id: int,
    data: CardFactsInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    card = await get_card(database, card_id)
    if user.role != UserRole.ADMIN and card.created_by_user_id != user.id:
        raise HTTPException(403, "Редактировать карточку может только автор или администратор")
    content = dict(card.snapshot)
    options = content["template_snapshot"].get("variant_options") or {}
    if set(data.facts) != set(options) or any(
        value not in options[key] for key, value in data.facts.items()
    ):
        raise HTTPException(422, "Условие не разрешено шаблоном")
    initial = dict(content["initial_state_snapshot"])
    initial["variant_facts"] = data.facts
    labels = {
        "floor": "Этаж",
        "room": "Место",
        "observation": "Задымление",
        "casualties": "Пострадавшие",
    }
    fact_text = "; ".join(f"{labels.get(key, key)}: {value}" for key, value in data.facts.items())
    initial["description"] = content["classifier_snapshot"]["final_incident_type"] + (
        f"; {fact_text}" if fact_text else ""
    )
    content["initial_state_snapshot"] = initial
    renderer = await renderer_for_database(database)
    initial["render"] = await renderer.render(_initial_request(content))
    card.snapshot = content
    await database.commit()
    return serialize(card)


@router.delete("/{card_id}", status_code=204)
async def delete_card(
    card_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> None:
    card = await get_card(database, card_id)
    if user.role != UserRole.ADMIN and card.created_by_user_id != user.id:
        raise HTTPException(403, "Удалить карточку может только автор или администратор")
    card.deleted_at = datetime.now(UTC)
    await database.commit()


@router.post("/{card_id}/add-to-group", status_code=201)
async def add_to_group(
    card_id: int,
    data: AddToGroupInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    card = await get_card(database, card_id)
    session = await database.get(TrainingSession, data.session_id)
    if session is None:
        raise HTTPException(404, "Занятие не найдено")
    if user.role != UserRole.ADMIN and session.instructor_id != user.id:
        raise HTTPException(403, "Нет доступа к занятию")
    if session.state not in {"DRAFT", "READY"}:
        raise HTTPException(409, "Занятие уже началось")
    group = await database.get(TrainingGroup, data.group_id)
    if group is None or group.training_session_id != session.id:
        raise HTTPException(422, "Группа не принадлежит занятию")
    if session.state == TrainingSessionState.READY:
        session.state = TrainingSessionState.DRAFT
    content = card.snapshot
    row = ScenarioInstance(
        scenario_template_id=card.source_template_id,
        training_session_id=session.id,
        training_group_id=group.id,
        created_by_user_id=user.id,
        name=card.name,
        difficulty=content["difficulty"],
        generation_seed=content["generation_seed"],
        status="CONFIRMED",
        classifier_snapshot=content["classifier_snapshot"],
        object_snapshot=content["object_snapshot"],
        service_snapshot=content["service_snapshot"],
        initial_state_snapshot=content["initial_state_snapshot"],
        expected_actions_snapshot=content["expected_actions_snapshot"],
        assessment_criteria_snapshot=content["assessment_criteria_snapshot"],
        template_snapshot=content["template_snapshot"],
        events=[ScenarioInstanceEvent(**event) for event in content["events"]],
    )
    database.add(row)
    await database.commit()
    return {"id": row.id, "group_id": group.id}

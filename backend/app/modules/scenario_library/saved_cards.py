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
    SavedIncidentCardPackage,
    ScenarioInstance,
    ScenarioInstanceEvent,
)
from app.modules.scenario_library.instances import (
    AdditionalConditionsInput,
    _initial_request,
    _record_usage,
    read_instance,
)
from app.modules.scenario_library.router import require_editor
from app.modules.training.models import TrainingGroup, TrainingSession, TrainingSessionState
from app.services.text_generation.renderer import TextGenerationRequest, renderer_for_database

router = APIRouter(prefix="/api/incident-cards", tags=["incident-cards"])


class CardTextInput(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class CardFactsInput(BaseModel):
    facts: dict[str, str | int]


class AddToGroupInput(BaseModel):
    session_id: int = Field(gt=0)
    group_id: int = Field(gt=0)


class PackageInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    card_ids: list[int] = Field(min_length=1, max_length=100)


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


def serialize_package(package: SavedIncidentCardPackage) -> dict:
    return {
        "id": package.id,
        "name": package.name,
        "description": package.description,
        "card_ids": package.card_ids,
        "created_by_user_id": package.created_by_user_id,
        "created_at": package.created_at,
    }


async def get_card(database: AsyncSession, card_id: int) -> SavedIncidentCard:
    card = await database.get(SavedIncidentCard, card_id)
    if card is None or card.deleted_at is not None:
        raise HTTPException(404, "Карточка не найдена")
    return card


async def get_package(database: AsyncSession, package_id: int) -> SavedIncidentCardPackage:
    package = await database.get(SavedIncidentCardPackage, package_id)
    if package is None or package.deleted_at is not None:
        raise HTTPException(404, "Пакет карточек не найден")
    return package


async def validate_package_cards(database: AsyncSession, card_ids: list[int]) -> None:
    if len(set(card_ids)) != len(card_ids) or any(card_id <= 0 for card_id in card_ids):
        raise HTTPException(422, "Карточки в пакете не должны повторяться")
    found = (
        await database.scalars(
            select(SavedIncidentCard.id).where(
                SavedIncidentCard.id.in_(card_ids), SavedIncidentCard.deleted_at.is_(None)
            )
        )
    ).all()
    if len(found) != len(card_ids):
        raise HTTPException(422, "В пакете есть карточки, которых нет в библиотеке")


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


@router.get("/packages")
async def list_packages(
    _user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[dict]:
    packages = (
        await database.scalars(
            select(SavedIncidentCardPackage)
            .where(SavedIncidentCardPackage.deleted_at.is_(None))
            .order_by(
                SavedIncidentCardPackage.created_at.desc(),
                SavedIncidentCardPackage.id.desc(),
            )
        )
    ).all()
    return [serialize_package(package) for package in packages]


@router.post("/packages", status_code=201)
async def create_package(
    data: PackageInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    name = data.name.strip()
    if not name:
        raise HTTPException(422, "Укажите название пакета")
    await validate_package_cards(database, data.card_ids)
    package = SavedIncidentCardPackage(
        created_by_user_id=user.id,
        name=name,
        description=data.description.strip(),
        card_ids=data.card_ids,
    )
    database.add(package)
    await database.commit()
    return serialize_package(package)


@router.patch("/packages/{package_id}")
async def update_package(
    package_id: int,
    data: PackageInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    package = await get_package(database, package_id)
    if user.role != UserRole.ADMIN and package.created_by_user_id != user.id:
        raise HTTPException(403, "Изменить пакет может только автор или администратор")
    name = data.name.strip()
    if not name:
        raise HTTPException(422, "Укажите название пакета")
    await validate_package_cards(database, data.card_ids)
    package.name = name
    package.description = data.description.strip()
    package.card_ids = data.card_ids
    await database.commit()
    return serialize_package(package)


@router.delete("/packages/{package_id}", status_code=204)
async def delete_package(
    package_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> None:
    package = await get_package(database, package_id)
    if user.role != UserRole.ADMIN and package.created_by_user_id != user.id:
        raise HTTPException(403, "Удалить пакет может только автор или администратор")
    package.deleted_at = datetime.now(UTC)
    await database.commit()


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


@router.post("/{card_id}/rerender-text")
async def rerender_card_text(
    card_id: int,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    card = await get_card(database, card_id)
    if user.role != UserRole.ADMIN and card.created_by_user_id != user.id:
        raise HTTPException(403, "Редактировать карточку может только автор или администратор")
    content = dict(card.snapshot)
    initial = dict(content["initial_state_snapshot"])
    previous_text = initial.get("render", {}).get("rendered_text", "")
    request = _initial_request(content)
    renderer = await renderer_for_database(database)
    render = await renderer.render(
        TextGenerationRequest(
            task=request.task,
            facts=request.facts,
            context={"previous_text": previous_text} if previous_text else None,
        )
    )
    await _record_usage(database, [render])
    if render["fallback_used"] and renderer.enabled and renderer.provider.name != "template":
        await database.commit()
        raise HTTPException(503, "Модель не смогла сформировать текст. Повторите попытку")
    if render["rendered_text"].strip() == previous_text.strip():
        await database.commit()
        raise HTTPException(409, "Новая формулировка не получена. Текст карточки не изменился")
    initial["render"] = render
    content["initial_state_snapshot"] = initial
    card.snapshot = content
    await database.commit()
    return serialize(card)


@router.patch("/{card_id}/additional-conditions")
async def edit_card_additional_conditions(
    card_id: int,
    data: AdditionalConditionsInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    card = await get_card(database, card_id)
    if user.role != UserRole.ADMIN and card.created_by_user_id != user.id:
        raise HTTPException(403, "Редактировать карточку может только автор или администратор")
    content = dict(card.snapshot)
    initial = dict(content["initial_state_snapshot"])
    initial["additional_conditions"] = data.conditions
    content["initial_state_snapshot"] = initial
    render = await (await renderer_for_database(database)).render(_initial_request(content))
    await _record_usage(database, [render])
    initial["render"] = render
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
    packages = (
        await database.scalars(
            select(SavedIncidentCardPackage).where(SavedIncidentCardPackage.deleted_at.is_(None))
        )
    ).all()
    for package in packages:
        if card.id in package.card_ids:
            package.card_ids = [item for item in package.card_ids if item != card.id]
    await database.commit()


def _already_in_group(card: SavedIncidentCard, existing: list[ScenarioInstance]) -> bool:
    return any(
        row.template_snapshot.get("source_saved_card_id") == card.id
        or (
            row.object_snapshot == card.snapshot["object_snapshot"]
            and row.initial_state_snapshot == card.snapshot["initial_state_snapshot"]
            and row.scenario_template_id == card.source_template_id
        )
        for row in existing
    )


def _copy_to_group(
    card: SavedIncidentCard, session_id: int, group_id: int, user_id: int
) -> ScenarioInstance:
    content = card.snapshot
    return ScenarioInstance(
        scenario_template_id=card.source_template_id,
        training_session_id=session_id,
        training_group_id=group_id,
        created_by_user_id=user_id,
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
        template_snapshot={**content["template_snapshot"], "source_saved_card_id": card.id},
        events=[ScenarioInstanceEvent(**event) for event in content["events"]],
    )


async def _target_group(
    data: AddToGroupInput, user: User, database: AsyncSession
) -> tuple[TrainingSession, TrainingGroup]:
    session = await database.get(TrainingSession, data.session_id)
    if session is None:
        raise HTTPException(404, "Занятие не найдено")
    if user.role != UserRole.ADMIN and session.instructor_id != user.id:
        raise HTTPException(403, "Нет доступа к занятию")
    if session.state not in {"DRAFT", "READY"}:
        raise HTTPException(409, "Занятие уже началось")
    group = await database.scalar(
        select(TrainingGroup).where(TrainingGroup.id == data.group_id).with_for_update()
    )
    if group is None or group.training_session_id != session.id:
        raise HTTPException(422, "Группа не принадлежит занятию")
    return session, group


async def _group_instances(
    session_id: int, group_id: int, database: AsyncSession
) -> list[ScenarioInstance]:
    return list(
        (
            await database.scalars(
                select(ScenarioInstance).where(
                    ScenarioInstance.training_session_id == session_id,
                    ScenarioInstance.training_group_id == group_id,
                )
            )
        ).all()
    )


@router.post("/{card_id}/add-to-group", status_code=201)
async def add_to_group(
    card_id: int,
    data: AddToGroupInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    card = await get_card(database, card_id)
    session, group = await _target_group(data, user, database)
    existing = await _group_instances(session.id, group.id, database)
    if _already_in_group(card, existing):
        raise HTTPException(409, "Эта карточка уже добавлена в группу")
    if session.state == TrainingSessionState.READY:
        session.state = TrainingSessionState.DRAFT
    row = _copy_to_group(card, session.id, group.id, user.id)
    database.add(row)
    await database.commit()
    return {"id": row.id, "group_id": group.id}


@router.post("/packages/{package_id}/add-to-group", status_code=201)
async def add_package_to_group(
    package_id: int,
    data: AddToGroupInput,
    user: Annotated[User, Depends(require_editor)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> dict:
    package = await get_package(database, package_id)
    if not package.card_ids:
        raise HTTPException(409, "В пакете больше нет карточек")
    session, group = await _target_group(data, user, database)
    cards = (
        await database.scalars(
            select(SavedIncidentCard).where(
                SavedIncidentCard.id.in_(package.card_ids), SavedIncidentCard.deleted_at.is_(None)
            )
        )
    ).all()
    cards_by_id = {card.id: card for card in cards}
    if len(cards_by_id) != len(package.card_ids):
        raise HTTPException(409, "В пакете есть удалённые карточки. Обновите пакет")
    existing = await _group_instances(session.id, group.id, database)
    added = []
    for card_id in package.card_ids:
        card = cards_by_id[card_id]
        if _already_in_group(card, existing):
            continue
        row = _copy_to_group(card, session.id, group.id, user.id)
        added.append(row)
        existing.append(row)
    if not added:
        raise HTTPException(409, "Все карточки пакета уже добавлены в группу")
    if session.state == TrainingSessionState.READY:
        session.state = TrainingSessionState.DRAFT
    database.add_all(added)
    await database.commit()
    return {
        "group_id": group.id,
        "added_count": len(added),
        "skipped_count": len(package.card_ids) - len(added),
    }

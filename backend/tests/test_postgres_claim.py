"""Real PostgreSQL check for concurrent ownership of a shared incident."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.modules.identity.models import User, UserRole
from app.modules.incidents.models import Incident
from app.modules.incidents.router import claim_incident
from app.modules.incidents.workflow import create_delivered_incident
from app.modules.response import models as response_models  # noqa: F401
from app.modules.training.models import (
    QueueMode,
    TrainingGroup,
    TrainingRun,
    TrainingSession,
    TrainingSessionState,
)


@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_TESTS") != "1", reason="Requires isolated PostgreSQL test database"
)
def test_only_one_concurrent_claim_wins(monkeypatch) -> None:
    async def run() -> None:
        engine = create_database_engine(get_settings())
        factory = create_session_factory(engine)
        nonce = uuid4().hex[:10]
        first_user_id = 1_000_000_000 + int(nonce[:6], 16) * 3
        user_ids = []
        session_id = incident_id = None
        monkeypatch.setattr(
            "app.modules.incidents.router.publish_session_event", _no_notification
        )
        try:
            async with factory() as database:
                instructor = User(
                    id=first_user_id, username=f"i{nonce}",
                    full_name="Преподаватель", role=UserRole.INSTRUCTOR,
                )
                trainees = [
                    User(id=first_user_id + index, username=f"t{nonce}{index}",
                         full_name=f"Обучаемый {index}",
                         role=UserRole.TRAINEE)
                    for index in (1, 2)
                ]
                group = TrainingGroup(
                    name="Общая ДДС", dds_profile="ДДС", queue_mode=QueueMode.SHARED_QUEUE
                )
                session = TrainingSession(
                    title="Concurrency", instructor=instructor, trainees=trainees,
                    groups=[group], state=TrainingSessionState.ACTIVE,
                )
                session.runs = [
                    TrainingRun(
                        trainee=trainee, group=group, dds_profile="ДДС",
                        queue_mode=QueueMode.SHARED_QUEUE, workstation_number=index,
                    )
                    for index, trainee in enumerate(trainees, 1)
                ]
                database.add(session)
                await database.flush()
                snapshot = {
                    "incident_number": f"UT112-23-{nonce}",
                    "reported_at": datetime.now(UTC).isoformat(),
                    "source": "Система-112", "address": "Учебный адрес",
                    "description": "Проверка claim", "incident_type": "Проверка",
                }
                incident = create_delivered_incident(
                    training_session_id=session.id, source_snapshot=snapshot,
                )
                incident.training_group_id = group.id
                database.add(incident)
                await database.flush()
                user_ids = [instructor.id, *(trainee.id for trainee in trainees)]
                session_id, incident_id = session.id, incident.id
                await database.commit()

            async def attempt(trainee: User):
                async with factory() as database:
                    try:
                        return await claim_incident(incident_id, trainee, database)
                    except HTTPException as error:
                        await database.rollback()
                        return error

            outcomes = await asyncio.gather(*(attempt(trainee) for trainee in trainees))
            assert sum(not isinstance(outcome, HTTPException) for outcome in outcomes) == 1
            assert [outcome.status_code for outcome in outcomes
                    if isinstance(outcome, HTTPException)] == [409]
            async with factory() as database:
                owner = await database.scalar(
                    select(Incident.claimed_by_training_run_id).where(Incident.id == incident_id)
                )
                assert owner in {run.id for run in session.runs}
        finally:
            if session_id is not None:
                async with factory() as database:
                    if incident_id is not None:
                        await database.execute(delete(Incident).where(Incident.id == incident_id))
                    await database.execute(
                        delete(TrainingSession).where(TrainingSession.id == session_id)
                    )
                    await database.execute(delete(User).where(User.id.in_(user_ids)))
                    await database.commit()
            await engine.dispose()

    asyncio.run(run())


async def _no_notification(*_args) -> None:
    pass

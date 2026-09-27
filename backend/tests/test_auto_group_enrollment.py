"""Selected group members join a draft session when they occupy a workstation."""

import asyncio

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_scenario_library import AsyncAdapter

from app.db.base import Base
from app.db.dependencies import get_database_session
from app.modules.admin import models as admin_models  # noqa: F401
from app.modules.admin.models import UserGroup
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole
from app.modules.identity.router import router as users_router
from app.modules.incidents import models as incident_models  # noqa: F401
from app.modules.response import models as response_models  # noqa: F401
from app.modules.training.models import TrainingSession
from app.modules.training.router import router as sessions_router


def test_selected_group_member_joins_automatically_in_either_order():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        teacher = User(username="teacher", full_name="Teacher", role=UserRole.INSTRUCTOR)
        group = UserGroup(name="Диспетчеры", code="103", created_by_user_id=None)
        db.add_all([teacher, group])
        db.flush()
        group.created_by_user_id = teacher.id
        members = [
            User(
                username=f"member{index}",
                full_name=f"Member {index}",
                role=UserRole.TRAINEE,
                group_id=group.id,
            )
            for index in range(2)
        ]
        outsider = User(username="outsider", full_name="Outsider", role=UserRole.TRAINEE)
        lesson = TrainingSession(
            title="Занятие", instructor_id=teacher.id, mode="FIXED_SET", workstation_count=3
        )
        db.add_all([*members, outsider, lesson])
        db.commit()

        app = FastAPI()
        app.include_router(users_router)
        app.include_router(sessions_router)
        current = [teacher]
        app.dependency_overrides[get_current_user] = lambda: current[0]

        async def database():
            yield AsyncAdapter(db)

        app.dependency_overrides[get_database_session] = database

        async def run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                path = f"/api/training/sessions/{lesson.id}"
                current[0] = members[0]
                response = await client.put(
                    "/api/users/workstation", json={"workstation_number": 1}
                )
                assert response.status_code == 200, response.text

                current[0] = teacher
                response = await client.post(
                    f"{path}/groups",
                    json={
                        "name": group.name,
                        "source_user_group_id": group.id,
                        "queue_mode": "SHARED_QUEUE",
                    },
                )
                assert response.status_code == 200, response.text
                selected = response.json()["groups"][0]
                assert [
                    (run["trainee_id"], run["group_id"]) for run in response.json()["runs"]
                ] == [(members[0].id, selected["id"])]

                current[0] = members[1]
                response = await client.put(
                    "/api/users/workstation", json={"workstation_number": 2}
                )
                assert response.status_code == 200, response.text
                response = await client.put(
                    "/api/users/workstation", json={"workstation_number": 2}
                )
                assert response.status_code == 200, response.text

                current[0] = outsider
                response = await client.put(
                    "/api/users/workstation", json={"workstation_number": 3}
                )
                assert response.status_code == 200, response.text

                current[0] = teacher
                read = await client.get(path)
                assert read.status_code == 200, read.text
                assert [(run["trainee_id"], run["group_id"]) for run in read.json()["runs"]] == [
                    (members[0].id, selected["id"]),
                    (members[1].id, selected["id"]),
                ]

        asyncio.run(run())

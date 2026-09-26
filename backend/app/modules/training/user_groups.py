"""Reusable trainee groups managed by their instructor."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_database_session
from app.modules.admin.models import UserGroup
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.models import User, UserRole

router = APIRouter(prefix="/api/training/user-groups", tags=["trainee groups"])


class MemberRead(BaseModel):
    id: int
    full_name: str
    group_id: int | None = None


class UserGroupRead(BaseModel):
    id: int
    name: str
    code: str | None
    is_archived: bool
    members: list[MemberRead]
    member_count: int


class UserGroupWrite(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    code: str = Field(min_length=1, max_length=40)
    member_ids: list[int] = Field(default_factory=list)

    @field_validator("name", "code")
    @classmethod
    def strip_text(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("Поле не может быть пустым")
        return result

    @field_validator("member_ids")
    @classmethod
    def unique_members(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("Участник указан дважды")
        return value


class ArchiveWrite(BaseModel):
    is_archived: bool


def _check_role(user: User) -> None:
    if user.role not in (UserRole.INSTRUCTOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Доступно преподавателю и администратору")


def _check_owner(group: UserGroup, user: User) -> None:
    if user.role != UserRole.ADMIN and group.created_by_user_id != user.id:
        raise HTTPException(status_code=404, detail="Группа не найдена")


async def _read(database: AsyncSession, group: UserGroup) -> UserGroupRead:
    members = (await database.scalars(
        select(User).where(User.group_id == group.id, User.role == UserRole.TRAINEE)
        .order_by(User.full_name, User.id)
    )).all()
    return UserGroupRead(
        id=group.id, name=group.name, code=group.code,
        is_archived=group.is_archived,
        members=[
            MemberRead(id=member.id, full_name=member.full_name, group_id=member.group_id)
            for member in members
        ],
        member_count=len(members),
    )


async def _members(
    database: AsyncSession, ids: list[int], target_group_id: int | None = None,
) -> list[User]:
    if not ids:
        return []
    users = (await database.scalars(
        select(User).where(
            User.id.in_(ids), User.role == UserRole.TRAINEE, User.is_active.is_(True)
        )
    )).all()
    if {item.id for item in users} != set(ids):
        raise HTTPException(status_code=422, detail="Выберите существующих активных обучаемых")
    if any(item.group_id not in (None, target_group_id) for item in users):
        raise HTTPException(status_code=409, detail="Обучаемый уже состоит в другой группе")
    return list(users)


async def _check_unique(
    database: AsyncSession, payload: UserGroupWrite, group_id: int | None = None,
) -> None:
    duplicate = await database.scalar(
        select(UserGroup.id).where(
            (func.lower(UserGroup.name) == payload.name.lower())
            | (func.lower(UserGroup.code) == payload.code.lower()),
            UserGroup.id != group_id if group_id is not None else True,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Название или код группы уже используется")


@router.get("", response_model=list[UserGroupRead])
async def list_user_groups(
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[UserGroupRead]:
    _check_role(current_user)
    query = select(UserGroup).order_by(UserGroup.name)
    if current_user.role != UserRole.ADMIN:
        query = query.where(UserGroup.created_by_user_id == current_user.id)
    groups = (await database.scalars(query)).all()
    return [await _read(database, group) for group in groups]


@router.get("/trainees", response_model=list[MemberRead])
async def list_available_trainees(
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[MemberRead]:
    _check_role(current_user)
    users = (await database.scalars(
        select(User).where(User.role == UserRole.TRAINEE, User.is_active.is_(True))
        .order_by(User.full_name, User.id)
    )).all()
    return [
        MemberRead(id=item.id, full_name=item.full_name, group_id=item.group_id)
        for item in users
    ]


@router.post("", response_model=UserGroupRead, status_code=status.HTTP_201_CREATED)
async def create_user_group(
    payload: UserGroupWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> UserGroupRead:
    _check_role(current_user)
    await _check_unique(database, payload)
    members = await _members(database, payload.member_ids)
    group = UserGroup(
        name=payload.name, code=payload.code, created_by_user_id=current_user.id,
    )
    database.add(group)
    try:
        await database.flush()
        for member in members:
            member.group_id = group.id
        await database.commit()
    except IntegrityError as error:
        await database.rollback()
        raise HTTPException(
            status_code=409, detail="Название или код группы уже используется"
        ) from error
    return await _read(database, group)


@router.put("/{group_id}", response_model=UserGroupRead)
async def update_user_group(
    group_id: int,
    payload: UserGroupWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> UserGroupRead:
    _check_role(current_user)
    group = await database.get(UserGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    _check_owner(group, current_user)
    if group.is_archived:
        raise HTTPException(status_code=409, detail="Сначала восстановите группу из архива")
    await _check_unique(database, payload, group_id)
    members = await _members(database, payload.member_ids, group.id)
    group.name, group.code = payload.name, payload.code
    await database.execute(
        update(User).where(User.group_id == group.id, User.id.not_in(payload.member_ids))
        .values(group_id=None)
    )
    for member in members:
        member.group_id = group.id
    try:
        await database.commit()
    except IntegrityError as error:
        await database.rollback()
        raise HTTPException(
            status_code=409, detail="Название или код группы уже используется"
        ) from error
    return await _read(database, group)


@router.patch("/{group_id}/archive", response_model=UserGroupRead)
async def archive_user_group(
    group_id: int,
    payload: ArchiveWrite,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[AsyncSession, Depends(get_database_session)],
) -> UserGroupRead:
    _check_role(current_user)
    group = await database.get(UserGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    _check_owner(group, current_user)
    group.is_archived = payload.is_archived
    await database.commit()
    return await _read(database, group)

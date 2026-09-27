"""Идемпотентный импорт demo-пользователей, учебных и виртуальных групп."""

import asyncio
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
from app.db.session import create_database_engine

SEED_ROOT = Path(__file__).resolve().parents[2] / "seed" / "demo"


def load_rows(filename: str, key: str) -> list[dict]:
    rows = json.loads((SEED_ROOT / filename).read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{filename}: ожидается непустой JSON-массив")
    keys = [row.get(key) for row in rows if isinstance(row, dict)]
    if len(keys) != len(rows) or any(not value for value in keys) or len(set(keys)) != len(keys):
        raise ValueError(f"{filename}: пустой или повторяющийся {key}")
    return rows


async def upsert_users(connection: AsyncConnection, rows: list[dict]) -> dict[str, int]:
    stats = {"created": 0, "updated": 0, "unchanged": 0}
    for row in rows:
        existing = (
            await connection.execute(
                text("SELECT full_name, role, is_active FROM users WHERE username = :username"),
                {"username": row["username"]},
            )
        ).mappings().one_or_none()
        fields = {name: row[name] for name in ("full_name", "role", "is_active")}
        if existing is None:
            await connection.execute(
                text("""
                    INSERT INTO users (username, full_name, role, is_active)
                    VALUES (:username, :full_name, :role, :is_active)
                """),
                row,
            )
            stats["created"] += 1
        elif any(str(existing[name]) != str(value) for name, value in fields.items()):
            await connection.execute(
                text("""
                    UPDATE users SET full_name = :full_name, role = :role, is_active = :is_active
                    WHERE username = :username
                """),
                row,
            )
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1
    return stats


async def upsert_response_units(connection: AsyncConnection, rows: list[dict]) -> dict[str, int]:
    stats = {"created": 0, "updated": 0, "unchanged": 0}
    for row in rows:
        existing = (
            await connection.execute(
                text("""
                    SELECT name, dds_profile, description, is_active
                    FROM response_units WHERE seed_code = :seed_code
                """),
                {"seed_code": row["seed_code"]},
            )
        ).mappings().one_or_none()
        fields = {name: row[name] for name in ("name", "dds_profile", "description", "is_active")}
        if existing is None:
            await connection.execute(
                text("""
                    INSERT INTO response_units
                        (seed_code, name, dds_profile, description, is_active)
                    VALUES (:seed_code, :name, :dds_profile, :description, :is_active)
                """),
                row,
            )
            stats["created"] += 1
        elif any(existing[name] != value for name, value in fields.items()):
            await connection.execute(
                text("""
                    UPDATE response_units SET name = :name, dds_profile = :dds_profile,
                        description = :description, is_active = :is_active
                    WHERE seed_code = :seed_code
                """),
                row,
            )
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1
    return stats


async def upsert_user_groups(connection: AsyncConnection, rows: list[dict]) -> dict[str, int]:
    stats = {"created": 0, "updated": 0, "unchanged": 0}
    instructor_id = await connection.scalar(
        text("SELECT id FROM users WHERE username = 'instructor'")
    )
    for row in rows:
        existing = (
            await connection.execute(
                text("""
                    SELECT id, name, description, is_archived FROM user_groups WHERE code = :code
                """),
                {"code": row["code"]},
            )
        ).mappings().one_or_none()
        fields = {"name": row["name"], "description": row["description"], "is_archived": False}
        if existing is None:
            group_id = await connection.scalar(
                text("""
                    INSERT INTO user_groups (code, name, description, created_by_user_id)
                    VALUES (:code, :name, :description, :instructor_id) RETURNING id
                """),
                {**row, "instructor_id": instructor_id},
            )
            stats["created"] += 1
        else:
            group_id = existing["id"]
            if any(existing[name] != value for name, value in fields.items()):
                await connection.execute(
                    text("""
                        UPDATE user_groups SET name = :name, description = :description,
                            is_archived = false WHERE id = :id
                    """),
                    {**row, "id": group_id},
                )
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
        for username in row["members"]:
            member = (
                await connection.execute(
                    text("SELECT id, role, group_id FROM users WHERE username = :username"),
                    {"username": username},
                )
            ).mappings().one_or_none()
            if member is None or member["role"] != "TRAINEE":
                raise ValueError(f"Не найден обучаемый группы {row['code']}: {username}")
            if member["group_id"] is None:
                await connection.execute(
                    text("UPDATE users SET group_id = :group_id WHERE id = :id"),
                    {"group_id": group_id, "id": member["id"]},
                )
    return stats


async def seed_demo() -> dict[str, dict[str, int]]:
    users = load_rows("users.json", "username")
    units = load_rows("response_units.json", "seed_code")
    groups = load_rows("user_groups.json", "code")
    memberships = [member for group in groups for member in group["members"]]
    if len(memberships) != len(set(memberships)):
        raise ValueError("Обучаемый не может входить в две demo-группы")
    engine = create_database_engine(get_settings())
    try:
        async with engine.begin() as connection:
            results = {
                "users": await upsert_users(connection, users),
                "response_units": await upsert_response_units(connection, units),
                "user_groups": await upsert_user_groups(connection, groups),
            }
        return results
    finally:
        await engine.dispose()


def main() -> None:
    for name, stats in asyncio.run(seed_demo()).items():
        print(f"{name}: {stats}")


if __name__ == "__main__":
    main()

"""Добавляет пользователей, роли и данные локального стенда.

Revision ID: 20260922_01
Revises: 20260921_01
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_01"
down_revision: str | None = "20260921_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role = sa.Enum("ADMIN", "INSTRUCTOR", "TRAINEE", name="user_role")


def upgrade() -> None:
    """Создаёт таблицу пользователей и три demo-учётные записи."""
    users_table = op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    op.bulk_insert(
        users_table,
        [
            {
                "id": 1,
                "username": "admin",
                "full_name": "Администратор стенда",
                "role": "ADMIN",
                "is_active": True,
            },
            {
                "id": 2,
                "username": "instructor",
                "full_name": "Преподаватель",
                "role": "INSTRUCTOR",
                "is_active": True,
            },
            {
                "id": 3,
                "username": "trainee",
                "full_name": "Диспетчер ДДС",
                "role": "TRAINEE",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    """Удаляет demo-пользователей вместе с таблицей и enum ролей."""
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_table("users")
    user_role.drop(op.get_bind(), checkfirst=False)

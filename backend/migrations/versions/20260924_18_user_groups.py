"""Add named groups for trainee users.

Revision ID: 20260924_18
Revises: 20260924_17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_18"
down_revision: str | None = "20260924_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "user_groups" not in inspector.get_table_names():
        op.create_table(
            "user_groups",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(160), nullable=False, unique=True),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index("ix_user_groups_name", "user_groups", ["name"])
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "group_id" not in user_columns:
        op.add_column("users", sa.Column("group_id", sa.Integer()))
        op.create_foreign_key(
            "fk_users_group_id_user_groups",
            "users",
            "user_groups",
            ["group_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_users_group_id", "users", ["group_id"])


def downgrade() -> None:
    user_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")
    }
    if "group_id" in user_columns:
        op.drop_index("ix_users_group_id", table_name="users")
        op.drop_constraint("fk_users_group_id_user_groups", "users", type_="foreignkey")
        op.drop_column("users", "group_id")
    if "user_groups" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("user_groups")

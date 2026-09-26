"""Link reusable user groups to session groups.

Revision ID: 20260926_100504_8a3d71
Revises: 20260925_145915_663d54
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_100504_8a3d71"
down_revision: str | None = "20260925_145915_663d54"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("training_groups", "name", type_=sa.String(160), existing_type=sa.String(120))
    op.add_column("user_groups", sa.Column("code", sa.String(40), nullable=True))
    op.add_column("user_groups", sa.Column("created_by_user_id", sa.Integer(), nullable=True))
    op.add_column(
        "user_groups", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false")
    )
    op.create_index("ix_user_groups_code", "user_groups", ["code"], unique=True)
    op.create_index("ix_user_groups_created_by_user_id", "user_groups", ["created_by_user_id"])
    op.create_foreign_key(
        "fk_user_groups_created_by_user_id_users", "user_groups", "users",
        ["created_by_user_id"], ["id"], ondelete="SET NULL",
    )
    op.add_column("training_groups", sa.Column("source_user_group_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_training_groups_source_user_group_id", "training_groups", ["source_user_group_id"]
    )
    op.create_foreign_key(
        "fk_training_groups_source_user_group_id_user_groups", "training_groups", "user_groups",
        ["source_user_group_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_training_groups_session_source", "training_groups",
        ["training_session_id", "source_user_group_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_training_groups_session_source", "training_groups", type_="unique")
    op.drop_constraint(
        "fk_training_groups_source_user_group_id_user_groups", "training_groups", type_="foreignkey"
    )
    op.drop_index("ix_training_groups_source_user_group_id", table_name="training_groups")
    op.drop_column("training_groups", "source_user_group_id")
    op.drop_constraint("fk_user_groups_created_by_user_id_users", "user_groups", type_="foreignkey")
    op.drop_index("ix_user_groups_created_by_user_id", table_name="user_groups")
    op.drop_index("ix_user_groups_code", table_name="user_groups")
    op.drop_column("user_groups", "is_archived")
    op.drop_column("user_groups", "created_by_user_id")
    op.drop_column("user_groups", "code")
    op.alter_column("training_groups", "name", type_=sa.String(120), existing_type=sa.String(160))

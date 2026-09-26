"""Store temporary subgroup membership within a training session.

Revision ID: 20260926_181043_a341ac
Revises: 20260926_152539_a73f0c
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_181043_a341ac"
down_revision: str | None = "20260926_152539_a73f0c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "training_groups",
        sa.Column("is_subgroup", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_table(
        "training_subgroup_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "training_session_id",
            sa.Integer(),
            sa.ForeignKey("training_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "training_group_id",
            sa.Integer(),
            sa.ForeignKey("training_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.UniqueConstraint("training_session_id", "user_id", name="uq_subgroup_session_user"),
        sa.UniqueConstraint("training_group_id", "user_id", name="uq_subgroup_group_user"),
    )
    op.create_index(
        "ix_training_subgroup_members_training_session_id",
        "training_subgroup_members",
        ["training_session_id"],
    )
    op.create_index(
        "ix_training_subgroup_members_training_group_id",
        "training_subgroup_members",
        ["training_group_id"],
    )
    op.create_index(
        "ix_training_subgroup_members_user_id", "training_subgroup_members", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_training_subgroup_members_user_id", table_name="training_subgroup_members")
    op.drop_index(
        "ix_training_subgroup_members_training_group_id", table_name="training_subgroup_members"
    )
    op.drop_index(
        "ix_training_subgroup_members_training_session_id", table_name="training_subgroup_members"
    )
    op.drop_table("training_subgroup_members")
    op.drop_column("training_groups", "is_subgroup")

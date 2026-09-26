"""Reusable snapshots of prepared incident cards.

Revision ID: 20260926_143353_2d0538
Revises: 20260926_103849_b152dc
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_143353_2d0538"
down_revision: str | None = "20260926_103849_b152dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_incident_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_template_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_saved_incident_cards_created_by_user_id", "saved_incident_cards", ["created_by_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_saved_incident_cards_created_by_user_id", table_name="saved_incident_cards")
    op.drop_table("saved_incident_cards")

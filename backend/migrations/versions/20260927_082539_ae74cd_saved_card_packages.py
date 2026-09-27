"""Store reusable packages of saved incident cards.

Revision ID: 20260927_082539_ae74cd
Revises: 20260926_194017_800c20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_082539_ae74cd"
down_revision: str | Sequence[str] | None = "20260926_194017_800c20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_incident_card_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(500), server_default="", nullable=False),
        sa.Column("card_ids", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_saved_incident_card_packages_created_by_user_id",
        "saved_incident_card_packages",
        ["created_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_saved_incident_card_packages_created_by_user_id",
        table_name="saved_incident_card_packages",
    )
    op.drop_table("saved_incident_card_packages")

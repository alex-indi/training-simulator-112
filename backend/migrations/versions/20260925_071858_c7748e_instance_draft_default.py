"""New scenario instances start as drafts for instructor text review.

Revision ID: 20260925_071858_c7748e
Revises: 20260925_04
"""

from alembic import op

revision: str = "20260925_071858_c7748e"
down_revision: str | None = "20260925_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("scenario_instances", "status", server_default="DRAFT")


def downgrade() -> None:
    op.alter_column("scenario_instances", "status", server_default="CONFIRMED")

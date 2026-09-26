"""Store allowed variation choices on scenario templates.

Revision ID: 20260926_101509_c72e4a
Revises: 20260925_145915_663d54
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_101509_c72e4a"
down_revision: str | None = "20260925_145915_663d54"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scenario_templates",
        sa.Column("variant_options", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("scenario_templates", "variant_options")

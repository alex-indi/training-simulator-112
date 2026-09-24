"""Stable seed identity for methodological demo scenarios.

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
    op.add_column("scenario_templates", sa.Column("seed_code", sa.String(120)))
    op.create_unique_constraint(
        "uq_scenario_templates_seed_code", "scenario_templates", ["seed_code"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_scenario_templates_seed_code", "scenario_templates", type_="unique")
    op.drop_column("scenario_templates", "seed_code")

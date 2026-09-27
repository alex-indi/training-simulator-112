"""Record the incident currently open on a trainee workstation.

Revision ID: 20260927_120957_9880b4
Revises: 20260927_082539_ae74cd
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_120957_9880b4"
down_revision: str | Sequence[str] | None = "20260927_082539_ae74cd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "training_runs",
        sa.Column(
            "open_incident_id",
            sa.Integer(),
            sa.ForeignKey("incidents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("training_runs", "open_incident_id")

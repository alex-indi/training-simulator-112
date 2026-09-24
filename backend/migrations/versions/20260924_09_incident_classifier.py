"""SRC-006 classifier and customer service catalog.

Revision ID: 20260924_09
Revises: 20260923_08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_09"
down_revision: str | None = "20260923_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incident_classifier_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_code", sa.String(160)),
        sa.Column("incident_group", sa.Text(), nullable=False),
        sa.Column("final_incident_type", sa.Text(), nullable=False),
        sa.Column("ekp35_type", sa.Text()),
        sa.Column("source_reference", sa.String(500), nullable=False, unique=True),
    )
    op.create_table(
        "incident_features",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("level", sa.String(80), nullable=False),
        sa.Column("source_column", sa.String(160), nullable=False),
        sa.Column("source_value", sa.Text(), nullable=False),
        sa.UniqueConstraint("level", "source_column", "source_value"),
    )
    op.create_table(
        "dispatch_services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("official_name", sa.Text(), nullable=False),
        sa.Column("organization", sa.Text()),
        sa.Column("service_level", sa.String(120)),
        sa.Column("source_reference", sa.String(500), nullable=False, unique=True),
    )
    op.create_table(
        "incident_rule_features",
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("incident_classifier_rules.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "feature_id",
            sa.Integer(),
            sa.ForeignKey("incident_features.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )
    op.create_table(
        "incident_rule_services",
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("incident_classifier_rules.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "service_id",
            sa.Integer(),
            sa.ForeignKey("dispatch_services.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("source_reference", sa.String(500), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("incident_rule_services")
    op.drop_table("incident_rule_features")
    op.drop_table("dispatch_services")
    op.drop_table("incident_features")
    op.drop_table("incident_classifier_rules")

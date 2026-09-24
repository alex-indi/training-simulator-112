"""Persist automatic assessment, instructor decisions and audit.

Revision ID: 20260924_11
Revises: 20260924_10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_11"
down_revision: str | None = "20260924_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assessment_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "training_run_id",
            sa.Integer(),
            sa.ForeignKey("training_runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("automatic_score", sa.Integer(), nullable=False),
        sa.Column("final_score", sa.Integer()),
        sa.Column("score_override", sa.Integer()),
        sa.Column("final_comment", sa.Text()),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("metrics", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_assessment_results_training_run_id", "assessment_results", ["training_run_id"]
    )
    op.create_table(
        "assessment_deviations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "assessment_result_id",
            sa.Integer(),
            sa.ForeignKey("assessment_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("critical", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("decision", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("is_manual", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index(
        "ix_assessment_deviations_assessment_result_id",
        "assessment_deviations",
        ["assessment_result_id"],
    )
    op.create_table(
        "assessment_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "assessment_result_id",
            sa.Integer(),
            sa.ForeignKey("assessment_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "changed_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_assessment_audit_assessment_result_id", "assessment_audit", ["assessment_result_id"]
    )


def downgrade() -> None:
    op.drop_table("assessment_audit")
    op.drop_table("assessment_deviations")
    op.drop_table("assessment_results")

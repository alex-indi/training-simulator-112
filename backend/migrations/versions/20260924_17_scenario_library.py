"""Scenario template library.

Revision ID: 20260924_17
Revises: 20260924_16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_17"
down_revision: str | None = "20260924_16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scenario_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("difficulty", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "classifier_rule_id",
            sa.Integer(),
            sa.ForeignKey("incident_classifier_rules.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("initial_title", sa.String(200), nullable=False, server_default=""),
        sa.Column("initial_description", sa.Text(), nullable=False, server_default=""),
        sa.Column("initial_caller_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("difficulty BETWEEN 1 AND 5", name="ck_scenario_difficulty"),
        sa.CheckConstraint("status IN ('DRAFT', 'READY', 'ARCHIVED')", name="ck_scenario_status"),
    )
    for field in ("status", "classifier_rule_id", "created_by_user_id"):
        op.create_index(f"ix_scenario_templates_{field}", "scenario_templates", [field])
    op.create_table(
        "scenario_template_object_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scenario_template_id",
            sa.Integer(),
            sa.ForeignKey("scenario_templates.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("selection_mode", sa.String(20), nullable=False),
        sa.Column(
            "object_type_id",
            sa.Integer(),
            sa.ForeignKey("object_types.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "specific_object_id",
            sa.Integer(),
            sa.ForeignKey("city_objects.id", ondelete="RESTRICT"),
        ),
        sa.CheckConstraint(
            "(selection_mode = 'GENERIC' AND specific_object_id IS NULL) OR "
            "(selection_mode = 'OBJECT_BOUND' AND specific_object_id IS NOT NULL)",
            name="ck_scenario_object_mode",
        ),
    )
    op.create_table(
        "scenario_template_required_object_tags",
        sa.Column(
            "object_rule_id",
            sa.Integer(),
            sa.ForeignKey("scenario_template_object_rules.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag",
            sa.String(120),
            sa.ForeignKey("object_tags_dictionary.code", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )
    op.create_table(
        "scenario_event_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scenario_template_id",
            sa.Integer(),
            sa.ForeignKey("scenario_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("offset_seconds", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_type", sa.String(40), nullable=False, server_default="SYSTEM"),
        sa.CheckConstraint("offset_seconds >= 0", name="ck_scenario_event_offset"),
    )
    op.create_index(
        "ix_scenario_event_templates_scenario_template_id",
        "scenario_event_templates",
        ["scenario_template_id"],
    )
    op.create_table(
        "scenario_template_services",
        sa.Column(
            "scenario_template_id",
            sa.Integer(),
            sa.ForeignKey("scenario_templates.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "service_id",
            sa.Integer(),
            sa.ForeignKey("dispatch_services.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("source", sa.String(20), nullable=False),
    )
    op.create_table(
        "scenario_expected_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scenario_template_id",
            sa.Integer(),
            sa.ForeignKey("scenario_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expected_action_type", sa.String(80), nullable=False),
        sa.Column("target_status", sa.String(80)),
        sa.Column(
            "expected_service_id",
            sa.Integer(),
            sa.ForeignKey("dispatch_services.id", ondelete="RESTRICT"),
        ),
        sa.Column("deadline_seconds", sa.Integer()),
        sa.Column("is_critical", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.CheckConstraint(
            "deadline_seconds IS NULL OR deadline_seconds >= 0", name="ck_scenario_action_deadline"
        ),
    )
    op.create_index(
        "ix_scenario_expected_actions_scenario_template_id",
        "scenario_expected_actions",
        ["scenario_template_id"],
    )
    op.create_table(
        "scenario_assessment_criteria",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scenario_template_id",
            sa.Integer(),
            sa.ForeignKey("scenario_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("weight", sa.Integer()),
        sa.Column("is_critical", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("weight IS NULL OR weight >= 0", name="ck_scenario_criterion_weight"),
    )
    op.create_index(
        "ix_scenario_assessment_criteria_scenario_template_id",
        "scenario_assessment_criteria",
        ["scenario_template_id"],
    )


def downgrade() -> None:
    op.drop_table("scenario_assessment_criteria")
    op.drop_table("scenario_expected_actions")
    op.drop_table("scenario_template_services")
    op.drop_table("scenario_event_templates")
    op.drop_table("scenario_template_required_object_tags")
    op.drop_table("scenario_template_object_rules")
    op.drop_table("scenario_templates")

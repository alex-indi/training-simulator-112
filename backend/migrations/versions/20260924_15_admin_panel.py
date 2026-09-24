"""Add administrative configuration, imports and audit.

Revision ID: 20260924_15
Revises: 20260924_14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_15"
down_revision: str | None = "20260924_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "SELECT setval(pg_get_serial_sequence('users', 'id'), "
        "COALESCE((SELECT MAX(id) FROM users), 1), true)"
    )
    inspector = sa.inspect(op.get_bind())
    admin_tables = {
        "import_runs",
        "data_quality_issues",
        "ai_provider_config",
        "ai_usage_daily",
        "admin_audit",
    }
    existing_admin_tables = admin_tables & set(inspector.get_table_names())
    scenario_columns = {column["name"] for column in inspector.get_columns("training_scenarios")}
    if "is_archived" not in scenario_columns:
        op.add_column(
            "training_scenarios",
            sa.Column("is_archived", sa.Boolean(), server_default=sa.false(), nullable=False),
        )
    if existing_admin_tables == admin_tables:
        return  # Совместимость с локальной WIP-миграцией ранней версии UT112-31.
    if existing_admin_tables:
        raise RuntimeError(
            f"Частично создана административная схема: {sorted(existing_admin_tables)}"
        )
    op.create_table(
        "import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("dataset_id", sa.String(120)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("received", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("review", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errors", sa.Integer(), server_default="0", nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_import_runs_source", "import_runs", ["source"])
    op.create_index("ix_import_runs_status", "import_runs", ["status"])
    op.create_table(
        "data_quality_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(160)),
        sa.Column("status", sa.String(40), server_default="OPEN", nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    for column in ("kind", "entity_type", "status"):
        op.create_index(f"ix_data_quality_issues_{column}", "data_quality_issues", [column])
    op.create_table(
        "ai_provider_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(80), server_default="OPENAI_COMPATIBLE", nullable=False),
        sa.Column("model", sa.String(160), server_default="", nullable=False),
        sa.Column(
            "base_url", sa.String(500), server_default="https://api.openai.com/v1", nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), server_default="30", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "ai_usage_daily",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("requests", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fallbacks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errors", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "admin_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "admin_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(160)),
        sa.Column("before", sa.JSON()),
        sa.Column("after", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    for column in ("admin_id", "action", "entity_type", "created_at"):
        op.create_index(f"ix_admin_audit_{column}", "admin_audit", [column])


def downgrade() -> None:
    op.drop_table("admin_audit")
    op.drop_table("ai_usage_daily")
    op.drop_table("ai_provider_config")
    op.drop_table("data_quality_issues")
    op.drop_table("import_runs")
    op.drop_column("training_scenarios", "is_archived")

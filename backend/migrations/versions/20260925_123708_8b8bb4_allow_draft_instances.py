"""Allow scenario instances to remain drafts while an instructor reviews them.

Revision ID: 20260925_123708_8b8bb4
Revises: 20260925_074331_b9d594
"""

from alembic import op

revision: str = "20260925_123708_8b8bb4"
down_revision: str | None = "20260925_074331_b9d594"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_instance_status", "scenario_instances", type_="check")
    op.create_check_constraint(
        "ck_instance_status",
        "scenario_instances",
        "status IN ('DRAFT', 'CONFIRMED', 'CANCELLED')",
    )


def downgrade() -> None:
    op.execute("UPDATE scenario_instances SET status = 'CANCELLED' WHERE status = 'DRAFT'")
    op.drop_constraint("ck_instance_status", "scenario_instances", type_="check")
    op.create_check_constraint(
        "ck_instance_status", "scenario_instances", "status IN ('CONFIRMED', 'CANCELLED')"
    )

"""Add a dictionary for semantic object tags.

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
        "object_tags_dictionary",
        sa.Column("code", sa.String(120), primary_key=True),
        sa.Column("name", sa.String(250), nullable=False),
        sa.Column("description", sa.Text()),
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO object_tags_dictionary (code, name) "
            "SELECT DISTINCT tag, tag FROM object_tags"
        )
    )
    op.create_foreign_key(
        "fk_object_tags_dictionary_code",
        "object_tags",
        "object_tags_dictionary",
        ["tag"],
        ["code"],
        ondelete="RESTRICT",
    )
    connection.execute(
        sa.text(
            "UPDATE object_types SET parent_id = "
            "(SELECT id FROM object_types WHERE code = 'BUILDING') "
            "WHERE code = 'TRANSPORT' AND parent_id IS NULL"
        )
    )


def downgrade() -> None:
    op.execute(
        "UPDATE object_types SET parent_id = NULL WHERE code = 'TRANSPORT' "
        "AND parent_id = (SELECT id FROM object_types WHERE code = 'BUILDING')"
    )
    op.drop_constraint("fk_object_tags_dictionary_code", "object_tags", type_="foreignkey")
    op.drop_table("object_tags_dictionary")
